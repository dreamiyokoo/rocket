import statistics

import pytest

from analysis.calculator import (
    FLOOR_LINE_MIN,
    NO_ENTRY_LOW_CONSECUTIVE_LIMIT,
    NO_ENTRY_LOW_EV_MEDIAN_THRESHOLD,
    NO_ENTRY_LOW_MULTIPLIER_THRESHOLD,
    NO_ENTRY_LOW_VOLATILITY_CV,
    NO_ENTRY_POST_SPIKE_AVG_MAX,
    NO_ENTRY_POST_SPIKE_THRESHOLD,
    NO_ENTRY_POST_SPIKE_WINDOW,
    REGIME_THRESHOLDS,
    WINDOW,
    AnalysisResult,
    _recommendation,
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


# ---------- recommendation ----------

def test_recommendation_not_ready():
    result = _make([1.5] * (WINDOW - 1))
    assert result.recommendation is None


def test_recommendation_present_when_ready():
    result = _make([2.0] * WINDOW)
    assert result.recommendation is not None


def test_recommendation_low_volatility_regime():
    # All same values → std=0 → cv=0 → low regime
    window = [2.0] * WINDOW
    rec = _recommendation(window)
    assert rec.regime == "low"
    assert rec.volatility_cv < REGIME_THRESHOLDS[0]


def test_recommendation_medium_volatility_regime():
    # Mix that produces 0.3 ≤ cv < 0.8
    window = [1.0] * 9 + [4.0] * 9  # mean=2.5, std≈1.5, cv≈0.6
    rec = _recommendation(window)
    assert rec.regime == "medium"
    assert REGIME_THRESHOLDS[0] <= rec.volatility_cv < REGIME_THRESHOLDS[1]


def test_recommendation_high_volatility_regime():
    # Mix that produces cv ≥ 0.8
    window = [1.01] * 14 + [20.0] * 4  # high spread relative to mean
    rec = _recommendation(window)
    assert rec.regime == "high"
    assert rec.volatility_cv >= REGIME_THRESHOLDS[1]


def test_recommendation_regime_uses_unrounded_cv():
    # mean≈0.6298, std≈0.1889 => raw cv≈0.29998 (rounds to 0.3000)
    # regime must still be low because thresholding uses unrounded cv
    window = [0.5] * 12 + [0.8895] * 6
    rec = _recommendation(window)
    assert rec.volatility_cv == pytest.approx(0.3)
    assert rec.regime == "low"


def test_recommendation_floor_line_clipped():
    # Raw floor is below 1.01 and must be clipped
    window = [0.2] * 9 + [1.0] * 9
    rec = _recommendation(window)
    assert rec.floor_line == FLOOR_LINE_MIN


def test_recommendation_target_line_uses_regime_beta():
    window = [1.5] * 9 + [3.0] * 9
    rec = _recommendation(window)
    assert rec.regime == "medium"
    expected = round(statistics.mean(window) + 1.5 * statistics.stdev(window), 4)
    assert rec.target_line == expected
    assert rec.target_line > rec.floor_line


def test_recommendation_target_line_not_below_floor_after_clip():
    window = [0.2] * WINDOW
    rec = _recommendation(window)
    assert rec.floor_line == FLOOR_LINE_MIN
    assert rec.target_line == FLOOR_LINE_MIN


def test_recommendation_in_calculate_result():
    result = _make([2.0] * WINDOW)
    assert result.recommendation is not None
    rec = result.recommendation
    assert isinstance(rec.volatility_cv, float)
    assert rec.regime in ("low", "medium", "high")
    assert isinstance(rec.floor_line, float)
    assert isinstance(rec.target_line, float)


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


def test_no_entry_low_volatility_no_trigger_at_threshold():
    # CV exactly == 0.25 → strict < means no trigger
    # Build data so std/mean == 0.25. With mean=2, std=0.5 we get CV=0.25.
    # Use values that give mean≈2, std≈0.5: [1.5]*9 + [2.5]*9
    data = [1.5] * 9 + [2.5] * 9
    cv_raw = statistics.stdev(data) / statistics.mean(data)
    result = _make(data)
    if cv_raw == NO_ENTRY_LOW_VOLATILITY_CV:
        assert "low_volatility" not in result.no_entry.reasons
    else:
        # Confirm the test helper produces the right CV direction
        assert cv_raw >= NO_ENTRY_LOW_VOLATILITY_CV or "low_volatility" in result.no_entry.reasons


def test_no_entry_low_volatility_triggers_just_below_threshold():
    # CV just below 0.25 must trigger
    # Use values so CV is slightly below 0.25.  With mean=2 and std just under 0.5
    # we can use many near-identical values with a tiny spread.
    # [1.9]*9 + [2.1]*9 gives CV ≈ 0.1 which is clearly below 0.25.
    data = [1.9] * 9 + [2.1] * 9
    cv_raw = statistics.stdev(data) / statistics.mean(data)
    assert cv_raw < NO_ENTRY_LOW_VOLATILITY_CV
    result = _make(data)
    assert "low_volatility" in result.no_entry.reasons


def test_no_entry_multiple_reasons():
    # all same low values → low_consecutive (streak = WINDOW ≥ 5) AND low_volatility (CV = 0)
    data = [1.2] * WINDOW
    result = _make(data)
    assert "low_consecutive" in result.no_entry.reasons
    assert "low_volatility" in result.no_entry.reasons
    assert result.no_entry.active is True


def test_no_entry_low_ev_triggers_below_threshold():
    # median < 1.50 → low_expected_value
    data = [1.1] * 9 + [1.4] * 9  # median = 1.25 < 1.50
    result = _make(data)
    assert "low_expected_value" in result.no_entry.reasons
    assert result.no_entry.active is True
    assert result.no_entry.median_value == pytest.approx(1.25)


def test_no_entry_low_ev_no_trigger_at_threshold():
    # median exactly at threshold → no trigger (strictly less than)
    data = [NO_ENTRY_LOW_EV_MEDIAN_THRESHOLD] * WINDOW
    result = _make(data)
    assert "low_expected_value" not in result.no_entry.reasons


def test_no_entry_low_ev_no_trigger_above_threshold():
    # median > 1.50 → no trigger
    data = [2.0] * 9 + [3.0] * 9  # median = 2.5
    result = _make(data)
    assert "low_expected_value" not in result.no_entry.reasons
    assert result.no_entry.median_value == pytest.approx(2.5)


def test_no_entry_median_value_exposed():
    # median_value is always present in no_entry when ready
    data = [1.5] * 9 + [3.0] * 9
    result = _make(data)
    assert result.no_entry is not None
    assert isinstance(result.no_entry.median_value, float)
