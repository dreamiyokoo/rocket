#!/usr/bin/env bash
# run.sh — USB 接続 Android から爆発倍率を継続取得して API に送信する
#
# 使い方:
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh --once
#   CAPTURE_USERNAME=admin CAPTURE_PASSWORD=pass ./capture/run.sh --debug

set -euo pipefail

cd "$(dirname "$0")/.."

# 依存確認
if ! command -v adb &>/dev/null; then
    echo "[ERROR] adb が見つかりません。Android SDK (platform-tools) をインストールしてください。"
    exit 1
fi

# デバイス接続確認
DEVICES=$(adb devices | grep -c "device$" || true)
if [[ "$DEVICES" -eq 0 ]]; then
    echo "[ERROR] ADB デバイスが見つかりません。"
    echo "  1. Android の開発者オプション → USB デバッグ を ON にしてください。"
    echo "  2. USB を挿し直して 'このPCを信頼しますか？' を許可してください。"
    exit 1
fi
if [[ "$DEVICES" -gt 1 ]]; then
    echo "[ERROR] ADB デバイスが複数接続されています (${DEVICES}台)。"
    echo "  capture/config.yml の adb.device にシリアルを指定するか、1台だけ接続してください。"
    adb devices
    exit 1
fi

echo "[INFO] デバイス接続確認 OK (${DEVICES}台)"

# Python スクリプト実行
exec python3 capture/ocr.py "$@"
