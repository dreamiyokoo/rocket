import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.calculator import WINDOW, calculate
from core.database import get_db
from core.redis import get_redis

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

CACHE_KEY = "analysis:current"
CACHE_TTL = 60


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
        "chart_data": [
            {"index": i + 1, "value": v} for i, v in enumerate(result.chart_data)
        ],
        "analyzed_at": analyzed_at,
    }


@router.get("")
async def get_analysis(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    cached = await redis.get(CACHE_KEY)
    if cached:
        return json.loads(cached)

    rows = await db.execute(
        text("SELECT multiplier FROM rounds ORDER BY recorded_at ASC")
    )
    multipliers = [float(r.multiplier) for r in rows]

    result = calculate(multipliers)
    analyzed_at = datetime.now(timezone.utc).isoformat()

    response = _build_response(result, analyzed_at)
    await redis.setex(CACHE_KEY, CACHE_TTL, json.dumps(response))
    return response
