from datetime import UTC, datetime, timedelta

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
from ml.evaluation import build_eval_payload
from routers.analysis import CACHE_KEY as ANALYSIS_CACHE_KEY

router = APIRouter(prefix="/api/v1/rounds", tags=["rounds"])

READY_THRESHOLD = 18
MAX_LIMIT = 72
MAX_POST_VALUES = 200

MULTIPLIER_MIN = 1.01
MULTIPLIER_MAX = 501.00
DUPLICATE_GUARD_SECONDS = 90


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
        text("SELECT multiplier FROM rounds ORDER BY recorded_at DESC, id DESC LIMIT :limit"),
        {"limit": WINDOW},
    )
    history = [float(row.multiplier) for row in recent_rows]
    history.reverse()

    latest_row = await db.execute(
        text("SELECT multiplier, recorded_at FROM rounds ORDER BY recorded_at DESC, id DESC LIMIT 1")
    )
    latest = latest_row.fetchone()
    last_value = float(latest.multiplier) if latest else None
    last_recorded_at = latest.recorded_at if latest else None

    inserted_rounds = []
    skipped_duplicates = 0
    for value in body.values:
        # OCRの同一ラウンド再送対策: 直近値と同じ倍率が短時間で来た場合は重複として無視する
        if (
            last_value is not None
            and value == last_value
            and last_recorded_at is not None
            and (datetime.now(UTC) - last_recorded_at) <= timedelta(seconds=DUPLICATE_GUARD_SECONDS)
        ):
            skipped_duplicates += 1
            continue

        inserted_row = await db.execute(
            text("INSERT INTO rounds (multiplier) VALUES (:value) RETURNING id, multiplier, recorded_at"),
            {"value": value},
        )
        row = inserted_row.fetchone()
        last_value = float(row.multiplier)
        last_recorded_at = row.recorded_at
        inserted_rounds.append(
            {
                "id": row.id,
                "multiplier": float(row.multiplier),
                "recorded_at": row.recorded_at.isoformat(),
            }
        )

        eval_payload = build_eval_payload(
            round_id=int(row.id),
            actual_multiplier=float(row.multiplier),
            history=history,
        )
        if eval_payload is not None:
            await db.execute(
                text(
                    "INSERT INTO prediction_evals "
                    "(round_id, predicted_band, actual_band, actual_multiplier, verdict) "
                    "VALUES (:round_id, :predicted_band, :actual_band, :actual_multiplier, :verdict) "
                    "ON CONFLICT (round_id) DO NOTHING"
                ),
                eval_payload,
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
        "inserted": len(inserted_rounds),
        "skipped_duplicates": skipped_duplicates,
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
        text("SELECT id, multiplier, recorded_at FROM rounds ORDER BY recorded_at DESC, id DESC LIMIT :limit"),
        {"limit": limit},
    )
    rounds = [
        {"id": r.id, "multiplier": float(r.multiplier), "recorded_at": r.recorded_at.isoformat()}
        for r in rows
    ]
    total_row = await db.execute(text("SELECT COUNT(*) FROM rounds"))
    total = total_row.scalar()
    return {"rounds": rounds, "total": total}


@router.get("/probability-trends")
async def get_probability_trends(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    params = {"days": days}

    hourly_rows = await db.execute(
        text(
            """
            SELECT
                date_trunc('hour', recorded_at) AS bucket,
                COUNT(*) AS total,
                AVG(CASE WHEN multiplier <= 1.2 THEN 1.0 ELSE 0.0 END) AS prob_1_2x,
                AVG(CASE WHEN multiplier <= 2.0 THEN 1.0 ELSE 0.0 END) AS prob_2_0x,
                AVG(CASE WHEN multiplier <= 2.0 THEN 1.0 ELSE 0.0 END) AS prob_blue,
                AVG(CASE WHEN multiplier > 2.0 AND multiplier <= 5.0 THEN 1.0 ELSE 0.0 END) AS prob_green,
                AVG(CASE WHEN multiplier > 5.0 AND multiplier <= 10.0 THEN 1.0 ELSE 0.0 END) AS prob_yellow,
                AVG(CASE WHEN multiplier > 10.0 THEN 1.0 ELSE 0.0 END) AS prob_red
            FROM rounds
            WHERE recorded_at >= NOW() - (:days * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY 1 ASC
            """
        ),
        params,
    )

    daily_rows = await db.execute(
        text(
            """
            SELECT
                date_trunc('day', recorded_at) AS bucket,
                COUNT(*) AS total,
                AVG(CASE WHEN multiplier <= 1.2 THEN 1.0 ELSE 0.0 END) AS prob_1_2x,
                AVG(CASE WHEN multiplier <= 2.0 THEN 1.0 ELSE 0.0 END) AS prob_2_0x,
                AVG(CASE WHEN multiplier <= 2.0 THEN 1.0 ELSE 0.0 END) AS prob_blue,
                AVG(CASE WHEN multiplier > 2.0 AND multiplier <= 5.0 THEN 1.0 ELSE 0.0 END) AS prob_green,
                AVG(CASE WHEN multiplier > 5.0 AND multiplier <= 10.0 THEN 1.0 ELSE 0.0 END) AS prob_yellow,
                AVG(CASE WHEN multiplier > 10.0 THEN 1.0 ELSE 0.0 END) AS prob_red
            FROM rounds
            WHERE recorded_at >= NOW() - (:days * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY 1 ASC
            """
        ),
        params,
    )

    hourly_stats_rows = await db.execute(
        text(
            """
            SELECT
                EXTRACT(HOUR FROM recorded_at AT TIME ZONE 'Asia/Tokyo')::int AS hour,
                COUNT(*) AS total,
                AVG(CASE WHEN multiplier <= 1.2 THEN 1.0 ELSE 0.0 END) AS prob_1_2x,
                AVG(CASE WHEN multiplier <= 2.0 THEN 1.0 ELSE 0.0 END) AS prob_2_0x,
                AVG(CASE WHEN multiplier > 2.0 AND multiplier <= 5.0 THEN 1.0 ELSE 0.0 END) AS prob_green,
                AVG(CASE WHEN multiplier > 5.0 AND multiplier <= 10.0 THEN 1.0 ELSE 0.0 END) AS prob_yellow,
                AVG(CASE WHEN multiplier > 10.0 THEN 1.0 ELSE 0.0 END) AS prob_red
            FROM rounds
            WHERE recorded_at >= NOW() - (:days * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY 1 ASC
            """
        ),
        params,
    )

    hourly = [
        {
            "bucket": r.bucket.isoformat(),
            "total": int(r.total),
            "prob_1_2x": float(r.prob_1_2x or 0.0),
            "prob_2_0x": float(r.prob_2_0x or 0.0),
            "prob_blue": float(r.prob_blue or 0.0),
            "prob_green": float(r.prob_green or 0.0),
            "prob_yellow": float(r.prob_yellow or 0.0),
            "prob_red": float(r.prob_red or 0.0),
        }
        for r in hourly_rows
    ]

    daily = [
        {
            "bucket": r.bucket.isoformat(),
            "total": int(r.total),
            "prob_1_2x": float(r.prob_1_2x or 0.0),
            "prob_2_0x": float(r.prob_2_0x or 0.0),
            "prob_blue": float(r.prob_blue or 0.0),
            "prob_green": float(r.prob_green or 0.0),
            "prob_yellow": float(r.prob_yellow or 0.0),
            "prob_red": float(r.prob_red or 0.0),
        }
        for r in daily_rows
    ]

    hourly_stats_map = {
        int(r.hour): {
            "hour": int(r.hour),
            "total": int(r.total),
            "prob_1_2x": float(r.prob_1_2x or 0.0),
            "prob_2_0x": float(r.prob_2_0x or 0.0),
            "prob_green": float(r.prob_green or 0.0),
            "prob_yellow": float(r.prob_yellow or 0.0),
            "prob_red": float(r.prob_red or 0.0),
        }
        for r in hourly_stats_rows
    }
    hourly_stats = [
        hourly_stats_map.get(
            h,
            {
                "hour": h,
                "total": 0,
                "prob_1_2x": 0.0,
                "prob_2_0x": 0.0,
                "prob_green": 0.0,
                "prob_yellow": 0.0,
                "prob_red": 0.0,
            },
        )
        for h in range(24)
    ]

    return {
        "timezone": "UTC",
        "hourly_timezone": "UTC",
        "daily_timezone": "UTC",
        "hourly_stats_timezone": "Asia/Tokyo",
        "days": days,
        "hourly": hourly,
        "daily": daily,
        "hourly_stats": hourly_stats,
    }


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
