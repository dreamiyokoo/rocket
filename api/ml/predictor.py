"""ML モデルの読み込みとリアルタイム予測"""
from __future__ import annotations

import os
import pickle
import logging
from dataclasses import dataclass

from ml.features import WINDOW, make_feature_vector

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
    prob_blue: float | None = None    # Blue   (≤ 2.0x) 確率
    prob_green: float | None = None   # Green  (2.01〜5.0x) 確率
    prob_yellow: float | None = None  # Yellow (5.01〜10.0x) 確率
    prob_red: float | None = None     # Red    (> 10.0x) 確率
    prob_blue_binary: float | None = None  # 2値分類の Blue 確率
    skip_recommended: bool = False    # Blue確率 > 60% → スキップ推奨
    entry_boost: bool = False         # Red確率 > 30% → エントリー強化推奨


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

    prob_blue   = round(float(mc_proba[0]), 4)
    prob_green  = round(float(mc_proba[1]), 4)
    prob_yellow = round(float(mc_proba[2]), 4)
    prob_red    = round(float(mc_proba[3]), 4)
    prob_blue_binary = round(float(bi_proba), 4)

    return MLPrediction(
        available=True,
        prob_blue=prob_blue,
        prob_green=prob_green,
        prob_yellow=prob_yellow,
        prob_red=prob_red,
        prob_blue_binary=prob_blue_binary,
        skip_recommended=prob_blue_binary > 0.60,
        entry_boost=prob_red > 0.30,
    )
