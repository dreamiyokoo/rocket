from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from deps import get_current_user
from ml.evaluation import build_eval_payload

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])

VALID_BANDS = {"blue", "green", "yellow", "red"}
VALID_VERDICTS = {"hit", "miss"}

class EvalPostRequest(BaseModel):
    round_id: int
    predicted_band: str
    actual_band: str
    actual_multiplier: float
    verdict: str
    evaluated_at: datetime | None = None

    @field_validator("predicted_band", "actual_band")
    @classmethod
    def validate_band(cls, v: str) -> str:
        if v not in VALID_BANDS:
            raise ValueError(f"band must be one of {VALID_BANDS}")
        return v

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        if v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}")
        return v

    @field_validator("actual_multiplier")
    @classmethod
    def validate_multiplier(cls, v: float) -> float:
        if not (1.01 <= v <= 501.00):
            raise ValueError("actual_multiplier must be between 1.01 and 501.00")
        return round(v, 2)


@router.post("", status_code=201)
async def post_eval(
    body: EvalPostRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    evaluated_at = body.evaluated_at or datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO prediction_evals "
            "(round_id, predicted_band, actual_band, actual_multiplier, verdict, evaluated_at) "
            "VALUES (:round_id, :predicted_band, :actual_band, :actual_multiplier, :verdict, :evaluated_at) "
            "ON CONFLICT (round_id) DO NOTHING"
        ),
        {
            "round_id": body.round_id,
            "predicted_band": body.predicted_band,
            "actual_band": body.actual_band,
            "actual_multiplier": body.actual_multiplier,
            "verdict": body.verdict,
            "evaluated_at": evaluated_at,
        },
    )
    await db.commit()
    return {"ok": True}


@router.get("/stats")
async def get_eval_stats(
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    rows_result = await db.execute(
        text(
            "SELECT predicted_band, actual_band, verdict, COUNT(*) AS cnt "
            "FROM prediction_evals "
            "GROUP BY predicted_band, actual_band, verdict "
            "ORDER BY predicted_band, verdict"
        )
    )
    rows = rows_result.fetchall()

    # 全体の的中率
    total_row_result = await db.execute(
        text("SELECT COUNT(*) AS total, SUM(CASE WHEN verdict='hit' THEN 1 ELSE 0 END) AS hits FROM prediction_evals")
    )
    t = total_row_result.fetchone()
    total = t.total or 0
    hits = t.hits or 0

    # 直近 N 件
    recent_rows_result = await db.execute(
        text(
            "SELECT round_id, predicted_band, actual_band, actual_multiplier, verdict, evaluated_at "
            "FROM prediction_evals ORDER BY evaluated_at DESC LIMIT :lim"
        ),
        {"lim": limit},
    )
    recent_rows = recent_rows_result.fetchall()

    # レスポンス整形中はDB接続を保持しない
    await db.rollback()

    stats = [
        {"predicted_band": r.predicted_band, "actual_band": r.actual_band,
         "verdict": r.verdict, "count": r.cnt}
        for r in rows
    ]
    recent = [
        {
            "round_id": r.round_id,
            "predicted_band": r.predicted_band,
            "actual_band": r.actual_band,
            "actual_multiplier": float(r.actual_multiplier),
            "verdict": r.verdict,
            "evaluated_at": r.evaluated_at.isoformat() if hasattr(r.evaluated_at, "isoformat") else str(r.evaluated_at),
        }
        for r in recent_rows
    ]

    return {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total, 4) if total > 0 else None,
        "by_band": stats,
        "recent": recent,
    }


@router.delete("", status_code=200)
async def delete_evals(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """prediction_evals のみをリセットする（rounds は保持）。"""
    count_row = await db.execute(text("SELECT COUNT(*) FROM prediction_evals"))
    deleted = count_row.scalar()
    await db.execute(text("TRUNCATE prediction_evals"))
    await db.commit()
    return {"deleted": deleted}


@router.post("/rebuild", status_code=200)
async def rebuild_evals(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """現行モデルで prediction_evals を全件再計算する。"""
    rounds_rows = await db.execute(
        text("SELECT id, multiplier FROM rounds ORDER BY recorded_at ASC, id ASC")
    )
    rounds = [{"id": int(r.id), "multiplier": float(r.multiplier)} for r in rounds_rows]

    await db.execute(text("TRUNCATE prediction_evals"))

    history: list[float] = []
    payloads: list[dict] = []
    for row in rounds:
        payload = build_eval_payload(
            round_id=row["id"],
            actual_multiplier=row["multiplier"],
            history=history,
        )
        if payload is not None:
            payloads.append(payload)

        history.append(row["multiplier"])
        history = history[-WINDOW:]

    if payloads:
        await db.execute(
            text(
                "INSERT INTO prediction_evals "
                "(round_id, predicted_band, actual_band, actual_multiplier, verdict) "
                "VALUES (:round_id, :predicted_band, :actual_band, :actual_multiplier, :verdict)"
            ),
            payloads,
        )

    await db.commit()
    return {
        "rounds": len(rounds),
        "rebuilt": len(payloads),
        "skipped_head": min(len(rounds), WINDOW),
    }
