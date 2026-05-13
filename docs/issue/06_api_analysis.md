# [API] 分析結果エンドポイント実装

## 概要

閲覧者向けの分析結果取得 API を実装する。認証不要（パブリック）。
Redis キャッシュを使い、倍率登録・リセット時に自動で再計算する。

## エンドポイント

| Method | Path | 認証 | 説明 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/analysis` | 不要 | 現在の分析結果を返す |

## レスポンス例

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

データが 18 件未満の場合:

```json
{
  "ready": false,
  "total_rounds": 10,
  "window": 18
}
```

## `chart_data` の仕様

- 最大 72 件（直近 72 件）
- `index` はラウンド番号（1 始まり）
- 件数が 72 を超えた場合は直近 72 件のみ返す（蓄積データ自体は保持）

## 受け入れ条件

- [ ] JWT なしで `200` が返る
- [ ] `ready: false` のとき統計値・グラフデータは含まれない
- [ ] `chart_data` が最大 72 件で返る
- [ ] Redis キャッシュが有効なとき DB クエリが発生しない
- [ ] 倍率登録・リセット後にキャッシュが invalidate されて新値が返る

## 技術メモ

- Redis キャッシュキー: `analysis:current`（TTL: 60 秒）
- 倍率登録 / リセット時に `DELETE analysis:current` を実行してキャッシュクリアする
- `analyzed_at` は分析実行時刻（キャッシュヒット時も実際の計算時刻を返す）
