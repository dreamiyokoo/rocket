# capture — セットアップガイド

エミュレーターの初期構築から `docker-compose up capture` で OCR が動くまでの手順です。

---

## 前提条件

| ツール | 用途 | インストール方法 |
|--------|------|----------------|
| Android Studio **または** cmdline-tools | エミュレーター + ADB | 下記参照 |
| Docker / Docker Compose | capture コンテナ（任意） | 公式手順 |
| Java 17+ | エミュレーター実行に必要 | `sudo apt install openjdk-17-jdk` |

### Android Studio をインストールする場合（GUI あり・推奨）

画面を見ながら作業できるので初回セットアップが楽です。

1. https://developer.android.com/studio からダウンロード
2. 解凍してインストーラーを実行：
   ```bash
   tar -xzf android-studio-*.tar.gz -C ~/
   ~/android-studio/bin/studio.sh
   ```
3. 初回起動ウィザードで SDK をダウンロード（`~/Android/Sdk` に配置される）
4. **Tools → Device Manager** から AVD（仮想端末）を作成できます

### cmdline-tools のみインストールする場合（GUI 不要・軽量）

Android Studio をインストールせず、コマンドラインツールだけ入れる方法です。

```bash
# cmdline-tools をダウンロード
# 最新版 URL は https://developer.android.com/studio#command-tools で確認
wget https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools-linux-*.zip -d ~/android-sdk
mkdir -p ~/android-sdk/cmdline-tools/latest
mv ~/android-sdk/cmdline-tools/* ~/android-sdk/cmdline-tools/latest/ 2>/dev/null || true

# PATH 設定
echo 'export ANDROID_HOME="$HOME/android-sdk"' >> ~/.bashrc
echo 'export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools"' >> ~/.bashrc
source ~/.bashrc

# ライセンス同意 + システムイメージ + エミュレーターをインストール
sdkmanager --licenses
sdkmanager "platform-tools" "emulator" "system-images;android-33;google_apis;x86_64"

# AVD 作成
avdmanager create avd \
  -n RocketDevice \
  -k "system-images;android-33;google_apis;x86_64" \
  -d "pixel_6"
```

インストール後、`~/.bashrc` (または `~/.zshrc`) に SDK パスを追加します（Android Studio の場合は `~/Android/Sdk`、cmdline-tools の場合は `~/android-sdk`）：

```bash
adb --version      # 動作確認
emulator -version  # 動作確認
```

---

## 1. AVD (Android Virtual Device) の作成

### Android Studio GUI で作る（推奨）

1. Android Studio を起動
2. メニュー → **Tools → Device Manager**
3. **Create Virtual Device** をクリック
4. 端末: **Pixel 6**（画面サイズが安定していておすすめ）
5. システムイメージ: **API 33 (Android 13, x86_64)** をダウンロードして選択
6. AVD 名を `RocketDevice` に設定
7. **Finish**

### cmdline-tools で作る場合

`前提条件` の cmdline-tools インストール手順を完了させた後：

```bash
# AVD が作成済みか確認
avdmanager list avd
# RocketDevice が表示されれば OK
```

---

## 2. エミュレーターの起動

```bash
# GUI ウィンドウ付き（通常はこちら）
emulator -avd RocketDevice &

# 最初の起動は2〜3分かかります
# 「Android」ロゴが消えてホーム画面が出たら完了
```

起動確認：

```bash
adb devices
# 出力例:
# List of devices attached
# emulator-5554   device
```

---

## 3. APK のインストール

ゲームアプリの APK を `capture/app.apk` として用意してから実行します。

### APK の入手方法

**方法 A: 実機を持っている場合**

```bash
# 実機を USB 接続してパッケージ名を確認
adb -s <実機のシリアル> shell pm list packages | grep rocket

# APK パスを取得してコピー
adb -s <実機のシリアル> shell pm path com.example.rocket
# 出力例: package:/data/app/~~xxxx/com.example.rocket-xxxx/base.apk

adb -s <実機のシリアル> pull /data/app/~~xxxx/com.example.rocket-xxxx/base.apk ./capture/app.apk
```

**方法 B: APK ファイルを持っている場合**

```bash
cp /path/to/rocket.apk ./capture/app.apk
```

### エミュレーターにインストール

```bash
# エミュレーターが起動していることを確認してから
adb install -r ./capture/app.apk

# 成功すると "Success" と表示される
```

パッケージ名の確認：

```bash
adb shell pm list packages | grep rocket
# 出力例: package:com.example.rocket
```

確認したパッケージ名を `.env` と `capture/config.yml` に設定します。

---

## 4. 手動ログインとゲーム画面への遷移

初回は手動で操作し、**座標を確認**します。  
エミュレーターのウィンドウを見ながら操作してください。

### アプリを起動する

```bash
adb shell am start -n com.example.rocket/.MainActivity
```

### ログイン座標を調べる

Android Studio の **Layout Inspector** または `calibrate.py` で座標を確認します。

**adb で UI 要素の座標を取得する方法：**

```bash
# UI ダンプを取得して座標を確認
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml /tmp/ui.xml
grep -i "edit\|button\|login" /tmp/ui.xml | head -20
# bounds="[左, 上][右, 下]" の中心座標を使う
```

### 座標を設定する

`run.sh` のログイン関数内の tap 座標を実際の値に書き換えます：

```bash
# run.sh の login() 内
adb shell input tap <ID_FIELD_X> <ID_FIELD_Y>   # ID 入力欄
adb shell input tap <PW_FIELD_X> <PW_FIELD_Y>   # パスワード入力欄
adb shell input tap <LOGIN_BTN_X> <LOGIN_BTN_Y>  # ログインボタン
adb shell input tap <GAME_ICON_X> <GAME_ICON_Y>  # ロケットゲームアイコン
```

---

## 5. OCR クロップ座標のキャリブレーション

ロケット画面を表示した状態で `calibrate.py` を実行します。  
（コンテナ外、ホストのターミナルで実行してください）

```bash
cd /path/to/rocket
pip install opencv-python pytesseract pyyaml pillow
python capture/calibrate.py
```

1. 現在のスクリーンショットが表示される
2. **倍率テキスト（例: `2.45x`）が表示されているエリアをドラッグ**で囲む
3. Enter または Space で確定 → `capture/config.yml` に自動保存
4. OCR プレビューで正しく数値が読めているか確認

---

## 6. .env の設定

プロジェクトルートに `.env` を作成します：

```bash
cat > .env << 'EOF'
# Android
AVD_NAME=RocketDevice
APP_PACKAGE=com.example.rocket
APP_ACTIVITY=.MainActivity
APP_ID=your_game_id
APP_PASSWORD=your_game_password
APK_FILE=./capture/app.apk

# エミュレーターモード: host（ホストで起動済み）/ headless（コンテナ内起動）
EMULATOR_MODE=host

# API 認証トークン（以下のコマンドで取得）
# curl -s -X POST http://localhost:8001/api/v1/auth/token \
#   -d "username=admin&password=changeme" | jq -r .access_token
CAPTURE_API_TOKEN=

# その他
CLOUDFLARE_TUNNEL_TOKEN=
EOF
```

API トークンの取得：

```bash
# API が起動している状態で実行
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/token \
  -d "username=admin&password=changeme" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "CAPTURE_API_TOKEN=$TOKEN" >> .env
```

---

## 7. capture コンテナの起動

```bash
# 1. エミュレーターがホストで起動済みであることを確認
adb devices  # emulator-5554 device が表示されること

# 2. ゲーム画面を表示した状態にする（手動でアプリ起動・ログイン・画面遷移）

# 3. capture コンテナをビルド・起動
docker-compose build capture
docker-compose up capture

# ログ確認
docker-compose logs -f capture
# [INFO] OCR ループ開始 (interval=1.0s)
# [INFO] ラウンド開始: 1.05x
# [INFO] クラッシュ検出: peak=3.21x → 送信
# [INFO] 送信成功: 3.21x
```

---

---

## ホスト直接インストール（Docker 不要）

コンテナを使わずホスト上で Python スクリプトを直接動かす方法です。

### 依存パッケージのインストール

```bash
# Tesseract OCR 本体
sudo apt install -y tesseract-ocr tesseract-ocr-eng android-tools-adb

# Python ライブラリ（venv 推奨）
cd /path/to/rocket
python3 -m venv capture/.venv
source capture/.venv/bin/activate
pip install -r capture/requirements.txt

# opencv-python-headless だと calibrate.py の GUI が使えないので
# ホストで使う場合はフル版に置き換える
pip install opencv-python
```

### API トークンの取得と設定

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/token \
  -d "username=admin&password=changeme" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
export CAPTURE_API_TOKEN="$TOKEN"
```

### OCR ループの起動

```bash
source capture/.venv/bin/activate
export CAPTURE_API_TOKEN="..."
export APP_ID="your_game_id"
export APP_PASSWORD="your_game_password"

# エミュレーターが起動済みの状態で
python capture/ocr.py
```

### systemd サービスとして自動起動（オプション）

```ini
# /etc/systemd/system/rocket-capture.service
[Unit]
Description=Rocket Game Auto Capture
After=network.target

[Service]
User=%i
WorkingDirectory=/path/to/rocket
EnvironmentFile=/path/to/rocket/.env
ExecStart=/path/to/rocket/capture/.venv/bin/python capture/ocr.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rocket-capture
sudo systemctl status rocket-capture
journalctl -fu rocket-capture   # ログ確認
```

---

## トラブルシューティング

### ADB が接続できない

```bash
# ADB サーバーを再起動
adb kill-server
adb start-server
adb devices
```

### OCR が数値を読めない

```bash
# calibrate.py を再実行してクロップ範囲を調整
python capture/calibrate.py

# Tesseract が正しくインストールされているか確認
tesseract --version
```

### エミュレーターが重い

```bash
# HAXM または KVM が有効になっているか確認
kvm-ok        # Linux
# 出力: "KVM acceleration can be used"

# emulator 起動時にオプション追加
emulator -avd RocketDevice -accel on &
```
