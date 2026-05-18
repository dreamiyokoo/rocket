"""ML 特徴量エンジニアリング（直近 N 件のウィンドウ統計）"""
from __future__ import annotations

import math

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


def _safe_log(x: float) -> float:
    return math.log(max(x, 0.01))


def _polyfit_slope(values: list[float]) -> float:
    """線形回帰の傾き（対数変換後）"""
    n = len(values)
    xs = list(range(n))
    log_ys = [_safe_log(v) for v in values]
    mean_x = sum(xs) / n
    mean_y = sum(log_ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, log_ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den != 0 else 0.0


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]


def make_feature_vector(window: list[float]) -> list[float]:
    """直近 WINDOW 件から 14 特徴量ベクトルを生成する。

    Args:
        window: 長さ WINDOW の直近倍率リスト（古い順）

    Returns:
        FEATURE_COLS 順の特徴量リスト
    """
    n = len(window)
    mean = sum(window) / n
    median = _median(window)
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / n)
    cv = std / (mean + 1e-6)

    prob_2x = sum(1 for x in window if x >= 2.0) / n
    prob_5x = sum(1 for x in window if x >= 5.0) / n
    prob_10x = sum(1 for x in window if x >= 10.0) / n

    low_streak = 0
    for x in reversed(window):
        if x < 1.5:
            low_streak += 1
        else:
            break

    slope = _polyfit_slope(window)

    log_vals = [_safe_log(x) for x in window]
    log_mean = sum(log_vals) / n
    log_std = math.sqrt(sum((v - log_mean) ** 2 for v in log_vals) / n)

    momentum = sum(window[-5:]) / 5 - sum(window[:5]) / 5

    return [
        mean, median, std, max(window), min(window), cv,
        prob_2x, prob_5x, prob_10x, low_streak,
        slope, log_mean, log_std, momentum,
    ]
