import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

def make_features(multipliers):
    # Same as scripts/ml_model.py make_features
    feats = {
        'mean': np.mean(multipliers),
        'std': np.std(multipliers),
        'min': np.min(multipliers),
        'max': np.max(multipliers),
        'median': np.median(multipliers),
        'last': multipliers[-1],
        'last2_mean': np.mean(multipliers[-2:]),
        'last5_mean': np.mean(multipliers[-5:]),
        'last10_mean': np.mean(multipliers[-10:]),
    }
    return list(feats.values())

def categorize_4class(m):
    if m <= 2: return 0
    if m <= 5: return 1
    if m <= 10: return 2
    return 3

def prepare_data(csv_path, window_size):
    df = pd.read_csv(csv_path, names=['id', 'multiplier', 'recorded_at'], parse_dates=['recorded_at'])
    df = df.sort_values('recorded_at')
    
    multipliers = df['multiplier'].values
    
    X = []
    y_4class = []
    y_binary = [] # target <= 2 is 1 (Blue)
    
    for i in range(window_size, len(multipliers)):
        window = multipliers[i - window_size : i]
        target = multipliers[i]
        
        X.append(make_features(window))
        y_4class.append(categorize_4class(target))
        y_binary.append(1 if target <= 2 else 0)
        
    return np.array(X), np.array(y_4class), np.array(y_binary)

windows = [20, 30, 40, 60, 80]
results = []

csv_path = 'docs/rounds_export_ml.csv'
lgbm_params = {
    'objective': 'multiclass',
    'num_class': 4,
    'metric': 'multi_logloss',
    'verbosity': -1,
    'boosting_type': 'gbdt',
    'random_state': 42,
    'learning_rate': 0.05,
    'num_leaves': 31,
    'feature_fraction': 0.9,
    'bagging_fraction': 0.8,
    'bagging_freq': 5
}

for w in windows:
    X, y4, yb = prepare_data(csv_path, w)
    
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y4_train, y4_test = y4[:split_idx], y4[split_idx:]
    yb_train, yb_test = yb[:split_idx], yb[split_idx:]
    
    train_data = lgb.Dataset(X_train, label=y4_train)
    model = lgb.train(lgbm_params, train_data, num_boost_round=100)
    
    y4_pred_prob = model.predict(X_test)
    y4_pred = np.argmax(y4_pred_prob, axis=1)
    
    acc = accuracy_score(y4_test, y4_pred)
    f1s = f1_score(y4_test, y4_pred, average=None, labels=[0, 1, 2, 3])
    
    # 2値AUC: target <= 2 (class 0) を positive とする
    # y4_pred_prob[:, 0] は class 0 の確率
    auc = roc_auc_score(yb_test, y4_pred_prob[:, 0])
    
    results.append({
        'WINDOW': w,
        'Accuracy': acc,
        'F1_Blue': f1s[0], # <=2
        'F1_Green': f1s[1], # <=5
        'F1_Yellow': f1s[2], # <=10
        'F1_Red': f1s[3], # >10
        'AUC_Blue': auc
    })

res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))

print("\nDifferences from WINDOW 20:")
base = res_df.iloc[0]
diffs = res_df.copy()
for col in res_df.columns[1:]:
    diffs[col] = res_df[col] - base[col]
print(diffs.to_string(index=False))
