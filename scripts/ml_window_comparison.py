"""
ウィンドウサイズ比較実験スクリプト
異なるウィンドウサイズ (18, 20, 36) でモデルを訓練し、性能を比較

使い方:
  python3 scripts/ml_window_comparison.py
  python3 scripts/ml_window_comparison.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, accuracy_score

FEATURE_COLS = [
    'mean', 'median', 'std', 'max', 'min', 'cv',
    'prob_2x', 'prob_5x', 'prob_10x', 'low_streak',
    'slope', 'log_mean', 'log_std', 'momentum',
]


def make_features(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """指定されたウィンドウサイズで特徴量を生成"""
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
    """倍率をクラスに変換: Blue(0) / Green(1) / Yellow(2) / Red(3)"""
    if x <= 2.0:
        return 0  # Blue  (≤ 2.0x)
    if x <= 5.0:
        return 1  # Green (2.01〜5.0x)
    if x <= 10.0:
        return 2  # Yellow (5.01〜10.0x)
    return 3      # Red   (> 10.0x)


def train_multiclass(feat_df: pd.DataFrame, window: int):
    """4クラス分類モデルを訓練"""
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
    y_proba = model.predict_proba(X_test)

    # 精度指標
    accuracy = accuracy_score(y_test, y_pred)
    
    # Blue確率の ROC AUC（2値: Blue vs Not Blue）
    y_binary = (y_test == 0).astype(int)
    y_proba_blue = y_proba[:, 0]
    try:
        roc_auc = roc_auc_score(y_binary, y_proba_blue)
    except:
        roc_auc = np.nan

    return {
        'window': window,
        'accuracy': accuracy,
        'roc_auc': roc_auc,
        'model': model,
        'X_test': X_test,
        'y_test': y_test,
        'y_pred': y_pred,
        'class_report': classification_report(y_test, y_pred, output_dict=True),
    }


def train_binary(feat_df: pd.DataFrame, window: int):
    """2値分類モデルを訓練（Blue判定）"""
    feat_df['label_binary'] = (feat_df['target'] <= 2.0).astype(int)
    X = feat_df[FEATURE_COLS]
    y = feat_df['label_binary']
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
    y_proba = model.predict_proba(X_test)[:, 1]

    # 精度指標
    accuracy = accuracy_score(y_test, y_pred)
    roc_auc = roc_auc_score(y_test, y_proba)

    return {
        'window': window,
        'accuracy': accuracy,
        'roc_auc': roc_auc,
        'model': model,
        'X_test': X_test,
        'y_test': y_test,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', default='docs/rounds_export_ml.csv')
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), '..', csv_path)

    print(f'データ読み込み: {csv_path}')
    df = pd.read_csv(csv_path, names=['id', 'multiplier', 'recorded_at'], parse_dates=['recorded_at'])
    df = df.sort_values('recorded_at').reset_index(drop=True)
    print(f'総件数: {len(df)}\n')

    windows = [18, 20, 36]
    results_multi = []
    results_binary = []

    print('=' * 80)
    print('ウィンドウサイズ比較実験')
    print('=' * 80)

    for w in windows:
        print(f'\n【ウィンドウサイズ: {w}】')
        print(f'  特徴量生成中...')
        feat_df = make_features(df, w)
        print(f'  学習用サンプル数: {len(feat_df)}')

        # 4クラス分類
        print(f'  4クラス分類を訓練中...')
        result_multi = train_multiclass(feat_df, w)
        results_multi.append(result_multi)
        print(f'    精度: {result_multi["accuracy"]:.4f}')
        print(f'    ROC AUC (Blue): {result_multi["roc_auc"]:.4f}')

        # 2値分類
        print(f'  2値分類を訓練中...')
        result_binary = train_binary(feat_df, w)
        results_binary.append(result_binary)
        print(f'    精度: {result_binary["accuracy"]:.4f}')
        print(f'    ROC AUC: {result_binary["roc_auc"]:.4f}')

    # 比較結果をサマリーテーブルで出力
    print('\n' + '=' * 80)
    print('比較サマリー')
    print('=' * 80)

    print('\n【4クラス分類】')
    print(f'{"Window":>10} {"精度":>10} {"ROC AUC":>10}')
    print('-' * 32)
    for r in results_multi:
        print(f'{r["window"]:>10} {r["accuracy"]:>10.4f} {r["roc_auc"]:>10.4f}')

    print('\n【2値分類 (Blue判定)】')
    print(f'{"Window":>10} {"精度":>10} {"ROC AUC":>10}')
    print('-' * 32)
    for r in results_binary:
        print(f'{r["window"]:>10} {r["accuracy"]:>10.4f} {r["roc_auc"]:>10.4f}')

    # 詳細レポート
    print('\n' + '=' * 80)
    print('詳細分類レポート')
    print('=' * 80)

    for i, w in enumerate(windows):
        print(f'\n【Window={w}: 4クラス分類】')
        print(results_multi[i]['class_report'])

    # ウィンドウサイズの影響をまとめて表示
    print('\n' + '=' * 80)
    print('ウィンドウサイズの影響分析')
    print('=' * 80)
    
    acc_18_multi = results_multi[0]['accuracy']
    acc_20_multi = results_multi[1]['accuracy']
    acc_36_multi = results_multi[2]['accuracy']
    
    acc_18_binary = results_binary[0]['accuracy']
    acc_20_binary = results_binary[1]['accuracy']
    acc_36_binary = results_binary[2]['accuracy']
    
    print(f'\n4クラス分類:')
    print(f'  W=18: {acc_18_multi:.4f}')
    print(f'  W=20: {acc_20_multi:.4f} (基準)')
    print(f'  W=36: {acc_36_multi:.4f}')
    print(f'  18→36の変化: {(acc_36_multi - acc_18_multi) / acc_18_multi * 100:+.1f}%')
    
    print(f'\n2値分類 (Blue判定):')
    print(f'  W=18: {acc_18_binary:.4f}')
    print(f'  W=20: {acc_20_binary:.4f} (基準)')
    print(f'  W=36: {acc_36_binary:.4f}')
    print(f'  18→36の変化: {(acc_36_binary - acc_18_binary) / acc_18_binary * 100:+.1f}%')

    print('\n結論:')
    best_window_multi = max(results_multi, key=lambda x: x['accuracy'])
    best_window_binary = max(results_binary, key=lambda x: x['accuracy'])
    print(f'  4クラス分類: W={best_window_multi["window"]} が最適 (精度={best_window_multi["accuracy"]:.4f})')
    print(f'  2値分類: W={best_window_binary["window"]} が最適 (精度={best_window_binary["accuracy"]:.4f})')


if __name__ == '__main__':
    main()
