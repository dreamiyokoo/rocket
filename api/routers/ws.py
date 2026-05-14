from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError

from core.redis import get_redis

router = APIRouter(prefix="/api/v1", tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    redis = get_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe("analysis:trigger")
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text("update")
    except (WebSocketDisconnect, RedisError):
        pass
    finally:
        try:
            await pubsub.unsubscribe("analysis:trigger")
            await pubsub.aclose()
            await redis.aclose()
        except Exception:
            pass
