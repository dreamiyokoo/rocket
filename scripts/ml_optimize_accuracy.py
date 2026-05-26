"""
精度向上向けの時系列最適化スクリプト。
- 4クラス Accuracy を主目的に、時系列ホールドアウトで設定探索
- 追加で 2値AUC も併記して劣化を監視

使い方:
  python3 scripts/ml_optimize_accuracy.py --csv docs/rounds_export_ml.csv
"""

import argparse
import os
from dataclasses import dataclass
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, f1_score, roc_auc_score

WINDOW = 30
FEATURE_COLS = [
    "mean",
    "median",
    "std",
    "max",
    "min",
    "p90",
    "p95",
    "max5",
    "gap_since_10x",
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
    class_weight: Optional[str]
    half_life: Optional[int]


def load_rounds_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["recorded_at"])
    if {"id", "multiplier", "recorded_at"}.issubset(df.columns):
        return df

    return pd.read_csv(
        csv_path,
        names=["id", "multiplier", "recorded_at"],
        parse_dates=["recorded_at"],
        skiprows=1,
    )


def make_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    rows = []
    for i in range(window, len(df)):
        w = df["multiplier"].iloc[i - window : i].values
        row = {
            "mean": np.mean(w),
            "median": np.median(w),
            "std": np.std(w),
            "max": np.max(w),
            "min": np.min(w),
            "p90": np.percentile(w, 90),
            "p95": np.percentile(w, 95),
            "max5": np.max(w[-5:]),
            "gap_since_10x": next((j for j, x in enumerate(reversed(w)) if x >= 10.0), window),
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
        rows.append(row)
    return pd.DataFrame(rows)


def label_regime(x: float) -> int:
    if x <= 2.0:
        return 0
    if x <= 5.0:
        return 1
    if x <= 10.0:
        return 2
    return 3


def recency_weight(n: int, half_life: Optional[int]) -> np.ndarray:
    if not half_life or half_life <= 0:
        return np.ones(n)
    idx = np.arange(n)
    age = (n - 1) - idx
    return np.power(0.5, age / half_life)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="docs/rounds_export_ml.csv")
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), "..", csv_path)

    df = load_rounds_csv(csv_path)
    df = df.sort_values("recorded_at").reset_index(drop=True)

    feat_df = make_features(df)
    X = feat_df[FEATURE_COLS]
    y_multi = feat_df["target"].apply(label_regime)
    y_bin = (feat_df["target"] <= 2.0).astype(int)

    n_total = len(feat_df)
    split_test = int(n_total * 0.8)

    X_train_full, X_test = X.iloc[:split_test], X.iloc[split_test:]
    y_train_full_multi, y_test_multi = y_multi.iloc[:split_test], y_multi.iloc[split_test:]
    y_train_full_bin, y_test_bin = y_bin.iloc[:split_test], y_bin.iloc[split_test:]

    split_val = int(len(X_train_full) * 0.8)
    X_train, X_val = X_train_full.iloc[:split_val], X_train_full.iloc[split_val:]
    y_train_multi, y_val_multi = y_train_full_multi.iloc[:split_val], y_train_full_multi.iloc[split_val:]

    candidates = [
        Candidate("base", 300, 0.05, 4, 15, 20, "balanced", None),
        Candidate("deeper", 500, 0.03, 6, 31, 30, "balanced", None),
        Candidate("small_lr", 700, 0.02, 6, 31, 40, "balanced", None),
        Candidate("recency_2000", 500, 0.03, 6, 31, 30, "balanced", 2000),
        Candidate("recency_1200", 500, 0.03, 6, 31, 30, "balanced", 1200),
        Candidate("recency_800", 400, 0.04, 5, 31, 30, "balanced", 800),
        Candidate("no_class_weight", 500, 0.03, 6, 31, 30, None, 1200),
    ]

    best = None
    best_score = -1.0

    print("=== Validation Search (4class balance priority) ===")
    for c in candidates:
        w = recency_weight(len(X_train), c.half_life)
        model = lgb.LGBMClassifier(
            n_estimators=c.n_estimators,
            learning_rate=c.learning_rate,
            max_depth=c.max_depth,
            num_leaves=c.num_leaves,
            min_child_samples=c.min_child_samples,
            class_weight=c.class_weight,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train_multi, sample_weight=w)
        pred_val = model.predict(X_val)
        acc = accuracy_score(y_val_multi, pred_val)
        balanced_acc = balanced_accuracy_score(y_val_multi, pred_val)
        macro_f1 = f1_score(y_val_multi, pred_val, average="macro", zero_division=0)
        balance_score = (balanced_acc + macro_f1) / 2
        print(
            f"{c.name:>16}: acc={acc:.4f} balanced_acc={balanced_acc:.4f} "
            f"macro_f1={macro_f1:.4f} score={balance_score:.4f}"
        )
        if balance_score > best_score:
            best_score = balance_score
            best = c

    assert best is not None
    print("\nBest config:", best)

    w_full = recency_weight(len(X_train_full), best.half_life)
    mc_model = lgb.LGBMClassifier(
        n_estimators=best.n_estimators,
        learning_rate=best.learning_rate,
        max_depth=best.max_depth,
        num_leaves=best.num_leaves,
        min_child_samples=best.min_child_samples,
        class_weight=best.class_weight,
        random_state=42,
        verbose=-1,
    )
    mc_model.fit(X_train_full, y_train_full_multi, sample_weight=w_full)
    pred_test = mc_model.predict(X_test)
    acc_test = accuracy_score(y_test_multi, pred_test)
    balanced_acc_test = balanced_accuracy_score(y_test_multi, pred_test)
    macro_f1_test = f1_score(y_test_multi, pred_test, average="macro", zero_division=0)

    print("\n===== 4class Test =====")
    print(f"accuracy: {acc_test:.4f}")
    print(f"balanced_accuracy: {balanced_acc_test:.4f}")
    print(f"macro_f1: {macro_f1_test:.4f}")
    print(classification_report(y_test_multi, pred_test, target_names=["Blue", "Green", "Yellow", "Red"]))

    # 2値モデルは既存に近い設定で、同じ重みのみ適用
    pos_ratio = (y_train_full_bin == 0).sum() / max((y_train_full_bin == 1).sum(), 1)
    bi_model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        scale_pos_weight=pos_ratio,
        random_state=42,
        verbose=-1,
    )
    bi_model.fit(X_train_full, y_train_full_bin, sample_weight=w_full)
    prob_test = bi_model.predict_proba(X_test)[:, 1]
    auc_test = roc_auc_score(y_test_bin, prob_test)

    print("===== Binary Test (Blue<=2.0) =====")
    print(f"AUC: {auc_test:.4f}")


if __name__ == "__main__":
    main()
