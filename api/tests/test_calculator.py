import statistics

import pytest

from analysis.calculator import (
    NO_ENTRY_LOW_CONSECUTIVE_LIMIT,
    NO_ENTRY_LOW_MULTIPLIER_THRESHOLD,
    NO_ENTRY_LOW_VOLATILITY_CV,
    NO_ENTRY_POST_SPIKE_AVG_MAX,
    NO_ENTRY_POST_SPIKE_THRESHOLD,
    NO_ENTRY_POST_SPIKE_WINDOW,
    WINDOW,
    AnalysisResult,
    calculate,
)


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


# ---------- no_entry ----------

def test_no_entry_none_when_not_ready():
    result = _make([1.5] * (WINDOW - 1))
    assert result.no_entry is None


def test_no_entry_inactive_when_no_conditions():
    # High variance, no streak at end, no spike pattern
    data = [1.5] * 9 + [3.0] * 9
    result = _make(data)
    assert result.no_entry is not None
    assert result.no_entry.active is False
    assert result.no_entry.reasons == []


def test_no_entry_low_consecutive_triggers_at_limit():
    streak_len = NO_ENTRY_LOW_CONSECUTIVE_LIMIT
    data = [2.0] * (WINDOW - streak_len) + [1.1] * streak_len
    result = _make(data)
    assert "low_consecutive" in result.no_entry.reasons
    assert result.no_entry.active is True
    assert result.no_entry.low_consecutive_count == streak_len


def test_no_entry_low_consecutive_no_trigger_below_limit():
    streak_len = NO_ENTRY_LOW_CONSECUTIVE_LIMIT - 1
    data = [2.0] * (WINDOW - streak_len) + [1.1] * streak_len
    result = _make(data)
    assert "low_consecutive" not in result.no_entry.reasons
    assert result.no_entry.low_consecutive_count == streak_len


def test_no_entry_low_consecutive_boundary_value():
    # Value exactly at threshold counts as low
    data = [2.0] * (WINDOW - NO_ENTRY_LOW_CONSECUTIVE_LIMIT) + [NO_ENTRY_LOW_MULTIPLIER_THRESHOLD] * NO_ENTRY_LOW_CONSECUTIVE_LIMIT
    result = _make(data)
    assert "low_consecutive" in result.no_entry.reasons


def test_no_entry_post_spike_triggers():
    # spike at [-4] ≥ 10.0, post 3 values average < 1.3; streak = 3 < 5 so no low_consecutive
    data = [2.0] * (WINDOW - NO_ENTRY_POST_SPIKE_WINDOW - 1) + [NO_ENTRY_POST_SPIKE_THRESHOLD] + [1.1] * NO_ENTRY_POST_SPIKE_WINDOW
    assert len(data) == WINDOW
    result = _make(data)
    assert "post_spike" in result.no_entry.reasons
    assert result.no_entry.active is True


def test_no_entry_post_spike_no_trigger_spike_below_threshold():
    below = NO_ENTRY_POST_SPIKE_THRESHOLD - 0.1
    data = [2.0] * (WINDOW - NO_ENTRY_POST_SPIKE_WINDOW - 1) + [below] + [1.1] * NO_ENTRY_POST_SPIKE_WINDOW
    result = _make(data)
    assert "post_spike" not in result.no_entry.reasons


def test_no_entry_post_spike_no_trigger_post_avg_at_ceiling():
    # post average exactly at ceiling (not strictly less) → no trigger
    data = [2.0] * (WINDOW - NO_ENTRY_POST_SPIKE_WINDOW - 1) + [NO_ENTRY_POST_SPIKE_THRESHOLD] + [NO_ENTRY_POST_SPIKE_AVG_MAX] * NO_ENTRY_POST_SPIKE_WINDOW
    result = _make(data)
    assert "post_spike" not in result.no_entry.reasons


def test_no_entry_low_volatility_triggers():
    # identical values → CV = 0 < 0.25
    data = [2.0] * WINDOW
    result = _make(data)
    assert "low_volatility" in result.no_entry.reasons
    assert result.no_entry.volatility_cv == pytest.approx(0.0)


def test_no_entry_low_volatility_no_trigger_high_cv():
    # [1.5]*9 + [3.0]*9 → CV ≈ 0.33 > 0.25
    data = [1.5] * 9 + [3.0] * 9
    result = _make(data)
    assert "low_volatility" not in result.no_entry.reasons
    assert result.no_entry.volatility_cv >= NO_ENTRY_LOW_VOLATILITY_CV


def test_no_entry_multiple_reasons():
    # all same low values → low_consecutive (streak = WINDOW ≥ 5) AND low_volatility (CV = 0)
    data = [1.2] * WINDOW
    result = _make(data)
    assert "low_consecutive" in result.no_entry.reasons
    assert "low_volatility" in result.no_entry.reasons
    assert result.no_entry.active is True
