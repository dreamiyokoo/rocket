"""ML モデルの読み込みとリアルタイム予測"""
from __future__ import annotations

import os
import pickle
import logging
from dataclasses import dataclass

from ml.features import WINDOW, FEATURE_COLS, make_feature_vector

logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

_multiclass_model = None
_binary_model = None
_models_loaded = False


def _load_models() -> None:
    global _multiclass_model, _binary_model, _models_loaded
    if _models_loaded:
        return
    mc_path = os.path.join(_MODELS_DIR, "multiclass.pkl")
    bi_path = os.path.join(_MODELS_DIR, "binary.pkl")
    try:
        with open(mc_path, "rb") as f:
            _multiclass_model = pickle.load(f)
        with open(bi_path, "rb") as f:
            _binary_model = pickle.load(f)
        _models_loaded = True
        logger.info("ML models loaded successfully")
    except FileNotFoundError as e:
        logger.warning("ML model files not found: %s", e)
    except Exception as e:
        logger.warning("Failed to load ML models: %s", e)


@dataclass
class MLPrediction:
    available: bool
    prob_low: float | None = None    # Low  (< 1.5x) 確率
    prob_mid: float | None = None    # Mid  (1.5〜10x) 確率
    prob_high: float | None = None   # High (≥ 10x) 確率
    prob_low_binary: float | None = None  # 2値分類の Low 確率
    skip_recommended: bool = False   # Low確率 > 60% → スキップ推奨
    entry_boost: bool = False        # High確率 > 30% → エントリー強化推奨


def predict(multipliers: list[float]) -> MLPrediction:
    """直近の倍率リストから ML 予測を返す。

    モデル未ロードまたはデータ不足の場合は available=False を返す。
    """
    _load_models()

    if not _models_loaded or len(multipliers) < WINDOW:
        return MLPrediction(available=False)

    window = multipliers[-WINDOW:]
    features = make_feature_vector(window)

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mc_proba = _multiclass_model.predict_proba([features])[0]
            bi_proba = _binary_model.predict_proba([features])[0][1]
    except Exception as e:
        logger.warning("ML prediction failed: %s", e)
        return MLPrediction(available=False)

    prob_low = round(float(mc_proba[0]), 4)
    prob_mid = round(float(mc_proba[1]), 4)
    prob_high = round(float(mc_proba[2]), 4)
    prob_low_binary = round(float(bi_proba), 4)

    return MLPrediction(
        available=True,
        prob_low=prob_low,
        prob_mid=prob_mid,
        prob_high=prob_high,
        prob_low_binary=prob_low_binary,
        skip_recommended=prob_low_binary > 0.60,
        entry_boost=prob_high > 0.30,
    )
