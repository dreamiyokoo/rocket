"""
ML モデル構築スクリプト
- LightGBM 4クラス分類 (Blue <=2x / Green 2-5x / Yellow 5-10x / Red >10x)
- LightGBM 2値分類 (次が Blue <= 2.0x か)

使い方:
  python3 scripts/ml_model.py
  python3 scripts/ml_model.py --csv docs/rounds_export_ml.csv
"""

import argparse
import json
import os
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

WINDOW = 30
RECENCY_HALF_LIFE = 1200
MULTICLASS_FEATURE_COLS = [
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
BINARY_EXTRA_FEATURE_COLS = [
    "prob_12",
    "prob_15",
    "prob_20",
    "min5",
    "mean5",
    "mean10",
    "std5",
    "very_low_streak",
]
BINARY_FEATURE_COLS = MULTICLASS_FEATURE_COLS + BINARY_EXTRA_FEATURE_COLS
_SCRIPT_DIR = os.path.dirname(__file__)
_CONTAINER_MODEL_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "ml", "models"))
_REPO_MODEL_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "api", "ml", "models"))
MODEL_DIR = os.environ.get("ML_MODEL_DIR") or (
    _CONTAINER_MODEL_DIR if os.path.isdir(_CONTAINER_MODEL_DIR) else _REPO_MODEL_DIR
)
CLASS_NAMES = ["blue", "green", "yellow", "red"]


def recency_weight(n: int, half_life: int = RECENCY_HALF_LIFE) -> np.ndarray:
    idx = np.arange(n)
    age = (n - 1) - idx
    return np.power(0.5, age / half_life)


def threshold_for_target_recall(y_true, proba, target_recall: float = 0.90):
    """目標再現率を満たす最大しきい値を返す。"""
    best = {
        "threshold": 0.5,
        "recall": 0.0,
        "precision": 0.0,
        "skip_rate": 0.0,
    }
    for t in np.linspace(0.0, 1.0, 1001):
        pred = (proba >= t).astype(int)
        tp = int(((pred == 1) & (y_true == 1)).sum())
        fn = int(((pred == 0) & (y_true == 1)).sum())
        fp = int(((pred == 1) & (y_true == 0)).sum())
        tn = int(((pred == 0) & (y_true == 0)).sum())
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        if recall >= target_recall:
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            skip_rate = (tn + fn) / max(len(y_true), 1)
            best = {
                "threshold": float(t),
                "recall": float(recall),
                "precision": float(precision),
                "skip_rate": float(skip_rate),
            }
        else:
            break
    return best


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
            # 2値分類向け追加特徴量
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


def train_multiclass(feat_df: pd.DataFrame):
    feat_df["label"] = feat_df["target"].apply(label_regime)
    X = feat_df[MULTICLASS_FEATURE_COLS]
    y = feat_df["label"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.03,
        max_depth=6,
        num_leaves=31,
        min_child_samples=30,
        class_weight='balanced',
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train, sample_weight=recency_weight(len(X_train)))

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    print("\n===== 4クラス分類 (Blue / Green / Yellow / Red) =====")
    print(
        classification_report(
            y_test,
            y_pred,
            target_names=["Blue(<=2x)", "Green(2-5x)", "Yellow(5-10x)", "Red(>10x)"],
        )
    )

    feat_imp = pd.Series(model.feature_importances_, index=MULTICLASS_FEATURE_COLS).sort_values(ascending=False)
    print("特徴量重要度 (上位10):")
    print(feat_imp.head(10).to_string())

    band_thresholds = tune_band_thresholds(y_test.values, y_proba)
    print("色別しきい値(One-vs-Rest F1 最適化):", band_thresholds)

    return model, band_thresholds


def tune_band_thresholds(y_true: np.ndarray, y_proba: np.ndarray) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    grid = np.linspace(0.05, 0.95, 91)

    for idx, name in enumerate(CLASS_NAMES):
        y_bin = (y_true == idx).astype(int)
        probs = y_proba[:, idx]
        best_t = 0.25
        best_f1 = -1.0
        for t in grid:
            pred = (probs >= t).astype(int)
            score = f1_score(y_bin, pred, zero_division=0)
            if score > best_f1:
                best_f1 = score
                best_t = float(t)
        thresholds[name] = round(best_t, 3)

    return thresholds


def train_binary(feat_df: pd.DataFrame):
    feat_df["label_binary"] = (feat_df["target"] <= 2.0).astype(int)
    X = feat_df[BINARY_FEATURE_COLS]
    y = feat_df["label_binary"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    pos_ratio = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=31,
        min_child_samples=20,
        scale_pos_weight=pos_ratio,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, proba)
    print("\n===== 2値分類 (次が Blue <= 2.0x か) =====")
    print(f"AUC: {auc:.4f}")

    y_pred = (proba >= 0.5).astype(int)
    print(classification_report(y_test, y_pred, target_names=["Not-Blue", "Blue"]))

    threshold_info = threshold_for_target_recall(y_test.values, proba, target_recall=0.90)
    print(
        "推奨しきい値 (Recall>=0.90): "
        f"{threshold_info['threshold']:.3f} "
        f"(Recall={threshold_info['recall']:.4f}, "
        f"Precision={threshold_info['precision']:.4f}, "
        f"SkipRate={threshold_info['skip_rate']:.4f})"
    )

    return model, threshold_info


def save_models(multiclass_model, binary_model, threshold_info: dict, band_thresholds: dict[str, float]):
    os.makedirs(MODEL_DIR, exist_ok=True)
    mc_path = os.path.join(MODEL_DIR, "multiclass.pkl")
    bi_path = os.path.join(MODEL_DIR, "binary.pkl")
    th_path = os.path.join(MODEL_DIR, "thresholds.json")

    with open(mc_path, "wb") as f:
        pickle.dump(multiclass_model, f)
    with open(bi_path, "wb") as f:
        pickle.dump(binary_model, f)
    with open(th_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "blue_warn_threshold": round(float(threshold_info["threshold"]), 3),
                "band_thresholds": band_thresholds,
            },
            f,
        )

    print(f"\nモデルを保存しました: {mc_path}, {bi_path}, {th_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="docs/rounds_export_ml.csv")
    parser.add_argument("--save", action="store_true", default=True, help="モデルを保存する")
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), "..", csv_path)

    print(f"データ読み込み: {csv_path}")
    df = pd.read_csv(csv_path, names=["id", "multiplier", "recorded_at"], parse_dates=["recorded_at"], skiprows=1)
    df = df.sort_values("recorded_at").reset_index(drop=True)
    print(f"件数: {len(df)}  期間: {df['recorded_at'].min()} 〜 {df['recorded_at'].max()}")

    feat_df = make_features(df)
    print(f"特徴量行数: {len(feat_df)}")

    mc_model, band_thresholds = train_multiclass(feat_df.copy())
    bi_model, threshold_info = train_binary(feat_df.copy())

    if args.save:
        save_models(mc_model, bi_model, threshold_info, band_thresholds)


if __name__ == "__main__":
    main()
