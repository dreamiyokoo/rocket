# ML バランス改善 進捗メモ

## 目的
青・緑・黄・赤をバランスよく当てる（特定色偏重を抑える）。

## 実装済み（2026-05-27）
- `scripts/ml_walkforward_eval.py`
  - 指標を拡張: `balanced_acc_4class`, `macro_f1_4class`
  - 各色の `precision_*`, `recall_*`, `f1_*` を出力
  - ヘッダー付き/なし CSV の両方を読み込み可能に修正
- `scripts/ml_optimize_accuracy.py`
  - 候補選定を Accuracy 優先から、`(balanced_acc + macro_f1)/2` 優先に変更
  - テスト出力に `balanced_accuracy`, `macro_f1` を追加
  - ヘッダー付き/なし CSV の両対応
- 高倍率向け特徴量を追加（学習・推論・評価で統一）
  - 追加: `p90`, `p95`, `max5`, `gap_since_10x`
  - 反映先: `api/ml/features.py`, `scripts/ml_model.py`, `scripts/ml_walkforward_eval.py`, `scripts/ml_optimize_accuracy.py`
- 色別しきい値判定を追加
  - `scripts/ml_model.py`: One-vs-Rest F1 で色別しきい値を探索し `thresholds.json` に保存
  - `api/ml/predictor.py`: `band_thresholds` を読み込み、しきい値補正済みの帯判定 `decide_band()` を追加
  - `api/routers/rounds.py`: 予測帯の決定を `decide_band()` へ変更

## 初期確認（抜粋）
- Walk-forward（fold=1, test_ratio=0.05）で、新指標が出力されることを確認。
- 追加指標により、Yellow/Red の recall が 0 の状態を可視化できるようになった。

## 次アクション
- 色別しきい値の探索をウォークフォワード前提に拡張
- High帯（Yellow/Red）の recall 下限を満たす制約付きでハイパーパラメータ探索
- 直近データで再学習し、本番モデルへ反映後に実運用評価を再開
