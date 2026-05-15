#!/usr/bin/env python3
"""
ocr.py — ADB スクリーンショット → OCR → /api/v1/rounds 送信

使い方:
    python3 capture/ocr.py                   # 継続監視モード
    python3 capture/ocr.py --once            # 1回スキャンして終了
    python3 capture/ocr.py --debug           # デバッグ画像を /tmp に保存
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytesseract
import yaml

# ────────────────────────────────────────────────
# 設定読み込み
# ────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # 環境変数で上書き
    if os.getenv("CAPTURE_USERNAME"):
        cfg["api"]["username"] = os.getenv("CAPTURE_USERNAME")
    if os.getenv("CAPTURE_PASSWORD"):
        cfg["api"]["password"] = os.getenv("CAPTURE_PASSWORD")
    if os.getenv("API_BASE_URL"):
        cfg["api"]["base_url"] = os.getenv("API_BASE_URL")
    return cfg


# ────────────────────────────────────────────────
# ADB ユーティリティ
# ────────────────────────────────────────────────

def adb_cmd(device: str, *args: str) -> list[str]:
    base = ["adb"]
    if device != "usb":
        base += ["-s", device]
    return base + list(args)


def take_screenshot(device: str) -> np.ndarray | None:
    """adb screencap で画像を取得して numpy 配列で返す"""
    try:
        result = subprocess.run(
            adb_cmd(device, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            print(f"[WARN] screencap failed: {result.stderr.decode()}", file=sys.stderr)
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except subprocess.TimeoutExpired:
        print("[WARN] screencap timed out", file=sys.stderr)
        return None


# ────────────────────────────────────────────────
# OCR
# ────────────────────────────────────────────────

def ocr_history_bar(img: np.ndarray, crop: list[int], scale: int, debug: bool = False) -> list[float]:
    """
    履歴バー（最新4件のピル）から倍率リストを抽出する。
    crop = [y_start, y_end, x_start, x_end]

    HSV 白テキストマスク方式: 白い文字（低彩度・高輝度）だけを抽出し、
    ピルの背景色（緑・青・赤など）の影響を排除する。
    """
    y0, y1, x0, x1 = crop
    bar = img[y0:y1, x0:x1]

    # 拡大してOCR精度向上
    large = cv2.resize(bar, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)

    # HSV でピル背景色を除外し白テキストだけ抽出
    hsv = cv2.cvtColor(large, cv2.COLOR_BGR2HSV)
    lower_white = np.array([0, 0, 170])
    upper_white = np.array([180, 80, 255])
    white_mask = cv2.inRange(hsv, lower_white, upper_white)

    if debug:
        cv2.imwrite("/tmp/ocr_bar.png", bar)
        cv2.imwrite("/tmp/ocr_thresh.png", white_mask)

    # PSM 11: スパーステキスト（ピル間の空白に強い）
    text = pytesseract.image_to_string(white_mask, config="--oem 1 --psm 11 -c tessedit_char_whitelist=0123456789.")
    values = re.findall(r"\d+\.\d+", text)
    return [float(v) for v in values]


# ────────────────────────────────────────────────
# API クライアント
# ────────────────────────────────────────────────

def login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    resp = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def post_round(client: httpx.Client, base_url: str, token: str, value: float) -> dict:
    resp = client.post(
        f"{base_url}/api/v1/rounds",
        json={"values": [value]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ────────────────────────────────────────────────
# メインループ
# ────────────────────────────────────────────────

def run(cfg: dict, once: bool = False, debug: bool = False) -> None:
    device = cfg["adb"]["device"]
    base_url = cfg["api"]["base_url"]
    username = cfg["api"]["username"]
    password = cfg["api"]["password"]
    crop = cfg["capture"]["bar_crop"]
    interval = cfg["capture"]["poll_interval"]
    scale = cfg["capture"]["scale"]

    if not username or not password:
        print("[ERROR] username/password が設定されていません。"
              "config.yml か環境変数 CAPTURE_USERNAME / CAPTURE_PASSWORD を設定してください。",
              file=sys.stderr)
        sys.exit(1)

    with httpx.Client() as client:
        # Docker 起動時など API が未起動の場合にリトライ
        for attempt in range(30):
            try:
                token = login(client, base_url, username, password)
                print(f"[INFO] ログイン成功: {base_url}")
                break
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt < 29:
                    print(f"[INFO] API 接続待ち ({attempt + 1}/30): {e}", file=sys.stderr)
                    time.sleep(5)
                else:
                    print(f"[ERROR] API に接続できませんでした: {e}", file=sys.stderr)
                    sys.exit(1)

        last_latest: float | None = None
        token_refreshed_at = time.time()

        while True:
            # 24時間ごとにトークン再取得（JWT_EXPIRE_MINUTES=1440 対応）
            if time.time() - token_refreshed_at > 23 * 3600:
                token = login(client, base_url, username, password)
                token_refreshed_at = time.time()
                print("[INFO] トークン再取得")

            img = take_screenshot(device)
            if img is None:
                print("[WARN] スクリーンショット取得失敗。再試行します...")
                time.sleep(interval)
                continue

            values = ocr_history_bar(img, crop, scale, debug=debug)

            if not values:
                if debug:
                    print("[DEBUG] OCR: 数値なし")
                time.sleep(interval)
                continue

            # 最新値（バーの先頭 = 直近ラウンド）
            latest = values[0]

            if latest != last_latest:
                print(f"[INFO] 新しい爆発倍率検出: {latest}x")
                try:
                    result = post_round(client, base_url, token, latest)
                    print(f"[INFO] POST 成功: inserted={result['inserted']}, total={result['total']}")
                    last_latest = latest
                except httpx.HTTPStatusError as e:
                    print(f"[ERROR] POST 失敗: {e.response.status_code} {e.response.text}", file=sys.stderr)
                except httpx.RequestError as e:
                    print(f"[ERROR] リクエストエラー: {e}", file=sys.stderr)
            else:
                if debug:
                    print(f"[DEBUG] 変化なし: {latest}x (OCR全件: {values})")

            if once:
                break

            time.sleep(interval)


# ────────────────────────────────────────────────
# エントリポイント
# ────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rocket OCR capture")
    parser.add_argument("--once", action="store_true", help="1回スキャンして終了")
    parser.add_argument("--debug", action="store_true", help="デバッグ画像を /tmp に保存")
    args = parser.parse_args()

    cfg = load_config()
    run(cfg, once=args.once, debug=args.debug)
