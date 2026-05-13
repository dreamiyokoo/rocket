# [API] 認証エンドポイント実装（JWT）

## 概要

入力者（1名固定）が ID / PW でログインし、JWT を取得する認証機能を実装する。
閲覧者は認証不要。入力・リセット系エンドポイントのみ JWT 検証を行う。

## エンドポイント

| Method | Path | 認証 | 説明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/login` | 不要 | ID / PW でログイン、JWT 発行 |
| `POST` | `/api/v1/auth/logout` | JWT | ログアウト（クライアント側でトークン破棄） |
| `GET` | `/api/v1/auth/me` | JWT | ログイン中ユーザー情報取得 |

## リクエスト / レスポンス例

### `POST /api/v1/auth/login`

```json
// Request
{ "username": "admin", "password": "xxxx" }

// Response 200
{ "access_token": "<jwt>", "token_type": "bearer" }

// Response 401
{ "detail": "Invalid credentials" }
```

### `GET /api/v1/auth/me`

```json
// Response 200
{ "id": 1, "username": "admin" }
```

## 受け入れ条件

- [x] 正しい ID / PW でログインすると JWT が返る
- [x] 誤った認証情報では `401` が返る
- [x] JWT の有効期限は設定可能（デフォルト 24 時間）
- [x] `POST /api/v1/rounds` を JWT なしで呼ぶと `401` が返る
- [x] `GET /api/v1/analysis` は JWT なしで `200` が返る
- [x] JWT の秘密鍵は環境変数 `JWT_SECRET` で管理する

## 技術メモ

- ライブラリ: `python-jose` + `passlib[bcrypt]`
- FastAPI の `Depends` で認証ミドルウェアを共通化する
- リフレッシュトークンは初期実装では不要（アクセストークンのみ）
