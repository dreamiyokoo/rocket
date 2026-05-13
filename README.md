# rocket

クラッシュゲーム（脱出系）のラウンド倍率データを蓄積し、確率遷移・移動平均によるテクニカル分析を行うダッシュボードの開発仕様です。
README と `docs/issue/` 配下の仕様はすべてこの前提で統一する。

## 概要

- 入力形式: ラウンドごとの倍率値を1行1値で入力（例: 1行目 `1.01`、2行目 `1.5`、…）
- 銘柄の概念はない。1セッション分のラウンド結果を時系列データとして扱う
- 最低 **18件** のデータ投入後に分析を開始する
- データはいつでもリセット可能

## ユーザー権限

| ロール | 権限 |
| --- | --- |
| **入力者**（1名） | ログイン必須。倍率入力・データリセット操作が可能 |
| **閲覧者**（複数） | 認証不要。分析結果・グラフの閲覧のみ可能 |

- 入力画面はログイン済みユーザーのみアクセス可
- 閲覧画面はパブリックに公開する（認証不要）
- 入力者アカウントは固定1名のみ（管理画面等での追加は不要）

## 分析仕様

### 確率遷移（移動平均付き）

以下の3閾値について、直近Nラウンド中に閾値以上となった割合（移動平均）をトラッキングする。

| 指標 | 条件 | 移動平均ウィンドウ |
| --- | --- | --- |
| 2x以上確率 | 倍率 >= 2.0 | 18件 |
| 5x以上確率 | 倍率 >= 5.0 | 18件 |
| 10x以上確率 | 倍率 >= 10.0 | 18件 |

- 移動平均は最新18件を基準ウィンドウとする
- データが18件未満の場合は分析結果を返さない（エラーではなく未算出として扱う）

### 全体グラフ

- 表示件数: 最大 **72件**（18 × 4）
- グラフには倍率の時系列と各確率遷移ラインを重ねて表示する
- 72件を超えた場合は直近72件のみ表示する（蓄積データ自体は保持する）

### その他の分析値（参考）

| 指標 | 内容 |
| --- | --- |
| 移動平均倍率 | 直近18件の倍率平均 |
| 中央値 | 直近18件の中央値 |
| 最大値 / 最小値 | 全蓄積データ中の最大・最小 |
| 標準偏差 | 直近18件のばらつき |
| 連続1x未満カウント | 直近で1.0未満が何連続しているか |

## データリセット

- UI上のリセットボタン、またはAPIエンドポイント経由で全ラウンドデータを削除できる
- リセット後は再び18件蓄積するまで分析結果が表示されない

## 推奨フルスタック構成

### フロントエンド

- **Next.js**
- 用途:
  - **入力画面**（認証済み専用）: 改行区切りの一括入力フォーム + 送信・リセットボタン
  - **閲覧画面**（パブリック）: 全体グラフ・確率遷移パネル・ステータスバー
  - ログイン / ログアウト

### バックエンド

- **FastAPI**
- 用途:
  - ラウンド結果の登録・取得
  - 確率遷移・移動平均の計算
  - データリセット処理

### データストア

- **PostgreSQL**: ラウンド履歴、分析スナップショット
- **Redis**: キャッシュ、リアルタイム更新通知

### インフラ / 開発環境

- **Docker / docker-compose**
- **Cloudflare Tunnel**

## コンテナ構成

| Service | Role |
| --- | --- |
| `frontend` | Next.js ダッシュボード |
| `api` | FastAPI REST API |
| `worker` | 分析計算・通知処理 |
| `db` | PostgreSQL |
| `redis` | キャッシュ / pub-sub |
| `cloudflared` | Cloudflare Tunnel 接続 |

## API 設計

### 認証

- `POST /api/v1/auth/login` — ID / PW でログイン（JWT発行）
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

入力系エンドポイント（`POST /api/v1/rounds`、`DELETE /api/v1/rounds`）はJWT必須。
分析・閲覧系エンドポイントは認証不要（パブリック）。

### ラウンド

- `POST /api/v1/rounds` — 複数件のラウンド倍率を一括登録（要認証）
- `GET /api/v1/rounds` — 蓄積済みラウンド一覧（最新N件、パブリック）
- `DELETE /api/v1/rounds` — 全データリセット（要認証）

#### `POST /api/v1/rounds` リクエスト例

改行区切りで入力された文字列をサーバー側でパースする。

```json
{ "values": [1.01, 1.5, 20, 2.05, 100] }
```

#### `POST /api/v1/rounds` レスポンス例

```json
{
  "inserted": 5,
  "total": 23,
  "ready": true
}
```

登録後の `total` が 18 件未満のときだけ `ready: false` となり、分析未算出を示す。

### 分析

- `GET /api/v1/analysis` — 現在の分析結果を返す

#### `GET /api/v1/analysis` レスポンス例

```json
{
  "ready": true,
  "total_rounds": 23,
  "window": 18,
  "prob_2x":  { "current": 0.44, "history": [0.39, 0.41, 0.44] },
  "prob_5x":  { "current": 0.17, "history": [0.11, 0.14, 0.17] },
  "prob_10x": { "current": 0.06, "history": [0.03, 0.05, 0.06] },
  "moving_avg": 4.82,
  "median": 1.72,
  "std_dev": 12.3,
  "max": 100.0,
  "min": 1.01,
  "chart_data": [
    { "index": 1, "value": 1.01 },
    { "index": 2, "value": 1.5 }
  ],
  "analyzed_at": "2026-05-14T10:00:00Z"
}
```

- `history` は「18件の分析ウィンドウを1件ずつ右にずらして算出した過去値」の配列
- 18件未満では `history` は生成されない
- 18件ちょうどで `history` は 1 件、以降はラウンド追加ごとに 1 件ずつ増える
- `history` の件数は `max(0, min(total_rounds - 17, 72))` を上限とする
- `chart_data` は直近 `min(total_rounds, 72)` 件の倍率時系列を返す

### システム

- `GET /api/v1/health`
- `GET /api/v1/metrics`

## データモデル

```
users
  id            SERIAL PRIMARY KEY
  username      VARCHAR(64) NOT NULL UNIQUE
  password_hash VARCHAR(255) NOT NULL
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()

rounds
  id            SERIAL PRIMARY KEY
  multiplier    NUMERIC(12, 4) NOT NULL
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()

analysis_snapshots
  id            SERIAL PRIMARY KEY
  prob_2x       NUMERIC(6, 4)
  prob_5x       NUMERIC(6, 4)
  prob_10x      NUMERIC(6, 4)
  moving_avg    NUMERIC(12, 4)
  window_size   INTEGER
  snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT now()
```

`users` テーブルには初期データとして入力者1名のみ登録する。

## 画面要件

### ログイン画面（入力者専用）

- ID / PW フォーム
- ログイン成功後、入力画面へ遷移

### 入力画面（認証済み専用）

1. **倍率入力エリア** — テキストエリア（1行1値の改行区切り）+ 送信ボタン
   - 例: 複数行に `1.01` / `1.5` / `20` / `2.05` / `100` を入力して一括送信
2. **リセットボタン** — 確認ダイアログ付き（全データ削除）
3. **ログアウトボタン**

### 閲覧画面（パブリック・認証不要）

1. **ステータスバー** — 蓄積件数 / 分析に必要な残り件数
2. **確率パネル**
   - 2x以上: XX.X%
   - 5x以上: XX.X%
   - 10x以上: XX.X%
3. **全体グラフ** — 最大72件の倍率折れ線 + 各確率遷移ライン（3本）

## 開発開始時の優先順位

1. Docker ベースのローカル起動
2. PostgreSQL スキーマ作成（`users` / `rounds` テーブル）
3. 認証エンドポイント実装（`POST /api/v1/auth/login`、JWT発行）
4. `POST /api/v1/rounds` と `DELETE /api/v1/rounds` の実装（認証ミドルウェア込み）
5. 確率遷移・移動平均の計算ロジック実装
6. `GET /api/v1/analysis` の実装（パブリック）
7. Next.js: ログイン画面 → 入力画面（改行区切りテキストエリア）
8. Next.js: 閲覧画面（グラフ・確率パネル、認証不要）
9. Redis キャッシュで分析結果を高速返却
10. Cloudflare Tunnel で外部確認環境を用意

## 次に追加できるもの

- docker-compose 完全版
- FastAPI コード雛形
- Next.js ダッシュボードテンプレート
- WebSocket によるリアルタイム更新
- Cloudflare Tunnel 設定ファイル例
