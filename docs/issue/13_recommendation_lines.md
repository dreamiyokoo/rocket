# [ロジック+API+フロントエンド] 推奨ライン計算（下限・利確）

## 概要

直近の分布・ボラティリティから「下限ライン（損失最小化）」と「利確ライン（利益最大化）」の2本を自動算出し、分析 API に追加・UI に表示する。

## 計算仕様

### ボラティリティ regime 判定

ボラティリティは変動係数（CV）で定義する。

```
volatility_cv = 標準偏差 / 平均   （直近 N 件）
```

| 状態 | CV 範囲 | ラベル |
|------|---------|--------|
| 低ボラ | CV < 0.3 | `low` |
| 中ボラ | 0.3 ≦ CV < 0.8 | `medium` |
| 高ボラ | 0.8 ≦ CV | `high` |

### 下限ライン（損失最小化）

低倍率連続時に "最低限ここで引く" 目安のライン。

```
floor_line = median(直近 N 件) - α × std_dev(直近 N 件)
```

- N = 18（既存 WINDOW 定数に合わせる）
- α: regime に応じて変化

| regime | α |
|--------|---|
| 低ボラ | 0.5 |
| 中ボラ | 0.75 |
| 高ボラ | 1.0 |

結果は 1.01 以上にクリップする（倍率の最小値）。

### 利確ライン（利益最大化）

"波が来た時に逃す" 目安のライン。

```
target_line = mean(直近 N 件) + β × std_dev(直近 N 件)
```

- N = 18
- β: regime に応じて変化

| regime | β |
|--------|---|
| 低ボラ | 1.0 |
| 中ボラ | 1.5 |
| 高ボラ | 2.0 |

## API 仕様

`GET /api/v1/analysis` のレスポンスに `recommendation` フィールドを追加する。

```json
{
  "recommendation": {
    "volatility_cv": 0.62,
    "regime": "medium",
    "floor_line": 1.32,
    "target_line": 3.41
  }
}
```

`ready: false` の場合は `recommendation` を含まない。

## UI 仕様

- 分析ページ（`/`）の統計値カードセクションに `recommendation` パネルを追加する
- 表示項目:
  - ボラティリティ状態（低・中・高）をバッジで色分け表示
  - 下限ライン: `1.32x`
  - 利確ライン: `3.41x`

## 受け入れ条件

- [x] `volatility_cv` と `regime` が正しく算出される
- [x] `floor_line` が regime に応じた α で計算され、1.01 以上にクリップされる
- [x] `target_line` が regime に応じた β で計算される
- [x] `ready: false` の場合 `recommendation` フィールドが含まれない
- [x] 分析ページに下限ライン・利確ライン・regime バッジが表示される
- [x] 単体テストが存在する

## 技術メモ

- 計算ロジックは `api/analysis/calculator.py` に `_recommendation()` として追加する
- `AnalysisResult` に `recommendation` フィールド（dataclass）を追加する
- α・β のテーブルは定数として定義してテストしやすくする
