"""
時系列ウォークフォワード評価スクリプト。
直近ドリフト下でも精度が維持できるかを確認する。

使い方:
  python3 scripts/ml_walkforward_eval.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import accuracy_score, roc_auc_score, f1_score

WINDOW = 30
RECENCY_HALF_LIFE = 1200
FEATURE_COLS = [
    'mean', 'median', 'std', 'max', 'min', 'cv',
    'prob_2x', 'prob_5x', 'prob_10x', 'low_streak',
    'slope', 'log_mean', 'log_std', 'momentum',
]
BINARY_EXTRA_FEATURE_COLS = [
    'prob_12', 'prob_15', 'prob_20',
    'min5', 'mean5', 'mean10', 'std5', 'very_low_streak',
]
BINARY_FEATURE_COLS = FEATURE_COLS + BINARY_EXTRA_FEATURE_COLS


def recency_weight(n: int, half_life: int = RECENCY_HALF_LIFE) -> np.ndarray:
    idx = np.arange(n)
    age = (n - 1) - idx
    return np.power(0.5, age / half_life)


def make_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    rows = []
    for i in range(window, len(df)):
        w = df['multiplier'].iloc[i - window:i].values
        rows.append({
            'mean': np.mean(w),
            'median': np.median(w),
            'std': np.std(w),
            'max': np.max(w),
            'min': np.min(w),
            'cv': np.std(w) / (np.mean(w) + 1e-6),
            'prob_2x': np.mean(w >= 2.0),
            'prob_5x': np.mean(w >= 5.0),
            'prob_10x': np.mean(w >= 10.0),
            'low_streak': sum(1 for x in reversed(w) if x < 1.5),
            'slope': np.polyfit(np.arange(window), np.log(np.maximum(w, 0.01)), 1)[0],
            'log_mean': np.mean(np.log(np.maximum(w, 0.01))),
            'log_std': np.std(np.log(np.maximum(w, 0.01))),
            'momentum': np.mean(w[-5:]) - np.mean(w[:5]),
            'prob_12': np.mean(w <= 1.2),
            'prob_15': np.mean(w <= 1.5),
            'prob_20': np.mean(w <= 2.0),
            'min5': np.min(w[-5:]),
            'mean5': np.mean(w[-5:]),
            'mean10': np.mean(w[-10:]),
            'std5': np.std(w[-5:]),
            'very_low_streak': sum(1 for x in reversed(w) if x <= 1.2),
            'target': df['multiplier'].iloc[i],
        })
    return pd.DataFrame(rows)


def label_regime(x: float) -> int:
    if x <= 2.0:
        return 0
    if x <= 5.0:
        return 1
    if x <= 10.0:
        return 2
    return 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', default='docs/rounds_export_ml.csv')
    parser.add_argument('--folds', type=int, default=4)
    parser.add_argument('--test-ratio', type=float, default=0.1)
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), '..', csv_path)

    df = pd.read_csv(csv_path, names=['id', 'multiplier', 'recorded_at'], parse_dates=['recorded_at'])
    df = df.sort_values('recorded_at').reset_index(drop=True)
    feat_df = make_features(df)

    X_multi = feat_df[FEATURE_COLS].reset_index(drop=True)
    X_bin = feat_df[BINARY_FEATURE_COLS].reset_index(drop=True)
    y_multi = feat_df['target'].apply(label_regime).reset_index(drop=True)
    y_bin = (feat_df['target'] <= 2.0).astype(int).reset_index(drop=True)

    n = len(X_multi)
    test_size = int(n * args.test_ratio)
    if test_size <= 0:
        raise ValueError('test-ratio が小さすぎます')

    start = n - (args.folds * test_size)
    if start < int(n * 0.5):
        start = int(n * 0.5)

    print('===== Walk-forward evaluation =====')
    print(f'samples={n}, folds={args.folds}, test_size={test_size}')

    rows = []
    for f in range(args.folds):
        test_start = start + f * test_size
        test_end = min(test_start + test_size, n)
        if test_end - test_start < max(100, test_size // 2):
            continue

        X_train_m = X_multi.iloc[:test_start]
        X_train_b = X_bin.iloc[:test_start]
        y_train_m = y_multi.iloc[:test_start]
        y_train_b = y_bin.iloc[:test_start]

        X_test_m = X_multi.iloc[test_start:test_end]
        X_test_b = X_bin.iloc[test_start:test_end]
        y_test_m = y_multi.iloc[test_start:test_end]
        y_test_b = y_bin.iloc[test_start:test_end]

        w = recency_weight(len(X_train_m))

        mc = lgb.LGBMClassifier(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=6,
            num_leaves=31,
            min_child_samples=30,
            class_weight=None,
            random_state=42,
            verbose=-1,
        )
        mc.fit(X_train_m, y_train_m, sample_weight=w)
        pred_m = mc.predict(X_test_m)
        acc = accuracy_score(y_test_m, pred_m)

        bi = lgb.LGBMClassifier(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=5,
            num_leaves=31,
            min_child_samples=20,
            scale_pos_weight=(y_train_b == 0).sum() / max((y_train_b == 1).sum(), 1),
            random_state=42,
            verbose=-1,
        )
        bi.fit(X_train_b, y_train_b)
        proba_b = bi.predict_proba(X_test_b)[:, 1]
        auc = roc_auc_score(y_test_b, proba_b)

        rows.append({
            'fold': f + 1,
            'train_end': test_start,
            'test_size': len(X_test_m),
            'acc_4class': acc,
            'auc_blue': auc,
            'f1_blue': f1_score(y_test_m, pred_m, labels=[0], average='macro', zero_division=0),
            'f1_green': f1_score(y_test_m, pred_m, labels=[1], average='macro', zero_division=0),
            'f1_yellow': f1_score(y_test_m, pred_m, labels=[2], average='macro', zero_division=0),
            'f1_red': f1_score(y_test_m, pred_m, labels=[3], average='macro', zero_division=0),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        print('有効なfoldが生成できませんでした。')
        return

    print('\n-- Fold metrics --')
    print(out.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

    print('\n-- Summary --')
    print(out[['acc_4class', 'auc_blue', 'f1_blue', 'f1_green', 'f1_yellow', 'f1_red']].agg(['mean', 'min', 'max']).to_string(float_format=lambda x: f'{x:.4f}'))


if __name__ == '__main__':
    main()
