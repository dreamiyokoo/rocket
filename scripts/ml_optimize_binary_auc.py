"""
2値分類 (Blue <= 2.0x) の AUC 最適化スクリプト。

使い方:
  python3 scripts/ml_optimize_binary_auc.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os
from dataclasses import dataclass
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

WINDOW = 30
FEATURE_COLS = [
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


@dataclass
class Candidate:
    name: str
    n_estimators: int
    learning_rate: float
    max_depth: int
    num_leaves: int
    min_child_samples: int
    scale_pos_weight_mode: str  # auto | balanced | fixed
    fixed_spw: Optional[float]
    half_life: Optional[int]


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
                "target": df["multiplier"].iloc[i],
            }
        )
    return pd.DataFrame(rows)


def recency_weight(n: int, half_life: Optional[int]) -> np.ndarray:
    if not half_life or half_life <= 0:
        return np.ones(n)
    idx = np.arange(n)
    age = (n - 1) - idx
    return np.power(0.5, age / half_life)


def spw_for_mode(y, mode: str, fixed: Optional[float]) -> float:
    if mode == "fixed" and fixed is not None:
        return float(fixed)
    neg = int((y == 0).sum())
    pos = int((y == 1).sum())
    ratio = neg / max(pos, 1)
    if mode == "balanced":
        return max(1.0, ratio * 0.8)
    return ratio


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

    X = feat_df[FEATURE_COLS]
    y = (feat_df["target"] <= 2.0).astype(int)

    n_total = len(X)
    split_test = int(n_total * 0.8)
    X_train_full, X_test = X.iloc[:split_test], X.iloc[split_test:]
    y_train_full, y_test = y.iloc[:split_test], y.iloc[split_test:]

    split_val = int(len(X_train_full) * 0.8)
    X_train, X_val = X_train_full.iloc[:split_val], X_train_full.iloc[split_val:]
    y_train, y_val = y_train_full.iloc[:split_val], y_train_full.iloc[split_val:]

    candidates = [
        Candidate("baseline", 300, 0.05, 4, 15, 20, "auto", None, 1200),
        Candidate("more_trees", 600, 0.03, 5, 31, 20, "auto", None, 1200),
        Candidate("small_lr", 900, 0.02, 6, 31, 30, "auto", None, 1200),
        Candidate("no_recency", 600, 0.03, 5, 31, 20, "auto", None, None),
        Candidate("recency_800", 600, 0.03, 5, 31, 20, "auto", None, 800),
        Candidate("recency_2000", 600, 0.03, 5, 31, 20, "auto", None, 2000),
        Candidate("balanced_spw", 600, 0.03, 5, 31, 20, "balanced", None, 1200),
        Candidate("fixed_spw_1", 600, 0.03, 5, 31, 20, "fixed", 1.0, 1200),
        Candidate("fixed_spw_1_5", 600, 0.03, 5, 31, 20, "fixed", 1.5, 1200),
        Candidate("fixed_spw_2", 600, 0.03, 5, 31, 20, "fixed", 2.0, 1200),
    ]

    best = None
    best_auc = -1.0

    print("=== Validation Search (binary AUC priority) ===")
    for c in candidates:
        w = recency_weight(len(X_train), c.half_life)
        spw = spw_for_mode(y_train, c.scale_pos_weight_mode, c.fixed_spw)
        model = lgb.LGBMClassifier(
            n_estimators=c.n_estimators,
            learning_rate=c.learning_rate,
            max_depth=c.max_depth,
            num_leaves=c.num_leaves,
            min_child_samples=c.min_child_samples,
            scale_pos_weight=spw,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train, sample_weight=w)
        prob_val = model.predict_proba(X_val)[:, 1]
        auc = roc_auc_score(y_val, prob_val)
        print(f"{c.name:>14}: val_auc={auc:.4f} spw={spw:.3f}")
        if auc > best_auc:
            best_auc = auc
            best = (c, spw)

    assert best is not None
    c, spw = best
    print("\nBest config:", c)
    print(f"Best spw: {spw:.4f}")

    w_full = recency_weight(len(X_train_full), c.half_life)
    model = lgb.LGBMClassifier(
        n_estimators=c.n_estimators,
        learning_rate=c.learning_rate,
        max_depth=c.max_depth,
        num_leaves=c.num_leaves,
        min_child_samples=c.min_child_samples,
        scale_pos_weight=spw_for_mode(y_train_full, c.scale_pos_weight_mode, c.fixed_spw),
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train_full, y_train_full, sample_weight=w_full)
    prob_test = model.predict_proba(X_test)[:, 1]
    auc_test = roc_auc_score(y_test, prob_test)

    baseline = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        scale_pos_weight=spw_for_mode(y_train_full, "auto", None),
        random_state=42,
        verbose=-1,
    )
    baseline.fit(X_train_full, y_train_full, sample_weight=recency_weight(len(X_train_full), 1200))
    baseline_auc = roc_auc_score(y_test, baseline.predict_proba(X_test)[:, 1])

    print("\n===== Test Comparison =====")
    print(f"baseline_auc: {baseline_auc:.4f}")
    print(f"best_auc:     {auc_test:.4f}")
    print(f"delta:        {auc_test - baseline_auc:+.4f}")


if __name__ == "__main__":
    main()
