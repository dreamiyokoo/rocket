# [インフラ] Redis キャッシュ実装

## 概要

`GET /api/v1/analysis` のレスポンスを Redis にキャッシュし、DB への負荷を軽減する。
倍率登録・リセット時にキャッシュを invalidate して最新の分析結果を返す。

## キャッシュ設計

| キー | 内容 | TTL |
| --- | --- | --- |
| `analysis:current` | 分析結果 JSON 全体 | 60 秒 |

## フロー

```
GET /api/v1/analysis
  ├─ Redis に analysis:current が存在する
  │    └─ キャッシュをそのまま返す
  └─ キャッシュなし
       ├─ DB からラウンドデータを取得
       ├─ 分析ロジックを実行
       ├─ 結果を Redis に保存（TTL 60秒）
       └─ 結果を返す

POST /api/v1/rounds
  ├─ DB に保存
  ├─ Redis の analysis:current を DELETE
  └─ 201 を返す

DELETE /api/v1/rounds
  ├─ DB を TRUNCATE
  ├─ Redis の analysis:current を DELETE
  └─ 200 を返す
```

## 受け入れ条件

- [x] キャッシュヒット時に DB クエリが発生しない
- [x] 倍率登録後に `GET /api/v1/analysis` を呼ぶと新しい値が返る
- [x] リセット後に `GET /api/v1/analysis` を呼ぶと `ready: false` が返る
- [x] Redis が落ちた場合も API は正常に動作する（Redis 障害時は DB から直接返す）

## 技術メモ

- ライブラリ: `redis-py`（async 対応）
- Redis が利用不可の場合は例外をキャッチして DB フォールバックする
- キャッシュ値は `json.dumps` でシリアライズして保存する
