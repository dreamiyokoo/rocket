"""
Capture preview endpoint tests.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-purposes-only-xx")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.redis import get_redis  # noqa: E402
from deps import get_current_user  # noqa: E402
from main import app  # noqa: E402
from routers.capture import PREVIEW_KEY  # noqa: E402

_CURRENT_USER = {"id": 1, "username": "admin", "jti": "test-jti", "exp": 9999999999}


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestCapturePreview:
    def test_upsert_capture_preview_success(self):
        mock_redis = AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).post(
            "/api/v1/capture/preview",
            json={
                "captured_at": "2026-05-22T12:00:00Z",
                "bar_image": "data:image/jpeg;base64,aaa",
                "mask_image": "data:image/png;base64,bbb",
                "raw_text": "9.97",
                "values": [9.97],
                "scale": 4,
            },
        )

        assert response.status_code == 204
        mock_redis.setex.assert_awaited_once()
        assert mock_redis.setex.await_args.args[0] == PREVIEW_KEY

    def test_get_capture_preview_success(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = (
            '{"captured_at":"2026-05-22T12:00:00Z","bar_image":"data:image/jpeg;base64,aaa",'
            '"mask_image":"data:image/png;base64,bbb","raw_text":"9.97","values":[9.97],"scale":4}'
        )
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).get("/api/v1/capture/preview")

        assert response.status_code == 200
        assert response.json()["values"] == [9.97]
        assert response.json()["raw_text"] == "9.97"

    def test_get_capture_preview_requires_auth(self):
        response = TestClient(app).get("/api/v1/capture/preview")

        assert response.status_code == 401

    def test_get_capture_preview_not_found(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).get("/api/v1/capture/preview")

        assert response.status_code == 404