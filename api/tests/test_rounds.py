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
        app.dependency_overrides[get_db] = lambda: _make_db([None, 5])
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
        app.dependency_overrides[get_db] = lambda: _make_db([None, 20])
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
# GET /api/v1/rounds/probability-trends
# ---------------------------------------------------------------------------


class TestGetProbabilityTrends:
    def _make_bucket_row(
        self,
        bucket_iso: str,
        total: int,
        prob_1_2x: float,
        prob_2_0x: float,
        prob_blue: float,
        prob_green: float,
        prob_yellow: float,
        prob_red: float,
    ) -> MagicMock:
        row = MagicMock()
        row.bucket = MagicMock()
        row.bucket.isoformat.return_value = bucket_iso
        row.total = total
        row.prob_1_2x = prob_1_2x
        row.prob_2_0x = prob_2_0x
        row.prob_blue = prob_blue
        row.prob_green = prob_green
        row.prob_yellow = prob_yellow
        row.prob_red = prob_red
        return row

    def _make_hourly_stats_row(
        self,
        hour: int,
        total: int,
        prob_1_2x: float,
        prob_2_0x: float,
        prob_green: float,
        prob_yellow: float,
        prob_red: float,
    ) -> MagicMock:
        row = MagicMock()
        row.hour = hour
        row.total = total
        row.prob_1_2x = prob_1_2x
        row.prob_2_0x = prob_2_0x
        row.prob_green = prob_green
        row.prob_yellow = prob_yellow
        row.prob_red = prob_red
        return row

    def _rows_result(self, rows: list[MagicMock]) -> MagicMock:
        result = MagicMock()
        result.__iter__ = lambda self: iter(rows)
        return result

    def test_get_probability_trends_success_with_24h_fill(self):
        hourly_rows = [
            self._make_bucket_row(
                "2026-01-01T10:00:00+00:00",
                10,
                0.4,
                0.8,
                0.8,
                0.1,
                0.05,
                0.05,
            )
        ]
        daily_rows = [
            self._make_bucket_row(
                "2026-01-01T00:00:00+00:00",
                20,
                0.5,
                0.9,
                0.9,
                0.05,
                0.03,
                0.02,
            )
        ]
        hourly_stats_rows = [
            self._make_hourly_stats_row(1, 5, 0.2, 0.5, 0.2, 0.2, 0.1),
            self._make_hourly_stats_row(23, 2, 0.1, 0.3, 0.3, 0.2, 0.2),
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                self._rows_result(hourly_rows),
                self._rows_result(daily_rows),
                self._rows_result(hourly_stats_rows),
            ]
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        response = TestClient(app).get("/api/v1/rounds/probability-trends?days=14")

        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 14
        assert data["timezone"] == "UTC"
        assert data["hourly_timezone"] == "UTC"
        assert data["daily_timezone"] == "UTC"
        assert data["hourly_stats_timezone"] == "Asia/Tokyo"

        assert len(data["hourly"]) == 1
        assert len(data["daily"]) == 1
        assert len(data["hourly_stats"]) == 24
        assert data["hourly_stats"][0] == {
            "hour": 0,
            "total": 0,
            "prob_1_2x": 0.0,
            "prob_2_0x": 0.0,
            "prob_green": 0.0,
            "prob_yellow": 0.0,
            "prob_red": 0.0,
        }
        assert data["hourly_stats"][1]["total"] == 5
        assert data["hourly_stats"][23]["total"] == 2

        assert mock_db.execute.await_count == 3
        for call in mock_db.execute.await_args_list:
            assert call.args[1] == {"days": 14}

    def test_get_probability_trends_days_validation(self):
        response = TestClient(app).get("/api/v1/rounds/probability-trends?days=0")
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
