"""
WebSocket endpoint tests.

``get_redis`` is called directly inside the endpoint (not via ``Depends``), so
we patch it at the module level with ``unittest.mock.patch``.  No real Redis
instance is required.
"""

import logging
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-purposes-only-xx")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from contextlib import contextmanager  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from fastapi import WebSocketDisconnect  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis.exceptions import RedisError  # noqa: E402

from main import app  # noqa: E402


def _make_redis(messages: list, cleanup_error: Exception | None = None) -> MagicMock:
    """Return a mock Redis whose pubsub yields *messages* then stops."""

    async def _listen():
        for msg in messages:
            yield msg

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen.return_value = _listen()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = (
        AsyncMock(side_effect=cleanup_error) if cleanup_error else AsyncMock()
    )

    redis = MagicMock()
    redis.pubsub.return_value = pubsub
    redis.aclose = AsyncMock()
    return redis


@contextmanager
def _patch_redis(mock_redis):
    with patch("routers.ws.get_redis", return_value=mock_redis):
        yield


class TestWebSocketEndpoint:
    def test_sends_update_on_message(self):
        """Normal path: a Redis 'message' triggers an 'update' WS frame."""
        mock_redis = _make_redis([{"type": "message", "data": b"update"}])
        with _patch_redis(mock_redis):
            with TestClient(app).websocket_connect("/api/v1/ws") as ws:
                data = ws.receive_text()
                assert data == "update"

    def test_non_message_type_is_ignored(self):
        """'subscribe' confirmation frames must not be forwarded to the client."""
        mock_redis = _make_redis([
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": b"update"},
        ])
        with _patch_redis(mock_redis):
            with TestClient(app).websocket_connect("/api/v1/ws") as ws:
                data = ws.receive_text()
                assert data == "update"

    def test_handles_websocket_disconnect(self):
        """WebSocketDisconnect raised during listen() is swallowed gracefully."""

        async def _raise_disconnect():
            raise WebSocketDisconnect()
            yield  # type: ignore[misc]  # keeps this an async generator

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen.return_value = _raise_disconnect()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()

        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        redis.aclose = AsyncMock()

        with _patch_redis(redis):
            # The endpoint handles the disconnect and closes; no exception leaks out.
            with TestClient(app).websocket_connect("/api/v1/ws"):
                pass

    def test_handles_redis_error(self):
        """RedisError raised during listen() is swallowed gracefully."""

        async def _raise_redis_error():
            raise RedisError("connection lost")
            yield  # type: ignore[misc]  # keeps this an async generator

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.listen.return_value = _raise_redis_error()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()

        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        redis.aclose = AsyncMock()

        with _patch_redis(redis):
            with TestClient(app).websocket_connect("/api/v1/ws"):
                pass

    def test_cleanup_redis_error_is_logged(self, caplog):
        """RedisError during cleanup is logged as a warning, not silently dropped."""
        mock_redis = _make_redis(
            messages=[],
            cleanup_error=RedisError("cleanup failed"),
        )
        with caplog.at_level(logging.WARNING, logger="routers.ws"):
            with _patch_redis(mock_redis):
                with TestClient(app).websocket_connect("/api/v1/ws"):
                    pass

        assert any("cleanup" in r.message.lower() for r in caplog.records)
