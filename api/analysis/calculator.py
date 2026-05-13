from __future__ import annotations

import statistics
from dataclasses import dataclass, field

WINDOW = 18
MAX_HISTORY = 72


@dataclass
class WindowStats:
    prob_2x: float
    prob_5x: float
    prob_10x: float
    moving_avg: float


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
    history: list[WindowStats] = field(default_factory=list)
    chart_data: list[float] = field(default_factory=list)


def _window_stats(window: list[float]) -> WindowStats:
    n = len(window)
    return WindowStats(
        prob_2x=sum(1 for x in window if x >= 2.0) / n,
        prob_5x=sum(1 for x in window if x >= 5.0) / n,
        prob_10x=sum(1 for x in window if x >= 10.0) / n,
        moving_avg=statistics.mean(window),
    )


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

    return AnalysisResult(
        ready=True,
        total_rounds=total,
        prob_2x=history[-1].prob_2x,
        prob_5x=history[-1].prob_5x,
        prob_10x=history[-1].prob_10x,
        moving_avg=statistics.mean(recent),
        median=statistics.median(recent),
        std_dev=statistics.stdev(recent),
        max=max(multipliers),
        min=min(multipliers),
        history=history,
        chart_data=chart_data,
    )
