"""
Rounds endpoint tests.

Dependencies (get_db, get_current_user) are overridden with in-memory mocks so no
real database or Redis instance is required.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-purposes-only-xx")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.database import get_db  # noqa: E402
from core.redis import get_redis  # noqa: E402
from deps import get_current_user  # noqa: E402
from main import app  # noqa: E402

_CURRENT_USER = {"id": 1, "username": "admin", "jti": "test-jti", "exp": 9999999999}


def _make_db(scalar_values: list) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns scalar values in sequence."""
    mock = AsyncMock()
    mock.commit = AsyncMock()
    side_effects = []
    for val in scalar_values:
        result = MagicMock()
        result.scalar.return_value = val
        side_effects.append(result)
    mock.execute = AsyncMock(side_effect=side_effects)
    return mock


def _make_post_rounds_db(inserted_values: list[float], total: int) -> AsyncMock:
    """Return a mock AsyncSession for post_rounds with sequential inserts."""
    mock = AsyncMock()
    mock.commit = AsyncMock()

    recent_result = MagicMock()
    recent_result.__iter__ = lambda self: iter([])

    side_effects = [recent_result]
    for index, value in enumerate(inserted_values, start=1):
        insert_result = MagicMock()
        row = MagicMock()
        row.id = index
        row.multiplier = value
        row.recorded_at = MagicMock()
        row.recorded_at.isoformat.return_value = f"2026-01-01T00:00:{index:02d}"
        insert_result.fetchone.return_value = row
        side_effects.append(insert_result)

    total_result = MagicMock()
    total_result.scalar.return_value = total
    side_effects.append(total_result)

    mock.execute = AsyncMock(side_effect=side_effects)
    return mock


def _make_db_with_rows(rows: list, count: int) -> AsyncMock:
    """Return a mock AsyncSession for get_rounds (rows then scalar count)."""
    mock = AsyncMock()
    rows_result = MagicMock()
    rows_result.__iter__ = lambda self: iter(rows)
    count_result = MagicMock()
    count_result.scalar.return_value = count
    mock.execute = AsyncMock(side_effect=[rows_result, count_result])
    return mock


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides are reset after every test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/rounds
# ---------------------------------------------------------------------------


class TestPostRounds:
    def test_post_rounds_success(self):
        mock_redis = AsyncMock()
        app.dependency_overrides[get_db] = lambda: _make_post_rounds_db([1.5, 2.0, 3.0], 5)
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [1.5, 2.0, 3.0]},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["inserted"] == 3
        assert data["total"] == 5
        assert data["ready"] is False  # 5 < 18

    def test_post_rounds_ready_when_total_exceeds_threshold(self):
        mock_redis = AsyncMock()
        app.dependency_overrides[get_db] = lambda: _make_post_rounds_db([1.5], 20)
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [1.5]},
        )

        assert response.status_code == 201
        assert response.json()["ready"] is True  # 20 >= 18

    def test_post_rounds_no_auth_returns_401(self):
        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [1.5, 2.0]},
        )
        assert response.status_code == 401

    def test_post_rounds_empty_values_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": []},
        )
        assert response.status_code == 422

    def test_post_rounds_zero_value_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [0.0, 1.5]},
        )
        assert response.status_code == 422

    def test_post_rounds_negative_value_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [-1.0, 1.5]},
        )
        assert response.status_code == 422

    def test_post_rounds_below_min_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [1.00]},
        )
        assert response.status_code == 422

    def test_post_rounds_above_max_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [501.01]},
        )
        assert response.status_code == 422

    def test_post_rounds_too_many_values_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER

        response = TestClient(app).post(
            "/api/v1/rounds",
            json={"values": [1.5] * 1001},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/rounds
# ---------------------------------------------------------------------------


class TestGetRounds:
    def _make_row(self, id_: int, multiplier: float, ts: str) -> MagicMock:
        row = MagicMock()
        row.id = id_
        row.multiplier = multiplier
        row.recorded_at = MagicMock()
        row.recorded_at.isoformat.return_value = ts
        return row

    def test_get_rounds_success(self):
        row = self._make_row(1, 1.5, "2026-01-01T00:00:00")
        app.dependency_overrides[get_db] = lambda: _make_db_with_rows([row], count=1)

        response = TestClient(app).get("/api/v1/rounds")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["rounds"]) == 1
        assert data["rounds"][0]["multiplier"] == 1.5

    def test_get_rounds_empty(self):
        app.dependency_overrides[get_db] = lambda: _make_db_with_rows([], count=0)

        response = TestClient(app).get("/api/v1/rounds")

        assert response.status_code == 200
        assert response.json() == {"rounds": [], "total": 0}

    def test_get_rounds_custom_limit(self):
        app.dependency_overrides[get_db] = lambda: _make_db_with_rows([], count=0)

        response = TestClient(app).get("/api/v1/rounds?limit=10")

        assert response.status_code == 200

    def test_get_rounds_limit_exceeds_max_returns_422(self):
        response = TestClient(app).get("/api/v1/rounds?limit=100")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/rounds
# ---------------------------------------------------------------------------


class TestDeleteRounds:
    def test_delete_rounds_success(self):
        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 10
        mock_db.execute = AsyncMock(side_effect=[count_result, MagicMock()])
        mock_db.commit = AsyncMock()
        mock_redis = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: _CURRENT_USER
        app.dependency_overrides[get_redis] = lambda: mock_redis

        response = TestClient(app).delete("/api/v1/rounds")

        assert response.status_code == 200
        assert response.json()["deleted"] == 10

    def test_delete_rounds_no_auth_returns_401(self):
        response = TestClient(app).delete("/api/v1/rounds")
        assert response.status_code == 401
