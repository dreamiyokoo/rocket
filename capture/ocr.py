#!/usr/bin/env python3
"""
ocr.py — ADB スクリーンショット → OCR → /api/v1/rounds 送信

使い方:
    python3 capture/ocr.py                   # 継続監視モード
    python3 capture/ocr.py --once            # 1回スキャンして終了
    python3 capture/ocr.py --debug           # デバッグ画像を /tmp に保存
"""

import argparse
import base64
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytesseract
import yaml
from pytesseract import Output

# ────────────────────────────────────────────────
# 設定読み込み
# ────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yml"

COLOR_RANGE_MAP = {
    "blue": (1.01, 2.00),
    "green": (2.01, 5.00),
    "yellow": (5.01, 10.00),
    "red": (10.01, 501.00),
}


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


def recover_adb_connection(device: str) -> None:
    """ADB 接続が不安定なときの軽量リカバリ。"""
    try:
        subprocess.run(adb_cmd(device, "reconnect"), capture_output=True, timeout=8)
        subprocess.run(adb_cmd(device, "wait-for-device"), capture_output=True, timeout=15)
        print("[INFO] ADB 接続をリカバリしました")
    except subprocess.TimeoutExpired:
        print("[WARN] ADB リカバリがタイムアウトしました", file=sys.stderr)


def take_screenshot(device: str) -> np.ndarray | None:
    """adb screencap で画像を取得して numpy 配列で返す"""
    try:
        result = subprocess.run(
            adb_cmd(device, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore")
            print(f"[WARN] screencap failed: {stderr}", file=sys.stderr)
            if (
                "no devices/emulators found" in stderr
                or "cannot connect to daemon" in stderr
                or "Connection refused" in stderr
            ):
                recover_adb_connection(device)
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

def encode_image_data_url(img: np.ndarray, extension: str, mime_type: str, params: list[int] | None = None) -> str:
    options = params if params is not None else []
    ok, encoded = cv2.imencode(extension, img, options)
    if not ok:
        raise ValueError(f"failed to encode image as {extension}")
    return f"data:{mime_type};base64,{base64.b64encode(encoded.tobytes()).decode('ascii')}"


def detect_pill_regions(white_mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    # 数字と下線を横方向にまとめて、各ピルの文字領域を1塊にする
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (41, 25))
    mask = cv2.dilate(white_mask, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    height, width = white_mask.shape[:2]
    min_w = max(70, width // 20)
    min_h = max(50, height // 4)
    regions: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < min_w or h < min_h:
            continue
        if y + h < height // 4:
            continue
        pad_x = min(70, x)
        pad_y = min(26, y)
        x0 = max(0, x - pad_x)
        y0 = max(0, y - pad_y)
        x1 = min(width, x + w + pad_x)
        y1 = min(height, y + h + pad_y)
        regions.append((x0, y0, x1, y1))
    regions.sort(key=lambda region: region[0])
    return regions[:4]


def classify_pill_color(pill_img: np.ndarray, pill_mask: np.ndarray) -> str:
    hsv = cv2.cvtColor(pill_img, cv2.COLOR_BGR2HSV)
    bg_mask = (hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 40) & (pill_mask == 0)
    pixels = hsv[bg_mask]
    if len(pixels) == 0:
        pixels = hsv.reshape(-1, 3)

    hue = float(np.median(pixels[:, 0]))
    if 35 <= hue < 85:
        return "green"
    if 15 <= hue < 35:
        return "yellow"
    if hue < 10 or hue >= 170:
        return "red"
    return "blue"


def parse_ocr_number(text: str) -> float | None:
    normalized = text.replace(" ", "").replace("\n", "")
    match = re.search(r"\d+\.\d+|\b\d{3,}\b", normalized)
    if not match:
        return None
    value = round(float(match.group(0)), 2)
    if 1.01 <= value <= 501.00:
        return value
    return None


def ocr_candidates_for_pill(pill_img: np.ndarray, pill_mask: np.ndarray) -> list[dict]:
    gray = cv2.cvtColor(pill_img, cv2.COLOR_BGR2GRAY)
    _, gray_threshold = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    variants = [
        ("base", pill_mask),
        (
            "close",
            cv2.morphologyEx(
                pill_mask,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            ),
        ),
        (
            "dilate",
            cv2.dilate(
                pill_mask,
                cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
                iterations=1,
            ),
        ),
        ("gray", gray),
        ("gray-threshold", gray_threshold),
    ]

    candidates: list[dict] = []
    for variant_name, variant in variants:
        data = pytesseract.image_to_data(
            variant,
            config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.",
            output_type=Output.DICT,
        )
        tokens = [text.strip() for text in data["text"] if text.strip()]
        confs = [float(conf) for conf in data["conf"] if conf not in {"-1", -1}]
        raw_text = "".join(tokens)
        value = parse_ocr_number(raw_text)
        if value is None:
            continue
        candidates.append(
            {
                "variant": variant_name,
                "raw_text": raw_text,
                "value": value,
                "confidence": float(np.mean(confs)) if confs else 0.0,
            }
        )
    return candidates


def is_value_consistent_with_color(value: float, pill_color: str) -> bool:
    lo, hi = COLOR_RANGE_MAP[pill_color]
    return lo <= value <= hi


def correct_value_with_color(value: float, pill_color: str) -> float | None:
    if is_value_consistent_with_color(value, pill_color):
        return value

    integer_part = int(value)
    fractional_part = round(value - integer_part, 2)

    # 青帯は 1.xx か 2.00 に限られるため、整数部だけの誤読は保守的に補正できる。
    if pill_color == "blue":
        corrected = round(1 + fractional_part, 2)
        if is_value_consistent_with_color(corrected, pill_color):
            return corrected

    return None


def choose_pill_value(pill_color: str, candidates: list[dict]) -> tuple[float | None, str]:
    if not candidates:
        return None, ""

    ranked = []
    for candidate in candidates:
        score = candidate["confidence"]
        if is_value_consistent_with_color(candidate["value"], pill_color):
            score += 100
        ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)

    best = ranked[0][1]
    corrected = correct_value_with_color(best["value"], pill_color)
    if corrected is not None and corrected != best["value"]:
        return corrected, f"{best['raw_text']} -> {corrected:.2f} ({pill_color})"
    return best["value"], best["raw_text"]


def extract_history_bar_preview(
    img: np.ndarray,
    crop: list[int],
    scale: int,
    debug: bool = False,
) -> dict:
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

    pill_regions = detect_pill_regions(white_mask)
    result = []
    raw_lines: list[str] = []
    colors: list[str] = []
    for x0, y0, x1, y1 in pill_regions:
        pill_img = large[y0:y1, x0:x1]
        pill_mask = white_mask[y0:y1, x0:x1]
        pill_color = classify_pill_color(pill_img, pill_mask)
        candidates = ocr_candidates_for_pill(pill_img, pill_mask)
        value, raw_text = choose_pill_value(pill_color, candidates)
        if value is None:
            continue
        result.append(value)
        raw_lines.append(raw_text or f"{value:.2f}")
        colors.append(pill_color)

    if debug:
        print(f"[DEBUG] OCR raw text: {repr(raw_lines)}")
        print(f"[DEBUG] pill colors: {colors}")

    text = "\n".join(raw_lines)
    return {
        "values": result,
        "raw_text": text.strip(),
        "bar_image": encode_image_data_url(bar, ".jpg", "image/jpeg", [int(cv2.IMWRITE_JPEG_QUALITY), 85]),
        "mask_image": encode_image_data_url(white_mask, ".png", "image/png"),
        "scale": scale,
        "pill_colors": colors,
    }


def post_capture_preview(client: httpx.Client, base_url: str, token: str, preview: dict) -> None:
    resp = client.post(
        f"{base_url}/api/v1/capture/preview",
        json=preview,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()


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


def post_rounds(client: httpx.Client, base_url: str, token: str, values: list[float]) -> dict:
    resp = client.post(
        f"{base_url}/api/v1/rounds",
        json={"values": values},
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

        last_values: list[float] = []  # 前回スキャン時の全値（oldest-first順）
        token_refreshed_at = time.time()

        while True:
            # 24時間ごとにトークン再取得（JWT_EXPIRE_MINUTES=1440 対応）
            if time.time() - token_refreshed_at > 23 * 3600:
                refreshed = False
                for retry in range(3):
                    try:
                        token = login(client, base_url, username, password)
                        token_refreshed_at = time.time()
                        print("[INFO] トークン再取得")
                        refreshed = True
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError) as e:
                        wait = 2 ** retry
                        print(f"[WARN] トークン再取得失敗 ({retry + 1}/3): {e}", file=sys.stderr)
                        if retry < 2:
                            time.sleep(wait)
                if not refreshed:
                    print("[WARN] トークン再取得をスキップし、既存トークンで継続します", file=sys.stderr)

            img = take_screenshot(device)
            if img is None:
                print("[WARN] スクリーンショット取得失敗。再試行します...")
                time.sleep(interval)
                continue

            preview = extract_history_bar_preview(img, crop, scale, debug=debug)
            preview_payload = {
                **preview,
                "captured_at": datetime.now(UTC).isoformat(),
            }

            try:
                post_capture_preview(client, base_url, token, preview_payload)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    try:
                        token = login(client, base_url, username, password)
                        token_refreshed_at = time.time()
                        post_capture_preview(client, base_url, token, preview_payload)
                    except (httpx.RequestError, httpx.HTTPStatusError) as preview_error:
                        print(f"[WARN] プレビュー送信失敗: {preview_error}", file=sys.stderr)
                else:
                    print(f"[WARN] プレビュー送信失敗: {e.response.status_code} {e.response.text}", file=sys.stderr)
            except httpx.RequestError as e:
                print(f"[WARN] プレビュー送信失敗: {e}", file=sys.stderr)

            values = preview["values"]

            if not values:
                if debug:
                    print("[DEBUG] OCR: 数値なし")
                time.sleep(interval)
                continue

            # OCR結果はバーの左→右（新→旧）順なので反転してoldest-first順に
            values_asc = list(reversed(values))

            # 前回と比較して新しくなった先頭部分を特定
            new_values: list[float] = []
            if not last_values:
                # 初回は最新1件だけ投稿
                new_values = [values_asc[-1]]
            else:
                # last_values の末尾 k 件と values_asc の先頭 k 件が一致する最大 k を探す
                # 例: last=[A,B,C,1.01] values=[B,C,1.01,X] → k=3 → new=[X]
                # こうすることで同じ値（1.01 連続等）の誤挿入を防ぐ
                max_check = min(len(last_values), len(values_asc))
                best_overlap = 0
                for k in range(max_check, 0, -1):
                    if last_values[-k:] == values_asc[:k]:
                        best_overlap = k
                        break
                if best_overlap == 0:
                    # 重複がまったくない場合（大きくリストが変わった等）→ 最新1件を投稿
                    new_values = [values_asc[-1]]
                else:
                    new_values = values_asc[best_overlap:]

            if new_values:
                print(f"[INFO] 新しい爆発倍率検出: {new_values}")
                try:
                    result = post_rounds(client, base_url, token, new_values)
                    print(f"[INFO] POST 成功: inserted={result['inserted']}, total={result['total']}")
                    last_values = values_asc
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        print("[WARN] トークン期限切れの可能性。再ログインして再送します", file=sys.stderr)
                        try:
                            token = login(client, base_url, username, password)
                            token_refreshed_at = time.time()
                            result = post_rounds(client, base_url, token, new_values)
                            print(f"[INFO] POST 成功: inserted={result['inserted']}, total={result['total']}")
                            last_values = values_asc
                        except (httpx.RequestError, httpx.HTTPStatusError) as relogin_error:
                            print(f"[ERROR] 再ログイン後の POST 失敗: {relogin_error}", file=sys.stderr)
                    else:
                        print(f"[ERROR] POST 失敗: {e.response.status_code} {e.response.text}", file=sys.stderr)
                except httpx.RequestError as e:
                    print(f"[ERROR] リクエストエラー: {e}", file=sys.stderr)
            else:
                if debug:
                    print(f"[DEBUG] 変化なし (OCR全件: {values_asc})")

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
