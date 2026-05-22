# CRASH ROCKET ML 実装ガイド

## 概要

CRASH ROCKETの倍率データを使ったMLモデルの実装ガイド。
別PCでの環境構築から学習・評価までを記載する。

---

## データ

### エクスポートファイル

`docs/rounds_export_ml.csv`

| カラム | 型 | 説明 |
|-------|-----|------|
| id | int | ラウンドID |
| multiplier | float | 爆発倍率（0.01〜500程度） |
| recorded_at | ISO8601 | 記録日時（UTC） |

### データ概要（2026-05-15〜16 時点）

| 項目 | 値 |
|------|-----|
| 件数 | 2,826件 |
| 期間 | 2026-05-15 08:02 UTC 〜 |
| 平均倍率 | 5.02x |
| 中央値 | 1.94x |
| 最大 | 186.04x |
| 1ラウンド平均時間 | 約35秒 |

### ラベル分布

| クラス | 範囲 | 件数 | 割合 |
|-------|------|------|------|
| Low | < 1.5x | 約42% | クラッシュ系 |
| Mid | 1.5〜10x | 約50% | 通常 |
| High | ≥ 10x | 約8% | 高倍率 |

---

## 環境構築（別PC）

```bash
# Python 3.11以上推奨
python3 -m venv venv
source venv/bin/activate

pip install pandas numpy scikit-learn lightgbm matplotlib seaborn jupyter
```

---

## 特徴量設計

直近 N 件（推奨 N=20）のウィンドウから以下を計算する。

```python
import pandas as pd
import numpy as np

df = pd.read_csv('docs/rounds_export_ml.csv', parse_dates=['recorded_at'])
df = df.sort_values('recorded_at').reset_index(drop=True)

WINDOW = 30

def make_features(df, window=WINDOW):
    rows = []
    for i in range(window, len(df)):
        w = df['multiplier'].iloc[i-window:i].values
        row = {
            # ウィンドウ統計
            'mean':     np.mean(w),
            'median':   np.median(w),
            'std':      np.std(w),
            'max':      np.max(w),
            'min':      np.min(w),
            'cv':       np.std(w) / (np.mean(w) + 1e-6),  # 変動係数
            # 到達率
            'prob_2x':  np.mean(w >= 2.0),
            'prob_5x':  np.mean(w >= 5.0),
            'prob_10x': np.mean(w >= 10.0),
            # 低倍率連続
            'low_streak': sum(1 for x in reversed(w) if x < 1.5),
            # 傾き（線形回帰の係数）
            'slope':    np.polyfit(np.arange(window), np.log(np.maximum(w, 0.01)), 1)[0],
            # ログ変換後の統計
            'log_mean': np.mean(np.log(np.maximum(w, 0.01))),
            'log_std':  np.std(np.log(np.maximum(w, 0.01))),
            # 直近5件と前半の差（モメンタム）
            'momentum': np.mean(w[-5:]) - np.mean(w[:5]),
            # ターゲット（次のラウンド）
            'target':   df['multiplier'].iloc[i],
        }
        rows.append(row)
    return pd.DataFrame(rows)

feat_df = make_features(df)
```

---

## ① LightGBM 3クラス分類（推奨）

### ラベル定義

```python
def label_regime(x):
    if x < 1.5:   return 0  # Low
    if x < 10.0:  return 1  # Mid
    return 2                 # High

feat_df['label'] = feat_df['target'].apply(label_regime)
```

### 学習

```python
from sklearn.model_selection import train_test_split
import lightgbm as lgb
from sklearn.metrics import classification_report

feature_cols = ['mean','median','std','max','min','cv',
                'prob_2x','prob_5x','prob_10x','low_streak',
                'slope','log_mean','log_std','momentum']

X = feat_df[feature_cols]
y = feat_df['label']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, shuffle=False  # 時系列なのでshuffleしない
)

model = lgb.LGBMClassifier(
    n_estimators=300,
    learning_rate=0.05,
    max_depth=4,
    num_leaves=15,
    class_weight='balanced',  # High クラスの不均衡対策
    random_state=42,
)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
print(classification_report(y_test, y_pred, target_names=['Low','Mid','High']))
```

### 特徴量重要度

```python
import matplotlib.pyplot as plt

feat_imp = pd.Series(model.feature_importances_, index=feature_cols)
feat_imp.sort_values().plot.barh(figsize=(8, 5))
plt.title('Feature Importance')
plt.tight_layout()
plt.show()
```

---

## ② 2値分類「次が1.5以下か？」

```python
feat_df['label_binary'] = (feat_df['target'] < 1.5).astype(int)

X = feat_df[feature_cols]
y = feat_df['label_binary']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

binary_model = lgb.LGBMClassifier(
    n_estimators=300, learning_rate=0.05, max_depth=4,
    scale_pos_weight=(y_train == 0).sum() / (y_train == 1).sum(),
    random_state=42,
)
binary_model.fit(X_train, y_train)

from sklearn.metrics import roc_auc_score
proba = binary_model.predict_proba(X_test)[:, 1]
print(f'AUC: {roc_auc_score(y_test, proba):.4f}')
```

---

## ③ AutoEncoder 異常値検知（高倍率前兆検出）

```python
import torch
import torch.nn as nn

class AutoEncoder(nn.Module):
    def __init__(self, input_dim=14):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 8), nn.ReLU(),
            nn.Linear(8, 4), nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(4, 8), nn.ReLU(),
            nn.Linear(8, input_dim),
        )
    def forward(self, x):
        return self.decoder(self.encoder(x))

# 正常データ（Low/Mid）のみで学習
from sklearn.preprocessing import StandardScaler
normal_mask = feat_df['label'] != 2  # High を除外して学習

scaler = StandardScaler()
X_normal = scaler.fit_transform(feat_df.loc[normal_mask, feature_cols])
X_all    = scaler.transform(feat_df[feature_cols])

# 再構成誤差が大きい = 異常（高倍率前兆の可能性）
# 詳細は実装時に調整
```

---

## 期待される精度と活用方針

| モデル | 精度目安 | 活用方針 |
|-------|---------|---------|
| 3クラス分類 | 60〜75% | High確率 > 30% のときのみエントリー |
| 2値分類（Low予測） | 70〜85% | Low確率 > 60% のときはスキップ |
| AutoEncoder | 定性的 | 再構成誤差 > 閾値のときアラート |

---

## 注意事項

- **時系列データのため `shuffle=False`** でtrain/test分割すること
- 2826件は「動き始めるライン」。**5000件超えると精度が大きく向上**
- High（10x以上）は約8%しかなく不均衡。`class_weight='balanced'` や
  `scale_pos_weight` で対処すること
- 1ラウンド約35秒のため5000件 ≒ 約2日間のデータ収集が必要

---

## データ更新方法

データが増えたら再エクスポートしてPCに転送する：

```bash
# サーバー側（ms02）
docker compose exec api python3 << 'EOF' > docs/rounds_export_ml.csv
import asyncio, asyncpg, os

async def main():
    db = await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://'))
    rows = await db.fetch('SELECT id, multiplier, recorded_at FROM rounds ORDER BY recorded_at ASC')
    await db.close()
    print('id,multiplier,recorded_at')
    for r in rows:
        print(f'{r["id"]},{float(r["multiplier"])},{r["recorded_at"].isoformat()}')

asyncio.run(main())
EOF

# 別PCへ転送（例）
scp yokoo@ms02:~/IdeaProjects/rocket/docs/rounds_export_ml.csv ./
```

---

## 修正履歴

### 2026-05-20: Trailing Streak 計算ロジック復帰

**問題**
- 2026-05-19 の CSV データ更新後、ML 予測がほぼ全て青（Low）に収束する症状が発生
- 推論時に生成される `low_streak`, `very_low_streak` 特徴量が、学習時の期待値と乖離していたことが根本原因

**原因の特定**
- Copilot の自動修正（コミット 5b7b995）により、`low_streak` と `very_low_streak` の計算ロジックが誤って変更されていた
- **修正前（正）**: ウィンドウの末尾から**連続で条件を満たす値をカウント**（trailing streak）
  ```python
  low_streak = 0
  for x in reversed(window):
      if x < 1.5:
          low_streak += 1
      else:
          break  # ← 途中で止める
  ```
- **修正後（誤）**: ウィンドウ**全体で条件を満たす値の個数をカウント**（simple count）
  ```python
  low_streak = sum(1 for x in window if x < 1.5)  # ← 全部カウント
  ```

**修正内容**
- `api/ml/features.py` の `make_binary_feature_vector()` 内の `low_streak`, `very_low_streak` を元の trailing streak ロジックに復帰
- コミット: `8b334ae` (feature/prediction-display-basic-auth)

**学習**
- **ML の train-inference パリティは極めて重要**。特徴量計算の変更は、学習済みモデルをそのまま使う場合、必ず全データで再学習が必要
- ウィンドウ内の時系列的な「最近の傾向」を反映させるには、単純カウントではなく trailing streak（末尾からの連続性）が必要な場合が多い
- 今後の修正時には、特徴量計算の変更があれば必ず精度検証（テストデータでの推論精度確認）を行うこと
