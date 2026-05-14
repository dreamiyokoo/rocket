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
    RSI_PERIOD_DEFAULT,
    WINDOW,
    calculate,
)
from core.database import get_db
from core.redis import get_redis

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
        "recommendation": {
            "volatility_cv": result.recommendation.volatility_cv,
            "regime": result.recommendation.regime,
            "floor_line": result.recommendation.floor_line,
            "target_line": result.recommendation.target_line,
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

    rows = await db.execute(
        text("SELECT multiplier FROM rounds ORDER BY recorded_at ASC")
    )
    multipliers = [float(r.multiplier) for r in rows]

    result = calculate(multipliers, rsi_period, macd_fast, macd_slow, macd_signal)
    analyzed_at = datetime.now(timezone.utc).isoformat()

    response = _build_response(result, analyzed_at)
    try:
        await redis.setex(key, CACHE_TTL, json.dumps(response))
    except RedisError:
        pass
    return response
