from __future__ import annotations

import statistics
from dataclasses import dataclass, field

WINDOW = 18
MAX_HISTORY = 72

# Default indicator periods (overridable via API query params)
RSI_PERIOD_DEFAULT = 14
MACD_FAST_DEFAULT = 12
MACD_SLOW_DEFAULT = 26
MACD_SIGNAL_DEFAULT = 9

# No-Entry Zone thresholds
NO_ENTRY_LOW_MULTIPLIER_THRESHOLD = 1.30   # values at or below this are "low"
NO_ENTRY_LOW_CONSECUTIVE_LIMIT    = 5      # condition ①: streak length trigger
NO_ENTRY_POST_SPIKE_THRESHOLD     = 10.0  # condition ②: "spike" definition
NO_ENTRY_POST_SPIKE_AVG_MAX       = 1.30  # condition ②: post-spike avg ceiling
NO_ENTRY_POST_SPIKE_WINDOW        = 3     # condition ②: how many post-spike values to average
NO_ENTRY_LOW_VOLATILITY_CV        = 0.25  # condition ③: CV below this → low vol
NO_ENTRY_LOW_EV_MEDIAN_THRESHOLD  = 1.50  # condition ④: median below this → low EV


@dataclass
class WindowStats:
    prob_2x: float
    prob_5x: float
    prob_10x: float
    moving_avg: float


@dataclass
class BollingerPoint:
    upper: float
    middle: float
    lower: float


@dataclass
class MacdPoint:
    macd: float
    signal: float | None
    histogram: float | None


REGIME_THRESHOLDS = (0.3, 0.8)  # (low/medium boundary, medium/high boundary)

# α for floor_line = median - α × std_dev
_ALPHA = {"low": 0.5, "medium": 0.75, "high": 1.0}
# β for target_line = mean + β × std_dev
_BETA  = {"low": 1.0, "medium": 1.5,  "high": 2.0}

FLOOR_LINE_MIN = 1.01  # recommendation lower bound (crash multiplier minimum payout is 1.01x)


@dataclass
class Recommendation:
    volatility_cv: float
    regime: str  # "low" | "medium" | "high"
    floor_line: float
    target_line: float


@dataclass
class NoEntry:
    active: bool
    reasons: list[str]
    low_consecutive_count: int
    volatility_cv: float
    median_value: float


@dataclass
class AnalysisResult:
    ready: bool
    total_rounds: int
    prob_2x: float | None = None
    prob_5x: float | None = None
    prob_10x: float | None = None
    moving_avg: float | None = None
    median: float | None = None
    std_dev: float | None = None
    max: float | None = None
    min: float | None = None
    atr: float | None = None
    bollinger_current: BollingerPoint | None = None
    bollinger_chart: list[BollingerPoint | None] = field(default_factory=list)
    rsi_period: int = RSI_PERIOD_DEFAULT
    rsi_chart: list[float | None] = field(default_factory=list)
    macd_fast: int = MACD_FAST_DEFAULT
    macd_slow: int = MACD_SLOW_DEFAULT
    macd_signal_period: int = MACD_SIGNAL_DEFAULT
    macd_chart: list[MacdPoint | None] = field(default_factory=list)
    recommendation: Recommendation | None = None
    no_entry: NoEntry | None = None
    history: list[WindowStats] = field(default_factory=list)
    chart_data: list[float] = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _window_stats(window: list[float]) -> WindowStats:
    n = len(window)
    return WindowStats(
        prob_2x=sum(1 for x in window if x >= 2.0) / n,
        prob_5x=sum(1 for x in window if x >= 5.0) / n,
        prob_10x=sum(1 for x in window if x >= 10.0) / n,
        moving_avg=statistics.mean(window),
    )


def _bollinger(window: list[float]) -> BollingerPoint:
    sma = statistics.mean(window)
    std = statistics.stdev(window) if len(window) >= 2 else 0.0
    return BollingerPoint(
        upper=round(sma + 2 * std, 4),
        middle=round(sma, 4),
        lower=round(sma - 2 * std, 4),
    )


def _ema_series(values: list[float], period: int) -> list[float | None]:
    """Full EMA series; None until period-1 data are available (initial = SMA)."""
    k = 2.0 / (period + 1)
    result: list[float | None] = []
    ema: float | None = None
    for i, v in enumerate(values):
        if i < period - 1:
            result.append(None)
        elif i == period - 1:
            ema = sum(values[:period]) / period
            result.append(ema)
        else:
            assert ema is not None
            ema = v * k + ema * (1 - k)
            result.append(ema)
    return result


def _rsi_series(values: list[float], period: int) -> list[float | None]:
    """Wilder-smoothed RSI series. None for the first `period` indices."""
    if len(values) < period + 1:
        return [None] * len(values)

    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains  = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result: list[float | None] = [None] * (period + 1)
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100 - 100 / (1 + rs), 4))

    return result


def _macd_series(
    values: list[float],
    fast: int,
    slow: int,
    signal: int,
) -> list[MacdPoint | None]:
    """MACD = EMA(fast) - EMA(slow), Signal = EMA(MACD, signal)."""
    fast_ema = _ema_series(values, fast)
    slow_ema = _ema_series(values, slow)

    macd_line: list[float | None] = [
        round(f - s, 4) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema)
    ]

    valid_macd = [v for v in macd_line if v is not None]
    signal_ema_values = _ema_series(valid_macd, signal) if valid_macd else []

    signal_line: list[float | None] = []
    sig_idx = 0
    for m in macd_line:
        if m is None:
            signal_line.append(None)
        else:
            signal_line.append(signal_ema_values[sig_idx] if sig_idx < len(signal_ema_values) else None)
            sig_idx += 1

    result: list[MacdPoint | None] = []
    for m, s in zip(macd_line, signal_line):
        if m is None:
            result.append(None)
        else:
            hist = round(m - s, 4) if s is not None else None
            result.append(MacdPoint(macd=m, signal=s, histogram=hist))
    return result


def _recommendation(window: list[float]) -> Recommendation:
    """Compute floor/target lines and volatility regime for the given window."""
    mean = statistics.mean(window)
    std  = statistics.stdev(window) if len(window) >= 2 else 0.0
    cv_raw = (std / mean) if mean > 0 else 0.0
    cv = round(cv_raw, 4)

    if cv_raw < REGIME_THRESHOLDS[0]:
        regime = "low"
    elif cv_raw < REGIME_THRESHOLDS[1]:
        regime = "medium"
    else:
        regime = "high"

    floor_line = round(max(FLOOR_LINE_MIN, statistics.median(window) - _ALPHA[regime] * std), 4)
    target_line = round(max(floor_line, mean + _BETA[regime] * std), 4)
    return Recommendation(volatility_cv=cv, regime=regime, floor_line=floor_line, target_line=target_line)


def _no_entry(multipliers: list[float], window: list[float]) -> NoEntry:
    """Evaluate the three no-entry conditions against all available data."""
    reasons: list[str] = []

    # ① Low-multiplier streak
    streak = 0
    for v in reversed(multipliers):
        if v <= NO_ENTRY_LOW_MULTIPLIER_THRESHOLD:
            streak += 1
        else:
            break
    if streak >= NO_ENTRY_LOW_CONSECUTIVE_LIMIT:
        reasons.append("low_consecutive")

    # ② Post-spike cooldown: last value was a spike AND next few avg low
    if len(multipliers) >= NO_ENTRY_POST_SPIKE_WINDOW + 1:
        spike_candidate = multipliers[-(NO_ENTRY_POST_SPIKE_WINDOW + 1)]
        post_values = multipliers[-NO_ENTRY_POST_SPIKE_WINDOW:]
        if (spike_candidate >= NO_ENTRY_POST_SPIKE_THRESHOLD
                and statistics.mean(post_values) < NO_ENTRY_POST_SPIKE_AVG_MAX):
            reasons.append("post_spike")

    # ③ Low volatility (CV)
    mean = statistics.mean(window)
    std  = statistics.stdev(window) if len(window) >= 2 else 0.0
    cv   = round(std / mean, 4) if mean > 0 else 0.0
    if cv < NO_ENTRY_LOW_VOLATILITY_CV:
        reasons.append("low_volatility")

    # ④ Low expected value (median)
    median_val = round(statistics.median(window), 4)
    if median_val < NO_ENTRY_LOW_EV_MEDIAN_THRESHOLD:
        reasons.append("low_expected_value")

    return NoEntry(
        active=len(reasons) > 0,
        reasons=reasons,
        low_consecutive_count=streak,
        volatility_cv=cv,
        median_value=median_val,
    )


# ── Main calculation ─────────────────────────────────────────────────────────

def calculate(
    multipliers: list[float],
    rsi_period: int = RSI_PERIOD_DEFAULT,
    macd_fast: int = MACD_FAST_DEFAULT,
    macd_slow: int = MACD_SLOW_DEFAULT,
    macd_signal: int = MACD_SIGNAL_DEFAULT,
) -> AnalysisResult:
    """Compute analysis from the full list of multipliers (oldest first).

    RSI and MACD are computed on the moving-average series (one value per
    18-round sliding window), not on raw multipliers, because individual
    crash-game rounds are independent random events.
    """
    total = len(multipliers)

    if total < WINDOW:
        return AnalysisResult(ready=False, total_rounds=total)

    recent = multipliers[-WINDOW:]

    # Sliding-window history: one entry per round from the 18th onward, capped at MAX_HISTORY
    history_count = min(total - WINDOW + 1, MAX_HISTORY)
    history_start = total - WINDOW - (history_count - 1)
    history = [
        _window_stats(multipliers[i : i + WINDOW])
        for i in range(history_start, history_start + history_count)
    ]

    chart_data = multipliers[-MAX_HISTORY:]
    chart_len = len(chart_data)

    # Bollinger Bands (parallel to chart_data, based on raw multipliers)
    bollinger_chart: list[BollingerPoint | None] = []
    for j in range(chart_len):
        idx = total - chart_len + j
        if idx >= WINDOW - 1:
            bb_window = multipliers[idx - WINDOW + 1 : idx + 1]
            bollinger_chart.append(_bollinger(bb_window))
        else:
            bollinger_chart.append(None)
    bollinger_current = _bollinger(recent)

    # ATR (raw multipliers)
    true_ranges = [abs(multipliers[i] - multipliers[i - 1]) for i in range(1, total)]
    atr = round(statistics.mean(true_ranges[-WINDOW:]), 4) if len(true_ranges) >= WINDOW else None

    # Moving-average series: the mean multiplier of each 18-round window
    moving_avg_series = [ws.moving_avg for ws in history]

    # RSI applied to moving-average series (parallel to history)
    rsi_chart = _rsi_series(moving_avg_series, rsi_period)
    # MACD applied to moving-average series (parallel to history)
    macd_chart = _macd_series(moving_avg_series, macd_fast, macd_slow, macd_signal)

    return AnalysisResult(
        ready=True,
        total_rounds=total,
        prob_2x=history[-1].prob_2x,
        prob_5x=history[-1].prob_5x,
        prob_10x=history[-1].prob_10x,
        moving_avg=history[-1].moving_avg,
        median=statistics.median(recent),
        std_dev=statistics.stdev(recent),
        max=max(multipliers),
        min=min(multipliers),
        atr=atr,
        bollinger_current=bollinger_current,
        bollinger_chart=bollinger_chart,
        rsi_period=rsi_period,
        rsi_chart=rsi_chart,
        macd_fast=macd_fast,
        macd_slow=macd_slow,
        macd_signal_period=macd_signal,
        macd_chart=macd_chart,
        recommendation=_recommendation(recent),
        no_entry=_no_entry(multipliers, recent),
        history=history,
        chart_data=chart_data,
    )
