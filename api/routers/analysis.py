import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.calculator import (
    MACD_FAST_DEFAULT,
    MACD_SIGNAL_DEFAULT,
    MACD_SLOW_DEFAULT,
    MAX_HISTORY,
    RSI_PERIOD_DEFAULT,
    WINDOW,
    calculate,
)
from core.database import get_db
from core.redis import get_redis
from ml.predictor import predict as ml_predict

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

CACHE_KEY = "analysis:current"
CACHE_TTL = 60


def _cache_key(rsi: int, mf: int, ms: int, msig: int) -> str:
    return f"{CACHE_KEY}:rsi{rsi}:macd{mf}-{ms}-{msig}"


def _build_response(result, analyzed_at: str) -> dict:
    if not result.ready:
        return {
            "ready": False,
            "total_rounds": result.total_rounds,
            "window": WINDOW,
        }
    return {
        "ready": True,
        "total_rounds": result.total_rounds,
        "window": WINDOW,
        "prob_2x": {
            "current": result.prob_2x,
            "history": [h.prob_2x for h in result.history],
        },
        "prob_5x": {
            "current": result.prob_5x,
            "history": [h.prob_5x for h in result.history],
        },
        "prob_10x": {
            "current": result.prob_10x,
            "history": [h.prob_10x for h in result.history],
        },
        "prob_1_2x": {
            "current": result.prob_1_2x,
            "history": [h.prob_1_2x for h in result.history],
        },
        "moving_avg": result.moving_avg,
        "median": result.median,
        "std_dev": result.std_dev,
        "max": result.max,
        "min": result.min,
        "atr": result.atr,
        "rsi": {
            "period": result.rsi_period,
            "current": next((v for v in reversed(result.rsi_chart) if v is not None), None),
            "chart": result.rsi_chart,
        },
        "macd": {
            "fast": result.macd_fast,
            "slow": result.macd_slow,
            "signal_period": result.macd_signal_period,
            "chart": [
                {"macd": p.macd, "signal": p.signal, "histogram": p.histogram}
                if p else None
                for p in result.macd_chart
            ],
        },
        "bollinger_bands": {
            "current": {
                "upper": result.bollinger_current.upper,
                "middle": result.bollinger_current.middle,
                "lower": result.bollinger_current.lower,
            } if result.bollinger_current else None,
            "chart": [
                {"upper": b.upper, "middle": b.middle, "lower": b.lower} if b else None
                for b in result.bollinger_chart
            ],
        },
        "chart_data": [
            {"index": i + 1, "value": v} for i, v in enumerate(result.chart_data)
        ],
        "no_entry": {
            "active": result.no_entry.active,
            "reasons": result.no_entry.reasons,
            "low_consecutive_count": result.no_entry.low_consecutive_count,
            "volatility_cv": result.no_entry.volatility_cv,
            "median_value": result.no_entry.median_value,
        } if result.no_entry else None,
        "recommendation": {
            "volatility_cv": result.recommendation.volatility_cv,
            "regime": result.recommendation.regime,
            "floor_line": result.recommendation.floor_line,
            "target_line": result.recommendation.target_line,
            "flow_state": (
                "hot" if (result.prob_2x or 0) >= 0.60
                else "warm" if (result.prob_2x or 0) >= 0.50
                else "cold"
            ),
            "stake_scale": (
                1.5 if (result.prob_2x or 0) >= 0.60
                else 1.0 if (result.prob_2x or 0) >= 0.40
                else 0.5
            ),
            "entry_ok": (
                not (result.no_entry.active if result.no_entry else False)
                and (result.prob_2x or 0) >= 0.50
            ),
        } if result.recommendation else None,
        "analyzed_at": analyzed_at,
    }


@router.get("")
async def get_analysis(
    rsi_period: int = Query(default=RSI_PERIOD_DEFAULT, ge=2, le=50, alias="rsi_period"),
    macd_fast: int = Query(default=MACD_FAST_DEFAULT, ge=2, le=50, alias="macd_fast"),
    macd_slow: int = Query(default=MACD_SLOW_DEFAULT, ge=3, le=100, alias="macd_slow"),
    macd_signal: int = Query(default=MACD_SIGNAL_DEFAULT, ge=2, le=30, alias="macd_signal"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    key = _cache_key(rsi_period, macd_fast, macd_slow, macd_signal)
    try:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)
    except (RedisError, json.JSONDecodeError):
        pass

    # Fetch total count and recent rows separately for performance.
    # Only the last MAX_HISTORY + WINDOW rows are needed for all computations.
    _FETCH_LIMIT = MAX_HISTORY + WINDOW
    count_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    total_count = count_row.scalar() or 0

    rows = await db.execute(
        text(
            "SELECT multiplier FROM ("
            "  SELECT multiplier, recorded_at FROM rounds"
            "  ORDER BY recorded_at DESC LIMIT :lim"
            ") sub ORDER BY recorded_at ASC"
        ),
        {"lim": _FETCH_LIMIT},
    )
    multipliers = [float(r.multiplier) for r in rows]

    result = calculate(multipliers, rsi_period, macd_fast, macd_slow, macd_signal, total_count=total_count)
    ml_result = ml_predict(multipliers)
    analyzed_at = datetime.now(timezone.utc).isoformat()

    response = _build_response(result, analyzed_at)
    if ml_result.available:
        response["ml_prediction"] = {
            "available": True,
            "prob_blue":   ml_result.prob_blue,
            "prob_green":  ml_result.prob_green,
            "prob_yellow": ml_result.prob_yellow,
            "prob_red":    ml_result.prob_red,
            "prob_blue_binary": ml_result.prob_blue_binary,
            "skip_recommended": ml_result.skip_recommended,
            "entry_boost": ml_result.entry_boost,
        }
        # ML シグナルで entry_ok を上書き
        # skip_recommended（Blue確率 > 60%）→ 強制的に待機
        # entry_boost（Red確率 > 30%）→ 強制的にエントリー推奨
        if response.get("recommendation"):
            if ml_result.skip_recommended:
                response["recommendation"]["entry_ok"] = False
            elif ml_result.entry_boost:
                response["recommendation"]["entry_ok"] = True
    else:
        response["ml_prediction"] = {"available": False}
    try:
        await redis.setex(key, CACHE_TTL, json.dumps(response))
    except RedisError:
        pass
    return response
