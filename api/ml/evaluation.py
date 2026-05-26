"""予測評価の共通ロジック。"""
from __future__ import annotations

from ml.features import WINDOW
from ml.predictor import decide_band, predict


def band_from_multiplier(value: float) -> str:
    if value > 10.0:
        return "red"
    if value > 5.0:
        return "yellow"
    if value > 2.0:
        return "green"
    return "blue"


def predicted_band_from_history(history: list[float]) -> str | None:
    if len(history) < WINDOW:
        return None
    prediction = predict(history)
    if not prediction.available:
        return None
    return decide_band(prediction)


def build_eval_payload(round_id: int, actual_multiplier: float, history: list[float]) -> dict | None:
    predicted_band = predicted_band_from_history(history)
    if predicted_band is None:
        return None

    actual_band = band_from_multiplier(actual_multiplier)
    return {
        "round_id": round_id,
        "predicted_band": predicted_band,
        "actual_band": actual_band,
        "actual_multiplier": actual_multiplier,
        "verdict": "hit" if predicted_band == actual_band else "miss",
    }
