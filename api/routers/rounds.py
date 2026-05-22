from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.redis import get_redis
from deps import get_current_user
from ml.features import WINDOW
from ml.predictor import predict
from routers.analysis import CACHE_KEY as ANALYSIS_CACHE_KEY

router = APIRouter(prefix="/api/v1/rounds", tags=["rounds"])

READY_THRESHOLD = 18
MAX_LIMIT = 72
MAX_POST_VALUES = 200

MULTIPLIER_MIN = 1.01
MULTIPLIER_MAX = 501.00


def _band_from_multiplier(value: float) -> str:
    if value > 10.0:
        return "red"
    if value > 5.0:
        return "yellow"
    if value > 2.0:
        return "green"
    return "blue"


def _predicted_band(history: list[float]) -> str | None:
    prediction = predict(history)
    if not prediction.available:
        return None

    probs = {
        "blue": prediction.prob_blue or 0.0,
        "green": prediction.prob_green or 0.0,
        "yellow": prediction.prob_yellow or 0.0,
        "red": prediction.prob_red or 0.0,
    }
    return max(probs, key=probs.get)


class RoundsPostRequest(BaseModel):
    values: list[float]

    @field_validator("values")
    @classmethod
    def validate_values(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("values must not be empty")
        if len(v) > MAX_POST_VALUES:
            raise ValueError(f"values must contain at most {MAX_POST_VALUES} items")
        # 小数2桁に丸める
        v = [round(x, 2) for x in v]
        invalid = [x for x in v if not (MULTIPLIER_MIN <= x <= MULTIPLIER_MAX)]
        if invalid:
            raise ValueError(
                f"each value must be between {MULTIPLIER_MIN} and {MULTIPLIER_MAX}, got: {invalid}"
            )
        return v


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_rounds(
    body: RoundsPostRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    recent_rows = await db.execute(
        text("SELECT multiplier FROM rounds ORDER BY recorded_at DESC LIMIT :limit"),
        {"limit": WINDOW},
    )
    history = [float(row.multiplier) for row in recent_rows]
    history.reverse()

    inserted_rounds = []
    for value in body.values:
        predicted_band = _predicted_band(history)
        inserted_row = await db.execute(
            text("INSERT INTO rounds (multiplier) VALUES (:value) RETURNING id, multiplier, recorded_at"),
            {"value": value},
        )
        row = inserted_row.fetchone()
        inserted_rounds.append(
            {
                "id": row.id,
                "multiplier": float(row.multiplier),
                "recorded_at": row.recorded_at.isoformat(),
            }
        )

        if predicted_band is not None:
            actual_multiplier = float(row.multiplier)
            actual_band = _band_from_multiplier(actual_multiplier)
            verdict = "hit" if predicted_band == actual_band else "miss"
            await db.execute(
                text(
                    "INSERT INTO prediction_evals "
                    "(round_id, predicted_band, actual_band, actual_multiplier, verdict) "
                    "VALUES (:round_id, :predicted_band, :actual_band, :actual_multiplier, :verdict) "
                    "ON CONFLICT (round_id) DO NOTHING"
                ),
                {
                    "round_id": row.id,
                    "predicted_band": predicted_band,
                    "actual_band": actual_band,
                    "actual_multiplier": actual_multiplier,
                    "verdict": verdict,
                },
            )

        history.append(float(row.multiplier))
        history = history[-WINDOW:]

    await db.commit()

    total_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    total = total_row.scalar()

    try:
        keys = await redis.keys(f"{ANALYSIS_CACHE_KEY}:*")
        if keys:
            await redis.delete(*keys)
        await redis.publish("analysis:trigger", "update")
    except RedisError:
        pass

    return {
        "inserted": len(body.values),
        "total": total,
        "ready": total >= READY_THRESHOLD,
        "inserted_rounds": inserted_rounds,
    }


@router.get("")
async def get_rounds(
    limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        text("SELECT id, multiplier, recorded_at FROM rounds ORDER BY recorded_at DESC LIMIT :limit"),
        {"limit": limit},
    )
    rounds = [
        {"id": r.id, "multiplier": float(r.multiplier), "recorded_at": r.recorded_at.isoformat()}
        for r in rows
    ]
    total_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    total = total_row.scalar()
    return {"rounds": rounds, "total": total}


@router.delete("")
async def delete_rounds(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    count_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    deleted = count_row.scalar()

    await db.execute(text("TRUNCATE prediction_evals, rounds RESTART IDENTITY"))
    await db.commit()

    try:
        keys = await redis.keys(f"{ANALYSIS_CACHE_KEY}:*")
        if keys:
            await redis.delete(*keys)
        await redis.publish("analysis:trigger", "update")
    except RedisError:
        pass

    return {"deleted": deleted}
