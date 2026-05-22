import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from core.redis import get_redis
from deps import get_current_user

router = APIRouter(prefix="/api/v1/capture", tags=["capture"])

PREVIEW_KEY = "capture:latest_preview"
PREVIEW_TTL_SECONDS = 60 * 10


class CapturePreviewPayload(BaseModel):
    captured_at: str
    bar_image: str
    mask_image: str
    raw_text: str
    values: list[float]
    scale: int


@router.post("/preview", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_capture_preview(
    body: CapturePreviewPayload,
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    try:
        await redis.setex(PREVIEW_KEY, PREVIEW_TTL_SECONDS, body.model_dump_json())
    except RedisError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Preview cache unavailable") from exc


@router.get("/preview")
async def get_capture_preview(
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    try:
        payload = await redis.get(PREVIEW_KEY)
    except RedisError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Preview cache unavailable") from exc

    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")

    return json.loads(payload)