# capture セットアップガイド

`capture` は USB 接続した Android 実機の画面を ADB で取得し、OCR でクラッシュ倍率を抽出して API に送信します。

## 前提

- Docker / Docker Compose
- Android platform-tools (`adb`)
- USB デバッグを有効化した Android 実機
- API が起動していること（`docker compose up -d api` など）

## 1. 設定ファイル

`capture/config.yml`:

```yaml
adb:
  # "usb" は 1 台接続前提。複数接続時はシリアル指定を推奨
  device: "usb"

api:
  base_url: "http://localhost:8001"
  username: ""
  password: ""

capture:
  # [y_start, y_end, x_start, x_end]
  bar_crop: [695, 755, 240, 820]
  poll_interval: 5
  scale: 4
```

環境変数で以下を上書きできます。

- `CAPTURE_USERNAME`
- `CAPTURE_PASSWORD`
- `API_BASE_URL`

## 2. USB 接続確認

```bash
adb devices
```

`device` が 1 台だけ表示される状態にしてください。複数台接続する場合は `capture/config.yml` の `adb.device` にシリアルを指定します。

## 3. Docker で起動

```bash
cd /path/to/rocket
cat > .env <<'ENV'
CAPTURE_USERNAME=admin
CAPTURE_PASSWORD=changeme
ENV

# API を起動
docker compose up -d api

# capture を起動
docker compose up --build capture
```

`docker-compose.yml` の capture サービスは次の経路で通信します。

- API: `http://api:8000`（Compose ネットワーク）
- ADB: `ADB_SERVER_SOCKET=tcp:host.docker.internal:5037`

## 4. ホストで直接実行（Docker なし）

```bash
sudo apt install -y android-tools-adb tesseract-ocr tesseract-ocr-eng
python3 -m venv capture/.venv
source capture/.venv/bin/activate
pip install -r capture/requirements.txt

export CAPTURE_USERNAME=admin
export CAPTURE_PASSWORD=changeme
export API_BASE_URL=http://localhost:8001

python capture/ocr.py
```

## 5. 動作確認

ログ例:

```text
[INFO] ログイン成功: http://...
[INFO] 新しい爆発倍率検出: 2.45x
[INFO] POST 成功: inserted=1, total=123
```

## 6. トラブルシューティング

### ADB 接続に失敗する

```bash
adb kill-server
adb start-server
adb devices
```

### `more than one device/emulator` が出る

- 接続デバイスを 1 台にする
- または `capture/config.yml` の `adb.device` に対象シリアルを設定する

### OCR が読み取れない

- `capture/config.yml` の `capture.bar_crop` を手動調整する
- `python capture/ocr.py --debug` で `/tmp/ocr_bar.png`, `/tmp/ocr_thresh.png` を確認する
