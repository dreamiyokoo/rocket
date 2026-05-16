import json
import os
from unittest.mock import patch

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
from ml.predictor import MLPrediction  # noqa: E402

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
        assert "recommendation" not in data

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
        assert "recommendation" in data
        assert data["recommendation"]["regime"] in ("low", "medium", "high")
        assert "floor_line" in data["recommendation"]
        assert "target_line" in data["recommendation"]
        assert "analyzed_at" in data

    def test_ready_true_no_entry_shape(self):
        values = [2.0] * WINDOW
        app.dependency_overrides[get_db] = lambda: _make_db(values)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ready"] is True
        assert "no_entry" in data
        ne = data["no_entry"]
        assert isinstance(ne["active"], bool)
        assert isinstance(ne["reasons"], list)
        assert isinstance(ne["low_consecutive_count"], int)
        assert isinstance(ne["volatility_cv"], float)
        assert isinstance(ne["median_value"], float)

    def test_ready_false_no_entry_absent(self):
        app.dependency_overrides[get_db] = lambda: _make_db([1.5] * (WINDOW - 1))
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ready"] is False
        assert "no_entry" not in data

    def test_chart_data_max_300(self):
        values = [1.5] * 400
        app.dependency_overrides[get_db] = lambda: _make_db(values)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        data = TestClient(app).get("/api/v1/analysis").json()
        assert len(data["chart_data"]) == 300

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


class TestGetAnalysisMLPrediction:
    def test_ml_prediction_unavailable(self):
        """ml_predict が利用不可の場合、ml_prediction.available == False を返す"""
        app.dependency_overrides[get_db] = lambda: _make_db([2.0] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        unavailable = MLPrediction(available=False)
        with patch("routers.analysis.ml_predict", return_value=unavailable):
            data = TestClient(app).get("/api/v1/analysis").json()
        assert data["ml_prediction"] == {"available": False}

    def test_ml_prediction_available_shape(self):
        """ml_predict が利用可能の場合、全フィールドを含む ml_prediction を返す"""
        app.dependency_overrides[get_db] = lambda: _make_db([2.0] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        pred = MLPrediction(
            available=True,
            prob_blue=0.50,
            prob_green=0.25,
            prob_yellow=0.15,
            prob_red=0.10,
            prob_blue_binary=0.50,
            skip_recommended=False,
            entry_boost=False,
        )
        with patch("routers.analysis.ml_predict", return_value=pred):
            data = TestClient(app).get("/api/v1/analysis").json()
        ml = data["ml_prediction"]
        assert ml["available"] is True
        assert ml["prob_blue"] == 0.50
        assert ml["prob_green"] == 0.25
        assert ml["prob_yellow"] == 0.15
        assert ml["prob_red"] == 0.10
        assert ml["prob_blue_binary"] == 0.50
        assert ml["skip_recommended"] is False
        assert ml["entry_boost"] is False

    def test_ml_skip_recommended_overrides_entry_ok_to_false(self):
        """skip_recommended=True のとき recommendation.entry_ok が False に上書きされる"""
        app.dependency_overrides[get_db] = lambda: _make_db([2.0] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        pred = MLPrediction(
            available=True,
            prob_blue=0.70,
            prob_green=0.15,
            prob_yellow=0.10,
            prob_red=0.05,
            prob_blue_binary=0.70,
            skip_recommended=True,
            entry_boost=False,
        )
        with patch("routers.analysis.ml_predict", return_value=pred):
            data = TestClient(app).get("/api/v1/analysis").json()
        assert data["recommendation"]["entry_ok"] is False
        assert data["ml_prediction"]["skip_recommended"] is True

    def test_ml_entry_boost_overrides_entry_ok_to_true(self):
        """entry_boost=True のとき recommendation.entry_ok が True に上書きされる"""
        app.dependency_overrides[get_db] = lambda: _make_db([2.0] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        pred = MLPrediction(
            available=True,
            prob_blue=0.20,
            prob_green=0.20,
            prob_yellow=0.25,
            prob_red=0.35,
            prob_blue_binary=0.20,
            skip_recommended=False,
            entry_boost=True,
        )
        with patch("routers.analysis.ml_predict", return_value=pred):
            data = TestClient(app).get("/api/v1/analysis").json()
        assert data["recommendation"]["entry_ok"] is True
        assert data["ml_prediction"]["entry_boost"] is True

    def test_ml_skip_recommended_takes_priority_over_entry_boost(self):
        """skip_recommended と entry_boost が同時に True でも skip_recommended が優先される"""
        app.dependency_overrides[get_db] = lambda: _make_db([2.0] * WINDOW)
        app.dependency_overrides[get_redis] = lambda: _make_redis()
        pred = MLPrediction(
            available=True,
            prob_blue=0.65,
            prob_green=0.10,
            prob_yellow=0.10,
            prob_red=0.15,
            prob_blue_binary=0.65,
            skip_recommended=True,
            entry_boost=True,
        )
        with patch("routers.analysis.ml_predict", return_value=pred):
            data = TestClient(app).get("/api/v1/analysis").json()
        assert data["recommendation"]["entry_ok"] is False
