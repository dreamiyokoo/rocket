from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.redis import get_redis
from deps import get_current_user

router = APIRouter(prefix="/api/v1/rounds", tags=["rounds"])

READY_THRESHOLD = 18
MAX_LIMIT = 72
MAX_POST_VALUES = 1000


class RoundsPostRequest(BaseModel):
    values: list[float]

    @field_validator("values")
    @classmethod
    def validate_values(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("values must not be empty")
        if len(v) > MAX_POST_VALUES:
            raise ValueError(f"values must contain at most {MAX_POST_VALUES} items")
        if any(x <= 0 for x in v):
            raise ValueError("each value must be greater than 0")
        return v


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_rounds(
    body: RoundsPostRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    await db.execute(
        text("INSERT INTO rounds (multiplier) SELECT unnest(:vals::numeric[])"),
        {"vals": body.values},
    )
    await db.commit()

    total_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    total = total_row.scalar()

    redis = get_redis()
    await redis.delete("analysis:latest")

    return {"inserted": len(body.values), "total": total, "ready": total >= READY_THRESHOLD}


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
    _: dict = Depends(get_current_user),
):
    count_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    deleted = count_row.scalar()

    await db.execute(text("TRUNCATE rounds"))
    await db.commit()

    redis = get_redis()
    await redis.delete("analysis:latest")

    return {"deleted": deleted}
