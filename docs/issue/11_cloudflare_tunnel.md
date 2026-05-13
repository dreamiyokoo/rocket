# [インフラ] Cloudflare Tunnel 設定

## 概要

外部からアクセスできる検証環境を Cloudflare Tunnel で構築する。
`cloudflared` コンテナ経由でフロントエンドと API を公開する。

## 公開先の設定例

| 公開 URL | 転送先 |
| --- | --- |
| `app.example.com` | `frontend:3000` |
| `api.example.com` | `api:8000` |

## 設定ファイル（`cloudflared/config.yml`）

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/credentials.json

ingress:
  - hostname: app.example.com
    service: http://frontend:3000
  - hostname: api.example.com
    service: http://api:8000
  - service: http_status:404
```

## 受け入れ条件

- [ ] `cloudflared` コンテナが起動し Tunnel に接続される
- [ ] `app.example.com` からフロントエンドにアクセスできる
- [ ] `api.example.com/api/v1/health` が `200 OK` を返す
- [ ] 認証情報（Tunnel トークン）は環境変数 `CLOUDFLARE_TUNNEL_TOKEN` で管理する
- [ ] `.env.example` に `CLOUDFLARE_TUNNEL_TOKEN` が記載されている

## 技術メモ

- Tunnel の作成は `cloudflared tunnel create rocket` で行う
- 認証情報ファイルは `.gitignore` 対象にする
- 開発時はローカルポート直接アクセスと Tunnel の両方を選択可能にする
- 管理画面（`/input`）を Cloudflare Access と組み合わせて保護することも可能
