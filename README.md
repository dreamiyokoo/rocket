# rocket

実装フェーズにそのまま入れることを前提にした、株価分析ダッシュボードの開発ベース仕様です。
フルスタック構成、Docker、Cloudflare Tunnel、RSI/MACD分析、管理画面、API設計までを1つに整理しています。

## 目的

- 市場データを取り込み、銘柄ごとのテクニカル分析結果を配信する
- RSI / MACD を利用したシグナル判定をAPIと管理画面で確認できるようにする
- ローカル開発から公開検証までを Docker + Cloudflare Tunnel で一貫運用できるようにする

## 推奨フルスタック構成

### フロントエンド

- **Next.js**
- 用途:
  - 管理画面
  - ダッシュボード
  - 銘柄一覧 / 詳細
  - アラート履歴確認

### バックエンド

- **FastAPI**
- 用途:
  - REST API 提供
  - テクニカル分析実行
  - バッチ / ワーカー連携
  - 認証・認可

### データストア

- **PostgreSQL**: 銘柄、価格履歴、シグナル、ユーザー、監視設定
- **Redis**: キャッシュ、ジョブキュー、リアルタイム通知基盤

### インフラ / 開発環境

- **Docker / docker-compose**
- **Cloudflare Tunnel**

## コンテナ構成

最低限のサービス構成は以下を想定します。

| Service | Role |
| --- | --- |
| `frontend` | Next.js 管理画面 |
| `api` | FastAPI REST API |
| `worker` | データ取得・指標計算・通知処理 |
| `db` | PostgreSQL |
| `redis` | キャッシュ / pub-sub / queue |
| `cloudflared` | Cloudflare Tunnel 接続 |

### Docker 運用方針

- 各サービスは個別 Dockerfile で管理
- ローカル開発は `docker compose up` を基本とする
- 環境変数は `.env` / `.env.example` で管理
- API / Frontend / Worker は同一 compose ネットワーク内で接続

## Cloudflare Tunnel 方針

- 外部公開は `cloudflared` コンテナ経由で実施
- 公開先の例:
  - `app.example.com` → `frontend:3000`
  - `api.example.com` → `api:8000`
- 開発時はローカルポート公開と Tunnel の両方を選択可能にする
- 認証が必要な管理画面は Cloudflare Access と併用可能な前提にする

## RSI / MACD 分析仕様

### RSI

- 期間: **14**
- 基本判定:
  - `RSI >= 70`: 買われすぎ
  - `RSI <= 30`: 売られすぎ

### MACD

- 標準設定:
  - 短期EMA: **12**
  - 長期EMA: **26**
  - シグナル: **9**
- 基本判定:
  - MACD がシグナルを上抜け: 買いシグナル候補
  - MACD がシグナルを下抜け: 売りシグナル候補

### シグナル生成ルール

- `buy`:
  - RSI が売られすぎ圏
  - かつ MACD ゴールデンクロス
- `sell`:
  - RSI が買われすぎ圏
  - かつ MACD デッドクロス
- `hold`:
  - 上記以外

## 管理画面要件

### 主要画面

1. **ログイン画面**
2. **ダッシュボード**
   - 監視銘柄数
   - 最新シグナル件数
   - 直近分析実行時刻
3. **銘柄一覧**
   - シンボル
   - 現在価格
   - RSI
   - MACD
   - 判定シグナル
4. **銘柄詳細**
   - 価格推移
   - RSI/MACD 時系列
   - シグナル履歴
5. **アラート管理**
   - 通知先
   - 条件
   - 有効 / 無効
6. **ジョブ・同期状態確認**
   - 最終取得時刻
   - 実行ステータス
   - エラー履歴

## API 設計

### 認証

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### 銘柄

- `GET /api/v1/symbols`
- `POST /api/v1/symbols`
- `GET /api/v1/symbols/{symbol}`
- `PATCH /api/v1/symbols/{symbol}`
- `DELETE /api/v1/symbols/{symbol}`

### 分析結果

- `GET /api/v1/analysis/latest`
- `GET /api/v1/analysis/{symbol}`
- `POST /api/v1/analysis/run`

#### `GET /api/v1/analysis/{symbol}` レスポンス例

```json
{
  "symbol": "AAPL",
  "price": 212.31,
  "rsi": 28.4,
  "macd": {
    "value": -1.24,
    "signal": -1.51,
    "histogram": 0.27
  },
  "signal": "buy",
  "analyzed_at": "2026-05-13T16:00:00Z"
}
```

### アラート

- `GET /api/v1/alerts`
- `POST /api/v1/alerts`
- `PATCH /api/v1/alerts/{alert_id}`
- `DELETE /api/v1/alerts/{alert_id}`

### システム

- `GET /api/v1/health`
- `GET /api/v1/jobs`
- `GET /api/v1/metrics`

## データモデルの最小単位

- `users`
- `symbols`
- `price_candles`
- `technical_indicators`
- `signals`
- `alerts`
- `job_runs`

## 開発開始時の優先順位

1. Docker ベースのローカル起動
2. FastAPI の `/health` / `/symbols` / `/analysis` 実装
3. PostgreSQL スキーマ作成
4. Worker による価格取得 + RSI/MACD 計算
5. Next.js 管理画面の一覧 / 詳細画面作成
6. Redis を使った通知・ジョブ連携
7. Cloudflare Tunnel で外部確認環境を用意

## 次に追加できるもの

- 詳細ER図
- docker-compose完全版
- FastAPI APIコード雛形
- Next.js管理画面テンプレート
- Redisリアルタイム通知実装
- Cloudflare Tunnel設定ファイル例
