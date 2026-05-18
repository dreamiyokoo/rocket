import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score, confusion_matrix
import os

# 1) Load data
csv_path = 'docs/rounds_export_ml.csv'
names = ['id', 'multiplier', 'recorded_at']
df = pd.read_csv(csv_path, names=names, parse_dates=['recorded_at'])
df = df.sort_values('recorded_at').reset_index(drop=True)

# 2) Feature Engineering (Window=30)
WINDOW = 30
target_col = 'multiplier'

def create_features(df, window):
    # Basic stats
    rolling = df[target_col].rolling(window)
    df['mean'] = rolling.mean()
    df['median'] = rolling.median()
    df['std'] = rolling.std()
    df['max'] = rolling.max()
    df['min'] = rolling.min()
    df['cv'] = df['std'] / df['mean']
    
    # Simple probability
    df['prob_2x'] = rolling.apply(lambda x: (x >= 2.0).mean(), raw=True)
    df['prob_5x'] = rolling.apply(lambda x: (x >= 5.0).mean(), raw=True)
    df['prob_10x'] = rolling.apply(lambda x: (x >= 10.0).mean(), raw=True)
    
    # Streak
    df['is_low'] = (df[target_col] <= 1.2).astype(int)
    df['low_streak'] = df['is_low'].rolling(window).sum()
    
    # Slope
    # Use raw=True and index into numpy array
    df['slope'] = rolling.apply(lambda x: (x[-1] - x[0]) / len(x) if len(x) > 0 else 0, raw=True)
    
    # Log stats
    log_v = np.log1p(df[target_col])
    rolling_log = log_v.rolling(window)
    df['log_mean'] = rolling_log.mean()
    df['log_std'] = rolling_log.std()
    
    # Momentum
    df['momentum'] = df[target_col] / df[target_col].shift(window)
    
    # Target features for (6)
    df['rolling_prob12'] = rolling.apply(lambda x: (x <= 1.2).mean(), raw=True)
    df['trend_up'] = (df['rolling_prob12'].diff(3) > 0).astype(int)
    
    return df

df = create_features(df, WINDOW)
df = df.dropna().reset_index(drop=True)

features = ['mean', 'median', 'std', 'max', 'min', 'cv', 'prob_2x', 'prob_5x', 'prob_10x', 
            'low_streak', 'slope', 'log_mean', 'log_std', 'momentum']

# 3) Split
split_idx = int(len(df) * 0.8)
train_df = df.iloc[:split_idx]
test_df = df.iloc[split_idx:].copy()

def train_and_eval(target_name, y_train, y_test, X_train, X_test):
    pos_count = y_train.sum()
    neg_count = len(y_train) - pos_count
    spw = neg_count / pos_count if pos_count > 0 else 1.0
    
    params = {
        'n_estimators': 300,
        'learning_rate': 0.05,
        'max_depth': 4,
        'random_state': 42,
        'verbose': -1,
        'scale_pos_weight': spw,
        'objective': 'binary',
        'metric': 'binary_logloss'
    }
    
    model = lgb.LGBMClassifier(**params)
    model.fit(X_train, y_train)
    
    probs = model.predict_proba(X_test)[:, 1]
    
    roc_auc = roc_auc_score(y_test, probs)
    pr_auc = average_precision_score(y_test, probs)
    
    # Find threshold for recall >= 0.90
    thresholds = np.linspace(0, 1, 1001)
    best_t = 0.0
    best_metrics = {}
    
    # Reverse search to find the maximum t that satisfies recall >= 0.90
    # Actually, as t increases, recall decreases. So we want the highest t with recall >= 0.9.
    found = False
    for t in thresholds:
        preds = (probs >= t).astype(int)
        tp = ((preds == 1) & (y_test == 1)).sum()
        fn = ((preds == 0) & (y_test == 1)).sum()
        fp = ((preds == 1) & (y_test == 0)).sum()
        tn = ((preds == 0) & (y_test == 0)).sum()
        
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        if recall >= 0.90:
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
            skip_rate = (tn + fn) / len(y_test)
            mpr = fn / (tp + fn) if (tp + fn) > 0 else 0
            best_t = t
            best_metrics = {
                'threshold': t,
                'recall': recall,
                'precision': precision,
                'fpr': fpr,
                'skip_rate': skip_rate,
                'missed_positive_rate': mpr
            }
            found = True
        else:
            # recall dropped below 0.9
            break
            
    if not found:
        # Fallback if no threshold meets 0.9 (e.g. t=0)
        best_metrics = {'threshold': 0, 'recall': 0, 'precision': 0, 'fpr': 0, 'skip_rate': 0, 'missed_positive_rate': 0}

    return roc_auc, pr_auc, best_metrics, probs

# Target A: y_12 = (multiplier <= 1.2)
y_train_12 = (train_df[target_col] <= 1.2).astype(int)
y_test_12 = (test_df[target_col] <= 1.2).astype(int)
roc12, pr12, m12, p12 = train_and_eval("y_12", y_train_12, y_test_12, train_df[features], test_df[features])

# Target B: y_20 = (multiplier <= 2.0)
y_train_20 = (train_df[target_col] <= 2.0).astype(int)
y_test_20 = (test_df[target_col] <= 2.0).astype(int)
roc20, pr20, m20, p20 = train_and_eval("y_20", y_train_20, y_test_20, train_df[features], test_df[features])

# 6) Trend rules
t12_90 = m12['threshold']
roll_p12 = test_df['rolling_prob12'].values
trend_up = test_df['trend_up'].values
flag_trend = ((p12 >= t12_90) | ((roll_p12 >= 0.22) & (trend_up == 1))).astype(int)

tp = ((flag_trend == 1) & (y_test_12 == 1)).sum()
fn = ((flag_trend == 0) & (y_test_12 == 1)).sum()
fp = ((flag_trend == 1) & (y_test_12 == 0)).sum()
tn = ((flag_trend == 0) & (y_test_12 == 0)).sum()

trend_metrics = {
    'recall': tp / (tp + fn) if (tp + fn) > 0 else 0,
    'precision': tp / (tp + fp) if (tp + fp) > 0 else 0,
    'skip_rate': (tn + fn) / len(y_test_12),
    'missed_positive_rate': fn / (tp + fn) if (tp + fn) > 0 else 0
}

# 7) Output results
print("| 指標 | タスクA (<=1.2) | タスクB (<=2.0) |")
print("| :--- | :--- | :--- |")
print(f"| ROC-AUC | {roc12:.4f} | {roc20:.4f} |")
print(f"| PR-AUC | {pr12:.4f} | {pr20:.4f} |")
print(f"| 閾値 (Recall>=0.90) | {m12['threshold']:.4f} | {m20['threshold']:.4f} |")
print(f"| Recall | {m12['recall']:.4f} | {m20['recall']:.4f} |")
print(f"| Precision | {m12['precision']:.4f} | {m20['precision']:.4f} |")
print(f"| FPR | {m12['fpr']:.4f} | {m20['fpr']:.4f} |")
print(f"| Skip Rate | {m12['skip_rate']:.4f} | {m20['skip_rate']:.4f} |")
print(f"| Missed Positive Rate | {m12['missed_positive_rate']:.4f} | {m20['missed_positive_rate']:.4f} |")

print("\n| 指標 | トレンド併用ルール (タスクAベース) |")
print("| :--- | :--- |")
print(f"| Recall | {trend_metrics['recall']:.4f} |")
print(f"| Precision | {trend_metrics['precision']:.4f} |")
print(f"| Skip Rate | {trend_metrics['skip_rate']:.4f} |")
print(f"| Missed Positive Rate | {trend_metrics['missed_positive_rate']:.4f} |")

