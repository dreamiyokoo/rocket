from redis.asyncio import Redis

from core.config import settings

_pool: Redis | None = None


def get_redis() -> Redis:
    global _pool
    if _pool is None:
        _pool = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool
