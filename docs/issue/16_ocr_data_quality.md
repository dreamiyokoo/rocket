# [OCR・データ品質] OCR精度改善・DBクリーニング・MLモデル再学習

## 概要

OCRによる重複データ挿入バグを修正し、DBデータをクリーニングした上でMLモデルを再学習する。
あわせて501.00（最大倍率）が取得できない問題を修正する。

---

## 問題1: OCR重複挿入バグ

### 原因
`values_asc.index(prev_latest)` が**最初に見つかった位置**（一番古い同値）を基準にするため、
後続の同値（1.01等）が全部「新しい」と誤判定され大量挿入された。

### 修正内容（`capture/ocr.py`）
`last_values`の末尾k件と`values_asc`の先頭k件が一致する最大kを探す**オーバーラップ検索方式**に変更。

```python
# 前回リスト末尾 k 件と今回リスト先頭 k 件が一致する最大 k を探す
max_check = min(len(last_values), len(values_asc))
best_overlap = 0
for k in range(max_check, 0, -1):
    if last_values[-k:] == values_asc[:k]:
        best_overlap = k
        break
new_values = [values_asc[-1]] if best_overlap == 0 else values_asc[best_overlap:]
```

---

## 問題2: 501.00が取得できない

### 原因
`bar_crop` の `x_start=240` が狭すぎ、501.00のような長いテキストが最左ピルに来た時に
先頭の「5」「0」が切れて `01.00 → 1.00` として誤読 → 範囲チェック除外。

### 修正内容
- `config.yml`: `bar_crop: [695, 755, 240, 820]` → `[695, 755, 150, 820]`（x_startを90px拡張）
- `ocr.py`: 正規表現を `\d+\.\d+` → `\d+\.\d+|\b\d{3,}\b` に変更（整数3桁以上もキャプチャ）

---

## DBクリーニング手順

### 実施内容（2026-05-20）
1. クリーニング前CSV保存: `docs/rounds_export_ml.csv`（16,687件）
2. 同値・10秒以内の重複を削除（46件）
3. クリーン済みDB: **16,645件**

```sql
DELETE FROM rounds WHERE id IN (
  SELECT id FROM (
    SELECT id, multiplier, recorded_at,
      LAG(multiplier) OVER w AS prev_mult,
      EXTRACT(EPOCH FROM recorded_at - LAG(recorded_at) OVER w) AS diff_sec
    FROM rounds
    WINDOW w AS (ORDER BY recorded_at)
  ) t
  WHERE diff_sec < 10 AND multiplier = prev_mult
);
```

---

## MLモデル再学習手順

```bash
# 1. DBからCSVエクスポート
docker compose exec db psql -U rocket -d rocket -t -A -F',' -c \
  "SELECT id, multiplier, recorded_at FROM rounds ORDER BY recorded_at" \
  > docs/rounds_export_ml.csv

# 2. MLモデル再学習
/tmp/ml_venv/bin/python scripts/ml_model.py --csv docs/rounds_export_ml.csv

# 3. APIコンテナ再起動
docker compose restart api
```

### 再学習結果（2026-05-20, 16,647件）
| モデル | 指標 | 値 |
|---|---|---|
| 4クラス分類 | accuracy | 34% |
| 2値分類 | AUC | 0.4953 |
| Blue Recall 90% しきい値 | threshold | 0.387 |

> データ蓄積後（10万件超）に再学習すると精度改善が見込まれる。

---

## 受け入れ条件

- [x] OCR重複挿入バグ修正（オーバーラップ検索方式）
- [x] 501.00が取得できない問題修正（x_start拡張 + 整数正規表現追加）
- [x] DBクリーニング実施（重複46件削除）
- [x] クリーン済みデータでMLモデル再学習
- [x] APIコンテナ再起動で新モデル反映確認
- [ ] データ追加後の再検証（次フェーズ）

---

## 次フェーズ: DB初期化と再スタート

データの不正確さが一定数残る可能性があるため、OCR修正後のクリーンな状態から収集し直すことを検討。

### 手順（予定）
1. 現在のDBデータをCSVバックアップ
2. `DELETE FROM rounds;` または `TRUNCATE rounds;`
3. OCR再起動（修正済みキャプチャコードで収集再開）
4. 十分なデータが溜まったら ML 再学習（目安: 5,000件〜）
