from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.redis import get_redis
from deps import get_current_user
from routers.analysis import CACHE_KEY as ANALYSIS_CACHE_KEY

router = APIRouter(prefix="/api/v1/rounds", tags=["rounds"])

READY_THRESHOLD = 18
MAX_LIMIT = 72
MAX_POST_VALUES = 1000

MULTIPLIER_MIN = 1.01
MULTIPLIER_MAX = 501.00


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
    inserted_rows_result = await db.execute(
        text(
            "INSERT INTO rounds (multiplier) "
            "SELECT v FROM unnest(CAST(:vals AS numeric[])) AS v "
            "RETURNING id, multiplier, recorded_at"
        ),
        {"vals": body.values},
    )
    await db.commit()

    inserted_rounds = []
    for r in inserted_rows_result:
        inserted_rounds.append(
            {
                "id": r.id,
                "multiplier": float(r.multiplier),
                "recorded_at": r.recorded_at.isoformat(),
            }
        )

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

    await db.execute(text("TRUNCATE rounds"))
    await db.commit()

    try:
        keys = await redis.keys(f"{ANALYSIS_CACHE_KEY}:*")
        if keys:
            await redis.delete(*keys)
        await redis.publish("analysis:trigger", "update")
    except RedisError:
        pass

    return {"deleted": deleted}
