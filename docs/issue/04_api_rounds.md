# [API] ラウンド倍率の登録・リセットエンドポイント実装

## 概要

入力者がラウンド倍率を一括登録する API と、全データをリセットする API を実装する。
どちらも JWT 認証が必要。

## エンドポイント

| Method   | Path             | 認証    | 説明              |
|----------|------------------|-------|-----------------|
| `POST`   | `/api/v1/rounds` | JWT必須 | 倍率を一括登録         |
| `GET`    | `/api/v1/rounds` | 不要    | 最新 N 件のラウンド一覧取得 |
| `DELETE` | `/api/v1/rounds` | JWT必須 | 全データリセット        |

## リクエスト / レスポンス例

### `POST /api/v1/rounds`

フロントエンドは改行区切りの入力文字列をパースして配列に変換してから送信する。

**Request**

```json
{ "values": [1.01, 1.5, 20, 2.05, 100] }
```

**Response 201**

```json
{
  "inserted": 5,
  "total": 23,
  "ready": true
}
```

登録後の `total` が 18 件未満のときだけ `ready: false` となり、分析未算出を示す。

### `GET /api/v1/rounds?limit=72`

```json
{
  "rounds": [
    { "id": 1, "multiplier": 1.01, "recorded_at": "2026-05-14T10:00:00Z" }
  ],
  "total": 23
}
```

### `DELETE /api/v1/rounds`

**Response 200**

```json
{ "deleted": 23 }
```

## バリデーション

- `values` は空配列不可
- 各値は `0` より大きい数値のみ受け付ける（負数・0 は `422` を返す）
- `limit` パラメータのデフォルト: 72、最大: 72

## 受け入れ条件

- [x] JWT なしで `POST` / `DELETE` を呼ぶと `401` が返る
- [x] 正常な倍率リストを送ると DB に保存され `201` が返る
- [x] 0 以下の値が含まれると `422` が返る
- [x] `DELETE` 実行後に `GET` を呼ぶと `rounds: []` が返る
- [x] `total` が 18 件未満のとき `ready: false` になる

## 技術メモ

- 登録後は Redis のキャッシュを invalidate して分析結果を再計算させる
- `DELETE` は `TRUNCATE rounds` で実装してよい
