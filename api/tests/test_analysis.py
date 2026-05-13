import json
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-purposes-only-xx")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis.exceptions import RedisError  # noqa: E402

from core.database import get_db  # noqa: E402
from core.redis import get_redis  # noqa: E402
from main import app  # noqa: E402

WINDOW = 18


def _make_rows(values: list[float]) -> MagicMock:
    rows = [MagicMock(multiplier=v) for v in values]
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter(rows))
    return result


def _make_db(values: list[float]) -> AsyncMock:
    mock = AsyncMock()
    mock.execute = AsyncMock(return_value=_make_rows(values))
    return mock


def _make_redis(cached: str | None = None) -> AsyncMock:
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=cached)
    mock.setex = AsyncMock()
    return mock


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestGetAnalysis:
    def test_no_auth_required(self):
        app.dependency_overrides[get_db] = lambda: _make_db([1.5] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        response = TestClient(app).get("/api/v1/analysis")
        assert response.status_code == 200

    def test_ready_false_when_below_threshold(self):
        app.dependency_overrides[get_db] = lambda: _make_db([1.5] * (WINDOW - 1))
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ready"] is False
        assert data["total_rounds"] == WINDOW - 1
        assert data["window"] == WINDOW
        assert "chart_data" not in data
        assert "prob_2x" not in data

    def test_ready_true_returns_all_fields(self):
        values = [2.0] * WINDOW
        app.dependency_overrides[get_db] = lambda: _make_db(values)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ready"] is True
        assert data["total_rounds"] == WINDOW
        assert "prob_2x" in data
        assert "history" in data["prob_2x"]
        assert "current" in data["prob_2x"]
        assert "analyzed_at" in data

    def test_chart_data_max_72(self):
        values = [1.5] * 100
        app.dependency_overrides[get_db] = lambda: _make_db(values)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert len(data["chart_data"]) == 72

    def test_chart_data_index_starts_at_1(self):
        values = [1.5] * WINDOW
        app.dependency_overrides[get_db] = lambda: _make_db(values)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["chart_data"][0]["index"] == 1

    def test_cache_hit_skips_db(self):
        cached_response = json.dumps({"ready": False, "total_rounds": 5, "window": WINDOW})
        mock_db = _make_db([])
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_redis] = lambda: _make_redis(cached=cached_response)
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ready"] is False
        mock_db.execute.assert_not_called()

    def test_cache_miss_stores_result(self):
        mock_redis = _make_redis(cached=None)
        app.dependency_overrides[get_db] = lambda: _make_db([1.5] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: mock_redis
        TestClient(app).get("/api/v1/analysis")
        mock_redis.setex.assert_awaited_once()

    def test_redis_down_falls_back_to_db(self):
        mock_db = _make_db([1.5] * WINDOW)
        broken_redis = AsyncMock()
        broken_redis.get = AsyncMock(side_effect=RedisError("Redis connection refused"))
        broken_redis.setex = AsyncMock(side_effect=RedisError("Redis connection refused"))
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_redis] = lambda: broken_redis
        response = TestClient(app).get("/api/v1/analysis")
        assert response.status_code == 200
        assert response.json()["ready"] is True
        broken_redis.get.assert_awaited_once()
        mock_db.execute.assert_awaited_once()
