import statistics

import pytest

from analysis.calculator import WINDOW, AnalysisResult, calculate


def _make(values: list[float]) -> AnalysisResult:
    return calculate(values)


# ---------- ready: false ----------

def test_not_ready_when_below_threshold():
    result = _make([1.5] * (WINDOW - 1))
    assert result.ready is False
    assert result.prob_2x is None
    assert result.history == []
    assert result.chart_data == []


def test_not_ready_empty():
    result = _make([])
    assert result.ready is False
    assert result.total_rounds == 0


# ---------- ready: true — basic ----------

def test_ready_at_exactly_threshold():
    data = [2.0] * WINDOW
    result = _make(data)
    assert result.ready is True
    assert result.total_rounds == WINDOW


def test_prob_all_above_2x():
    data = [2.0] * WINDOW
    result = _make(data)
    assert result.prob_2x == pytest.approx(1.0)
    assert result.prob_5x == pytest.approx(0.0)
    assert result.prob_10x == pytest.approx(0.0)


def test_prob_all_below_2x():
    data = [1.0] * WINDOW
    result = _make(data)
    assert result.prob_2x == pytest.approx(0.0)
    assert result.prob_5x == pytest.approx(0.0)
    assert result.prob_10x == pytest.approx(0.0)


def test_prob_mixed():
    # 9 values >= 2x, 4 values >= 5x, 1 value >= 10x
    data = [1.0] * 9 + [2.0] * 5 + [5.0] * 3 + [10.0] * 1
    assert len(data) == WINDOW
    result = _make(data)
    assert result.prob_2x == pytest.approx(9 / 18)
    assert result.prob_5x == pytest.approx(4 / 18)
    assert result.prob_10x == pytest.approx(1 / 18)


# ---------- statistics ----------

def test_moving_avg_and_median_use_recent_window():
    old = [100.0] * 10   # old data should not affect recent-window stats
    recent = [2.0] * WINDOW
    result = _make(old + recent)
    assert result.moving_avg == pytest.approx(statistics.mean(recent))
    assert result.median == pytest.approx(statistics.median(recent))


def test_std_dev_uses_recent_window():
    old = [100.0] * 5
    recent = [float(i) for i in range(1, WINDOW + 1)]
    result = _make(old + recent)
    assert result.std_dev == pytest.approx(statistics.stdev(recent))


def test_max_min_use_all_data():
    data = [1.5] * WINDOW + [50.0, 0.1]
    result = _make(data)
    assert result.max == pytest.approx(50.0)
    assert result.min == pytest.approx(0.1)


# ---------- history ----------

def test_history_length_at_threshold():
    result = _make([1.5] * WINDOW)
    assert len(result.history) == 1


def test_history_length_grows():
    result = _make([1.5] * (WINDOW + 5))
    assert len(result.history) == 6


def test_history_capped_at_72():
    result = _make([1.5] * (WINDOW + 100))
    assert len(result.history) == 72


def test_chart_data_capped_at_72():
    result = _make([1.5] * 100)
    assert len(result.chart_data) == 72


def test_chart_data_fewer_than_72():
    result = _make([1.5] * WINDOW)
    assert len(result.chart_data) == WINDOW
