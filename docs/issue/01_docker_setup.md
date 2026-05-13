# [インフラ] Docker / docker-compose 環境構築

## 概要

開発・本番共通のコンテナ基盤を整備する。
`docker compose up` 一発でローカル開発環境が起動できる状態を目標とする。

## コンテナ構成

| Service | Image / Role |
| --- | --- |
| `frontend` | Next.js ダッシュボード |
| `api` | FastAPI REST API |
| `worker` | 分析計算・通知処理 |
| `db` | PostgreSQL |
| `redis` | キャッシュ / pub-sub |
| `cloudflared` | Cloudflare Tunnel 接続 |

## 受け入れ条件

- [ ] `docker compose up` で全サービスが起動する
- [ ] `api` コンテナから `db`・`redis` コンテナに接続できる
- [ ] `frontend` コンテナから `api` コンテナに接続できる
- [ ] `.env.example` に必要な環境変数がすべて記載されている
- [ ] 各サービスに個別 `Dockerfile` が存在する
- [ ] `GET /api/v1/health` が `200 OK` を返す

## 技術メモ

- 環境変数は `.env` / `.env.example` で管理（`.env` は `.gitignore` 対象）
- 全サービスは同一 compose ネットワーク内で名前解決する
- DB の初期化は `db/init.sql` または Alembic マイグレーションで行う
