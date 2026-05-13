from __future__ import annotations

import statistics
from dataclasses import dataclass, field

WINDOW = 18
MAX_HISTORY = 72

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


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
    rsi_current: float | None = None
    rsi_chart: list[float | None] = field(default_factory=list)
    macd_chart: list[MacdPoint | None] = field(default_factory=list)
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
    """Full EMA series, None until period-1 data are available (initial = SMA)."""
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


def _rsi_series(values: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    """Wilder-smoothed RSI series. None for the first `period` indices."""
    if len(values) < period + 1:
        return [None] * len(values)

    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains  = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    # Initial averages (simple mean of first `period` changes)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result: list[float | None] = [None] * (period + 1)  # first period+1 values undefined
    # Wilder smoothing from index period onward
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
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> list[MacdPoint | None]:
    """MACD = EMA(fast) - EMA(slow), Signal = EMA(MACD, signal)."""
    fast_ema = _ema_series(values, fast)
    slow_ema = _ema_series(values, slow)

    # MACD line (None where either EMA is None)
    macd_line: list[float | None] = [
        round(f - s, 4) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema)
    ]

    # Signal line: EMA of the MACD values (only where MACD is defined)
    valid_macd = [v for v in macd_line if v is not None]
    signal_ema_values = _ema_series(valid_macd, signal)

    # Map signal back to original indices
    signal_line: list[float | None] = []
    sig_idx = 0
    for m in macd_line:
        if m is None:
            signal_line.append(None)
        else:
            signal_line.append(signal_ema_values[sig_idx])
            sig_idx += 1

    result: list[MacdPoint | None] = []
    for m, s in zip(macd_line, signal_line):
        if m is None:
            result.append(None)
        else:
            hist = round(m - s, 4) if s is not None else None
            result.append(MacdPoint(macd=m, signal=s, histogram=hist))
    return result


# ── Main calculation ─────────────────────────────────────────────────────────

def calculate(multipliers: list[float]) -> AnalysisResult:
    """Compute analysis from the full list of multipliers (oldest first)."""
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

    # Bollinger Bands (parallel to chart_data)
    bollinger_chart: list[BollingerPoint | None] = []
    for j in range(chart_len):
        idx = total - chart_len + j
        if idx >= WINDOW - 1:
            bb_window = multipliers[idx - WINDOW + 1 : idx + 1]
            bollinger_chart.append(_bollinger(bb_window))
        else:
            bollinger_chart.append(None)
    bollinger_current = _bollinger(recent)

    # ATR
    true_ranges = [abs(multipliers[i] - multipliers[i - 1]) for i in range(1, total)]
    atr = round(statistics.mean(true_ranges[-WINDOW:]), 4) if len(true_ranges) >= WINDOW else None

    # RSI (trim to chart_data window)
    rsi_full = _rsi_series(multipliers)
    rsi_chart = rsi_full[-chart_len:]
    rsi_current = next((v for v in reversed(rsi_full) if v is not None), None)

    # MACD (trim to chart_data window)
    macd_full = _macd_series(multipliers)
    macd_chart = macd_full[-chart_len:]

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
        rsi_current=rsi_current,
        rsi_chart=rsi_chart,
        macd_chart=macd_chart,
        history=history,
        chart_data=chart_data,
    )
