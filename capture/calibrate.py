"""
calibrate.py — OCR クロップ座標調整ツール

使い方:
  # エミュレーター起動後、ロケット画面を表示した状態で実行
  python capture/calibrate.py

操作:
  - マウスドラッグで倍率テキストエリアを選択
  - Enter / Space で座標を config.yml に保存
  - q / Esc でキャンセル
"""

import subprocess
import sys
import io
import pathlib

import cv2
import numpy as np
import yaml
from PIL import Image

CONFIG_PATH = pathlib.Path(__file__).parent / "config.yml"

# ---------- ADB screencap ----------

def take_screenshot() -> np.ndarray:
    result = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"adb screencap 失敗: {result.stderr.decode()}")
    img = Image.open(io.BytesIO(result.stdout))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ---------- マウスコールバック ----------

_drag_start = None
_drag_rect = None  # (x, y, w, h)
_drawing = False


def _mouse_cb(event, x, y, flags, param):
    global _drag_start, _drag_rect, _drawing
    if event == cv2.EVENT_LBUTTONDOWN:
        _drag_start = (x, y)
        _drawing = True
    elif event == cv2.EVENT_MOUSEMOVE and _drawing:
        x0, y0 = _drag_start
        _drag_rect = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
    elif event == cv2.EVENT_LBUTTONUP:
        _drawing = False


# ---------- メイン ----------

def main() -> None:
    print("スクリーンショットを取得中...")
    try:
        frame = take_screenshot()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    clone = frame.copy()
    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", _mouse_cb)

    print("倍率テキストが表示されているエリアをドラッグで選択してください。")
    print("  Enter / Space : 保存して終了")
    print("  q / Esc       : キャンセル")

    while True:
        display = clone.copy()
        if _drag_rect is not None:
            x, y, w, h = _drag_rect
            cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.imshow("calibrate", display)

        key = cv2.waitKey(20) & 0xFF
        if key in (13, 32):  # Enter or Space
            if _drag_rect is None:
                print("範囲が選択されていません。ドラッグしてください。")
                continue
            break
        if key in (ord("q"), 27):  # q or Esc
            print("キャンセルしました。")
            cv2.destroyAllWindows()
            sys.exit(0)

    cv2.destroyAllWindows()

    x, y, w, h = _drag_rect
    print(f"\n選択した座標: x={x}, y={y}, width={w}, height={h}")

    # config.yml 更新
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    config["ocr_region"] = {"x": x, "y": y, "width": w, "height": h}

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    print(f"config.yml を更新しました: {CONFIG_PATH}")

    # OCR プレビュー
    import pytesseract
    crop = frame[y : y + h, x : x + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    text = pytesseract.image_to_string(binary, config="--psm 7 -c tessedit_char_whitelist=0123456789.")
    print(f"OCR プレビュー: '{text.strip()}'")


if __name__ == "__main__":
    main()
