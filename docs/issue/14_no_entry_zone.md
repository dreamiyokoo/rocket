# [ロジック+API+フロントエンド] 買い禁止ゾーン（No-Entry Zone）判定

## 概要

直近データから「今は買うべきでない」状態を3条件でロジック判定し、分析 API に追加・UI にカラーインジケーターとして表示する。

## 判定条件

以下のいずれかを満たすと `no_entry: true` とする。

### ① 低倍率連続（吸い込み帯）

```
低倍率連続数 = 直近連続して 1.30x 以下が続いている件数
NoEntry_1 = (低倍率連続数 >= L)
```

- L = 5（デフォルト。設定可能）
- 直近の連続件数なので、最新値から遡り 1.30 を超えた時点でカウント停止

### ② 高倍率直後の急収束（吐き戻し調整帯）

```
NoEntry_2 = (直近1件が >= 10.0) AND (直近2〜4件の平均 < 1.3)
```

- 「10倍以上」→「1倍台が続く」パターンを検出
- 直近4件未満の場合は条件2をスキップ

### ③ 低ボラ期（跳ねる気配ゼロ）

```
volatility_cv = 標準偏差 / 平均   （直近 WINDOW=18 件）
NoEntry_3 = (volatility_cv < 0.25)
```

## API 仕様

`GET /api/v1/analysis` のレスポンスに `no_entry` フィールドを追加する。

```json
{
  "no_entry": {
    "active": true,
    "reasons": ["low_consecutive", "low_volatility"],
    "low_consecutive_count": 6,
    "volatility_cv": 0.18
  }
}
```

| フィールド | 説明 |
|-----------|------|
| `active` | 3条件いずれかが true のとき `true` |
| `reasons` | 該当した条件のリスト（`low_consecutive` / `post_spike` / `low_volatility`） |
| `low_consecutive_count` | 直近の連続低倍率件数 |
| `volatility_cv` | 変動係数（#13 の値と共有） |

`ready: false` の場合は `no_entry` を含まない。

## UI 仕様

- 分析ページ（`/`）のステータスバーに No-Entry インジケーターを追加する
- 表示ロジック:

| 状態 | 表示 | 色 |
|------|------|----|
| `no_entry.active = false` | エントリー可 | 緑 |
| `no_entry.active = true`、1条件 | 注意 | 黄 |
| `no_entry.active = true`、2条件以上 | 買い禁止 | 赤 |

- 該当した条件名を小さく表示する（例: `低倍率連続: 6回`）

## 受け入れ条件

- [ ] 条件① 低倍率連続が L 件以上で `no_entry.active = true` になる
- [ ] 条件② 高倍率直後の急収束が検出される
- [ ] 条件③ CV < 0.25 で `no_entry.active = true` になる
- [ ] 複数条件が `reasons` にすべて列挙される
- [ ] `ready: false` の場合 `no_entry` フィールドが含まれない
- [ ] 分析ページにカラーインジケーターと条件説明が表示される
- [ ] 単体テストが存在する（各条件の境界値を含む）

## 技術メモ

- `_no_entry()` を `api/analysis/calculator.py` に追加する
- `AnalysisResult` に `no_entry` フィールドを追加する
- 低倍率連続閾値 `L` と低ボラ閾値は定数として定義する
- #13（推奨ライン）の `volatility_cv` と同じ計算を再利用する
