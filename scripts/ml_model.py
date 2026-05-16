"""
ML モデル構築スクリプト
- LightGBM 3クラス分類 (Low / Mid / High)
- LightGBM 2値分類 (次が Low < 1.5x か？)

使い方:
  python3 scripts/ml_model.py
  python3 scripts/ml_model.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score

WINDOW = 20
FEATURE_COLS = [
    'mean', 'median', 'std', 'max', 'min', 'cv',
    'prob_2x', 'prob_5x', 'prob_10x', 'low_streak',
    'slope', 'log_mean', 'log_std', 'momentum',
]
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'docs', 'ml_models')


def make_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    rows = []
    for i in range(window, len(df)):
        w = df['multiplier'].iloc[i - window:i].values
        row = {
            'mean':       np.mean(w),
            'median':     np.median(w),
            'std':        np.std(w),
            'max':        np.max(w),
            'min':        np.min(w),
            'cv':         np.std(w) / (np.mean(w) + 1e-6),
            'prob_2x':    np.mean(w >= 2.0),
            'prob_5x':    np.mean(w >= 5.0),
            'prob_10x':   np.mean(w >= 10.0),
            'low_streak': sum(1 for x in reversed(w) if x < 1.5),
            'slope':      np.polyfit(np.arange(window), np.log(np.maximum(w, 0.01)), 1)[0],
            'log_mean':   np.mean(np.log(np.maximum(w, 0.01))),
            'log_std':    np.std(np.log(np.maximum(w, 0.01))),
            'momentum':   np.mean(w[-5:]) - np.mean(w[:5]),
            'target':     df['multiplier'].iloc[i],
        }
        rows.append(row)
    return pd.DataFrame(rows)


def label_regime(x: float) -> int:
    if x < 1.5:
        return 0  # Low
    if x < 10.0:
        return 1  # Mid
    return 2      # High


def train_multiclass(feat_df: pd.DataFrame):
    feat_df['label'] = feat_df['target'].apply(label_regime)
    X = feat_df[FEATURE_COLS]
    y = feat_df['label']
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        class_weight='balanced',
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print('\n===== 3クラス分類 (Low / Mid / High) =====')
    print(classification_report(y_test, y_pred, target_names=['Low', 'Mid', 'High']))

    feat_imp = pd.Series(model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print('特徴量重要度 (上位10):')
    print(feat_imp.head(10).to_string())

    return model, X_test, y_test


def train_binary(feat_df: pd.DataFrame):
    feat_df['label_binary'] = (feat_df['target'] < 1.5).astype(int)
    X = feat_df[FEATURE_COLS]
    y = feat_df['label_binary']
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    pos_ratio = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        scale_pos_weight=pos_ratio,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, proba)
    print(f'\n===== 2値分類 (次が Low < 1.5x か？) =====')
    print(f'AUC: {auc:.4f}')
    y_pred = (proba >= 0.5).astype(int)
    print(classification_report(y_test, y_pred, target_names=['Not-Low', 'Low']))

    return model, X_test, y_test


def save_models(multiclass_model, binary_model):
    os.makedirs(MODEL_DIR, exist_ok=True)
    mc_path = os.path.join(MODEL_DIR, 'multiclass.pkl')
    bi_path = os.path.join(MODEL_DIR, 'binary.pkl')
    with open(mc_path, 'wb') as f:
        pickle.dump(multiclass_model, f)
    with open(bi_path, 'wb') as f:
        pickle.dump(binary_model, f)
    print(f'\nモデルを保存しました: {mc_path}, {bi_path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', default='docs/rounds_export_ml.csv')
    parser.add_argument('--save', action='store_true', default=True, help='モデルを保存する')
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), '..', csv_path)

    print(f'データ読み込み: {csv_path}')
    df = pd.read_csv(csv_path, parse_dates=['recorded_at'])
    df = df.sort_values('recorded_at').reset_index(drop=True)
    print(f'件数: {len(df)}  期間: {df["recorded_at"].min()} 〜 {df["recorded_at"].max()}')

    feat_df = make_features(df)
    print(f'特徴量行数: {len(feat_df)}')

    mc_model, _, _ = train_multiclass(feat_df.copy())
    bi_model, _, _ = train_binary(feat_df.copy())

    if args.save:
        save_models(mc_model, bi_model)


if __name__ == '__main__':
    main()
