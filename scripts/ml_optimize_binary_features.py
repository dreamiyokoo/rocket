"""
2値分類 (Blue <= 2.0x) 向け特徴量の拡張探索。

使い方:
  python3 scripts/ml_optimize_binary_features.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

WINDOW = 30
BASE_FEATURES = [
    "mean",
    "median",
    "std",
    "max",
    "min",
    "cv",
    "prob_2x",
    "prob_5x",
    "prob_10x",
    "low_streak",
    "slope",
    "log_mean",
    "log_std",
    "momentum",
]


def make_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    rows = []
    for i in range(window, len(df)):
        w = df["multiplier"].iloc[i - window : i].values
        rows.append(
            {
                "mean": np.mean(w),
                "median": np.median(w),
                "std": np.std(w),
                "max": np.max(w),
                "min": np.min(w),
                "cv": np.std(w) / (np.mean(w) + 1e-6),
                "prob_2x": np.mean(w >= 2.0),
                "prob_5x": np.mean(w >= 5.0),
                "prob_10x": np.mean(w >= 10.0),
                "low_streak": sum(1 for x in reversed(w) if x < 1.5),
                "slope": np.polyfit(np.arange(window), np.log(np.maximum(w, 0.01)), 1)[0],
                "log_mean": np.mean(np.log(np.maximum(w, 0.01))),
                "log_std": np.std(np.log(np.maximum(w, 0.01))),
                "momentum": np.mean(w[-5:]) - np.mean(w[:5]),
                # binary 用拡張特徴
                "prob_12": np.mean(w <= 1.2),
                "prob_15": np.mean(w <= 1.5),
                "prob_20": np.mean(w <= 2.0),
                "min5": np.min(w[-5:]),
                "mean5": np.mean(w[-5:]),
                "mean10": np.mean(w[-10:]),
                "std5": np.std(w[-5:]),
                "very_low_streak": sum(1 for x in reversed(w) if x <= 1.2),
                "target": df["multiplier"].iloc[i],
            }
        )
    return pd.DataFrame(rows)


def train_eval_auc(X_train, y_train, X_test, y_test):
    spw = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=31,
        min_child_samples=20,
        scale_pos_weight=spw,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)
    prob = model.predict_proba(X_test)[:, 1]
    return roc_auc_score(y_test, prob)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="docs/rounds_export_ml.csv")
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), "..", csv_path)

    df = pd.read_csv(csv_path, names=["id", "multiplier", "recorded_at"], parse_dates=["recorded_at"])
    df = df.sort_values("recorded_at").reset_index(drop=True)
    feat_df = make_features(df)

    y = (feat_df["target"] <= 2.0).astype(int)

    feature_sets = {
        "base": BASE_FEATURES,
        "base_plus_prob12": BASE_FEATURES + ["prob_12"],
        "base_plus_low_probs": BASE_FEATURES + ["prob_12", "prob_15", "prob_20"],
        "base_plus_recent_stats": BASE_FEATURES + ["mean5", "mean10", "std5", "min5"],
        "base_plus_streak": BASE_FEATURES + ["very_low_streak", "prob_12", "prob_15"],
        "all_extended": BASE_FEATURES + ["prob_12", "prob_15", "prob_20", "min5", "mean5", "mean10", "std5", "very_low_streak"],
    }

    n = len(feat_df)
    split = int(n * 0.8)

    print("=== Binary feature-set comparison (test AUC) ===")
    best_name = None
    best_auc = -1.0
    base_auc = None

    for name, cols in feature_sets.items():
        X = feat_df[cols]
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]
        auc = train_eval_auc(X_train, y_train, X_test, y_test)
        print(f"{name:>24}: auc={auc:.4f}")
        if name == "base":
            base_auc = auc
        if auc > best_auc:
            best_auc = auc
            best_name = name

    print("\nBest feature set:", best_name)
    print(f"base_auc: {base_auc:.4f}")
    print(f"best_auc: {best_auc:.4f}")
    print(f"delta: {best_auc - base_auc:+.4f}")


if __name__ == "__main__":
    main()
