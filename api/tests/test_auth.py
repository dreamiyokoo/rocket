"""
Authentication endpoint tests.

Dependencies (get_db, get_redis) are overridden with in-memory mocks so no
real database or Redis instance is required.
"""

import os

# Set required env vars BEFORE any project modules are imported so that
# pydantic-settings (Settings()) can instantiate without error.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-purposes-only-xx")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.database import get_db  # noqa: E402
from core.redis import get_redis  # noqa: E402
from core.security import create_access_token, hash_password  # noqa: E402
from main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_row_result(data: dict | None) -> MagicMock:
    """Return a mock that mimics sqlalchemy Row.mappings().first() -> data."""
    result = MagicMock()
    result.mappings.return_value.first.return_value = data
    return result


def _make_db(data: dict | None) -> AsyncMock:
    """Return an AsyncMock session whose execute() returns *data* as the first row."""
    mock = AsyncMock()
    mock.execute = AsyncMock(return_value=_make_row_result(data))
    return mock


def _make_redis(*, get_value: str | None = None) -> AsyncMock:
    """Return an AsyncMock Redis client."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=get_value)
    mock.setex = AsyncMock(return_value=True)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides are reset after every test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_success(self):
        hashed = hash_password("correct-password")
        app.dependency_overrides[get_db] = lambda: _make_db(
            {"id": 1, "username": "admin", "password_hash": hashed}
        )
        app.dependency_overrides[get_redis] = lambda: _make_redis()

        response = TestClient(app).post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password_returns_401(self):
        hashed = hash_password("correct-password")
        app.dependency_overrides[get_db] = lambda: _make_db(
            {"id": 1, "username": "admin", "password_hash": hashed}
        )
        app.dependency_overrides[get_redis] = lambda: _make_redis()

        response = TestClient(app).post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_login_unknown_user_returns_401(self):
        app.dependency_overrides[get_db] = lambda: _make_db(None)
        app.dependency_overrides[get_redis] = lambda: _make_redis()

        response = TestClient(app).post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "anything"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"


# ---------------------------------------------------------------------------
# /me tests
# ---------------------------------------------------------------------------


class TestMe:
    def test_me_returns_current_user(self):
        app.dependency_overrides[get_db] = lambda: _make_db(
            {"id": 1, "username": "admin"}
        )
        app.dependency_overrides[get_redis] = lambda: _make_redis(get_value=None)

        token = create_access_token(1)
        response = TestClient(app).get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {"id": 1, "username": "admin"}

    def test_me_invalid_token_returns_401(self):
        response = TestClient(app).get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert response.status_code == 401

    def test_me_no_token_returns_401(self):
        response = TestClient(app).get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_me_revoked_token_returns_401(self):
        app.dependency_overrides[get_db] = lambda: _make_db(
            {"id": 1, "username": "admin"}
        )
        # Simulate the jti being in the Redis denylist
        app.dependency_overrides[get_redis] = lambda: _make_redis(get_value="1")

        token = create_access_token(1)
        response = TestClient(app).get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Token has been revoked"


# ---------------------------------------------------------------------------
# Logout tests
# ---------------------------------------------------------------------------


class TestLogout:
    def test_logout_success(self):
        mock_redis = _make_redis(get_value=None)
        app.dependency_overrides[get_db] = lambda: _make_db(
            {"id": 1, "username": "admin"}
        )
        app.dependency_overrides[get_redis] = lambda: mock_redis

        token = create_access_token(1)
        response = TestClient(app).post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 204
        # The jti should have been stored in the denylist
        mock_redis.setex.assert_awaited_once()

    def test_logout_without_token_returns_401(self):
        response = TestClient(app).post("/api/v1/auth/logout")
        assert response.status_code == 401
