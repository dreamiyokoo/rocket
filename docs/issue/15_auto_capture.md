# [自動化] Android エミュレーター自動起動・OCR 倍率取得システム

## 概要

Android Studio Emulator 上でロケットゲームアプリを自動起動し、  
スクリーンショット → OCR → 倍率抽出 → API 送信までを完全自動化する。

手動でロケット画面を見ながら倍率を入力する作業をゼロにし、  
リアルタイム解析の継続的なデータ収集を無人で行う。

---

## システム全体アーキテクチャ

```
Ubuntu Host
┌─────────────────────────────────────────────────┐
│  [Android Emulator]  ← 画面が見える！          │
│  emulator -avd RocketDevice &              │
│  ADB Server :5037 ←─────────────────────┐ │
│                                            │ │
│  Docker Compose (bridge network)            │ │
│  ┌──────────────────────────────┐    │ │
│  │ capture コンテナ                       │    │ │
│  │   adb client ─────────────────────┼─┘ │
│  │   └─ screencap                       │    │
│  │   ocr.py                            │    │
│  │   ├─ OpenCV クロップ・二値化         │    │
│  │   ├─ Tesseract OCR: 数値抽出         │    │
│  │   └─ POST /api/v1/rounds             │    │
│  └──────────────────────────────┘    │
│       ↓                                 │
│  既存 Docker Compose                      │
│  (api / db / redis / frontend)            │
└─────────────────────────────────────────────────┘
```

> **ポイント**: `capture` コンテナは ADB クライアント + OCR 処理を担当し、  
> ADB は `ADB_SERVER_SOCKET=tcp:host.docker.internal:5037` でホスト側サーバーに接続する。

---

## ディレクトリ構成

```
rocket/
└─ capture/
    ├─ Dockerfile          # OCR コンテナ
    ├─ requirements.txt    # opencv-python, pytesseract, httpx, ...
    ├─ run.sh              # ADB 接続確認 + ocr.py 起動
    ├─ ocr.py              # スクリーンショット → 倍率 → API 送信
    └─ config.yml          # ADB・API・OCR設定
```

`docker-compose.yml` に `capture` サービスを追加する。

---

## 実装フェーズ

### Phase 1: エミュレーター起動 + APK インストール

**担当**: ホスト (手動 or スクリプト) + `capture/run.sh`

**ホスト側でエミュレーターを起動する（画面が見える）**:

```bash
# Android Studio の AVD Manager から起動、または:
emulator -avd RocketDevice &
```

`capture` コンテナは起動後、ホストの ADB サーバー（`5037`）に接続します。

```bash
docker-compose up capture
# → 接続済みデバイスを利用して OCR ループを実行
```

**APK インストール**（必要な場合は手動実行）:

```bash
adb install -r "${APK_PATH}"
```

**APK の用意方法**:

| 方法 | コマンド | 備考 |
|------|---------|------|
| 実機からバックアップ | `adb backup -apk -noshared com.example.rocket` | Android 12以降は制限あり |
| root 実機からコピー | `adb pull /data/app/.../base.apk ./capture/app.apk` | root 必要 |
| `apkeep` で取得 | `apkeep -a com.example.rocket app.apk` | Google Play 認証が必要 |

取得した APK を `capture/app.apk` として配置し、`.env` に `APK_FILE=./capture/app.apk` を設定する。

---

### Phase 2: スクリーンショット取得 + OCR

**担当ファイル**: `capture/ocr.py`

```
処理フロー:
  1. adb exec-out screencap -p → PNG バイナリ取得
  2. OpenCV でロード
  3. 倍率テキスト表示エリアをクロップ（座標は config.yml で設定）
  4. グレースケール変換 → 二値化 → Tesseract で数値読み取り
  5. 正規表現で "123.45x" or "1.23" 形式を抽出
  6. 前回値と比較して「新しいラウンド完了」を検出
  7. POST /api/v1/rounds に送信
```

**新ラウンド検出ロジック**:

```
状態機械:
  RISING   → 倍率が増加中（ゲーム進行中）
  CRASHED  → 倍率がリセット（= 1.01 付近）→ 1ラウンド完了
  WAITING  → 次ラウンド開始待ち

CRASHED 検出時に前のピーク値を rounds テーブルに送信する。
```

---

### Phase 3: API 送信

既存の `POST /api/v1/rounds` エンドポイントを使用する。  
`config.yml`（または環境変数）で設定した `username` / `password` で
`/api/v1/auth/login` にログインして JWT を取得し、ヘッダーに付与する。

```python
httpx.post(
    f"{API_URL}/api/v1/rounds",
    json={"values": [multiplier]},
    headers={"Authorization": f"Bearer {token}"},
)
```

---

### Phase 4: 障害復旧・自動再起動

エミュレーターやアプリがクラッシュした場合に自動復旧する。

```bash
# run.sh 内で watchdog ループ
while true; do
  if ! adb shell pidof "$APP_PACKAGE" > /dev/null 2>&1; then
    echo "アプリがクラッシュ検出 → 再起動"
    restart_app
  fi
  sleep 10
done
```

systemd の `Restart=always` と組み合わせて、プロセス自体が落ちても復旧させる。

---

### Phase 5: docker-compose 統合

`docker-compose.yml` に `capture` サービスを追加する。

```yaml
capture:
  build: ./capture
  environment:
    API_BASE_URL: http://api:8000
    CAPTURE_USERNAME: ${CAPTURE_USERNAME}
    CAPTURE_PASSWORD: ${CAPTURE_PASSWORD}
    ADB_SERVER_SOCKET: tcp:host.docker.internal:5037
  extra_hosts:
    - "host.docker.internal:host-gateway"
  restart: unless-stopped
  depends_on:
    - api
```

---

## 設定ファイル仕様

`capture/config.yml`:

```yaml
adb:
  # usb の場合は 1 台接続前提。複数接続時はシリアル指定を推奨
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

---

## クロップ座標の調整

`calibrate.py` は未実装のため、`capture.bar_crop` を手動調整する。
`python capture/ocr.py --debug` で `/tmp/ocr_bar.png` と `/tmp/ocr_thresh.png`
を確認しながら値を合わせる。

---

## 受け入れ条件

> **実装方針変更**: エミュレーターではなく USB 接続の実機 Android を使用する方式に変更。
> `docker-compose up capture` ではなく `capture/run.sh` で直接実行する。

- [x] `docker-compose up capture` でエミュレーターが自動起動する
  - ※ USB 接続の実機方式では `docker compose up -d capture` で OCR コンテナが起動する
- [ ] ログイン → ロケット画面遷移が自動で完了する（未実装）
- [x] 1ラウンド完了ごとに倍率が `rounds` テーブルに記録される
- [x] OCR 精度 95% 以上（20回テストで 100% 達成、HSV 白テキストマスク方式）
- [x] エミュレーター自動起動/自動復旧（実装方針変更により対象外）
- [ ] `capture.bar_crop` の自動キャリブレーションツールを提供する（未実装）
- [ ] ログが `docs/logs/` に出力される（未実装）

※ 未チェック項目は本PRのスコープ外または未実装であり、issue は未完了。

---

## 未確定事項（実装前に確認が必要）

| 項目 | 確認内容 |
|------|---------|
| アプリパッケージ名 | `adb shell pm list packages` で確認 |
| APK 入手方法 | 実機からバックアップ or `apkeep` / ストア。`capture/app.apk` に配置 |
| 倍率テキスト表示座標 | `capture.bar_crop` を手動調整して確認 |
| ログイン画面の座標 | UI Automator で要素名取得推奨 |
| 接続デバイス識別 | `adb devices` のシリアルを `adb.device` に設定 |

---

## 技術スタック

| 用途 | ライブラリ |
|------|----------|
| スクリーンショット取得 | ADB (`adb exec-out screencap`) |
| 画像処理 | OpenCV (`opencv-python`) |
| OCR | Tesseract + `pytesseract` |
| API 送信 | `httpx` |
| Android 接続 | ADB (`adb exec-out screencap`) |
| UI 操作 | `adb shell input` / UI Automator |
| プロセス管理 | systemd + bash |

---

## 実装優先順

1. `capture/config.yml` の `bar_crop` 手動調整
2. `run.sh` — ADB 接続確認
3. `ocr.py` — スクショ → 数値抽出確認
4. `ocr.py` — API 送信・DB 書き込み確認
5. `docker-compose.yml` — capture 統合
