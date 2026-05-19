"""ML モデルの読み込みとリアルタイム予測"""
from __future__ import annotations

import json
import os
import pickle
import logging
from dataclasses import dataclass

from ml.features import WINDOW, make_binary_feature_vector, make_feature_vector

logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
_THRESHOLDS_PATH = os.path.join(_MODELS_DIR, "thresholds.json")

# Stage 1: <=2.0x 回避警告の閾値（最新再学習の推奨値）
BLUE_WARN_THRESHOLD = 0.387


def _load_blue_warn_threshold() -> float:
    """学習時に保存された推奨しきい値を読み込む。失敗時は既定値。"""
    try:
        with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        threshold = float(data.get("blue_warn_threshold", BLUE_WARN_THRESHOLD))
        if 0.0 <= threshold <= 1.0:
            return threshold
    except Exception:
        pass
    return BLUE_WARN_THRESHOLD

_multiclass_model = None
_binary_model = None
_last_mtime: float = 0.0
_blue_warn_threshold: float = BLUE_WARN_THRESHOLD


def _models_mtime() -> float:
    """両モデルファイルの最新更新日時を返す。ファイルがなければ 0。"""
    mc_path = os.path.join(_MODELS_DIR, "multiclass.pkl")
    bi_path = os.path.join(_MODELS_DIR, "binary.pkl")
    try:
        mtimes = [os.path.getmtime(mc_path), os.path.getmtime(bi_path)]
        if os.path.exists(_THRESHOLDS_PATH):
            mtimes.append(os.path.getmtime(_THRESHOLDS_PATH))
        return max(mtimes)
    except OSError:
        return 0.0


def _load_models() -> None:
    global _multiclass_model, _binary_model, _last_mtime, _blue_warn_threshold
    current_mtime = _models_mtime()
    if current_mtime == 0.0 or current_mtime == _last_mtime:
        return
    mc_path = os.path.join(_MODELS_DIR, "multiclass.pkl")
    bi_path = os.path.join(_MODELS_DIR, "binary.pkl")
    try:
        with open(mc_path, "rb") as f:
            _multiclass_model = pickle.load(f)
        with open(bi_path, "rb") as f:
            _binary_model = pickle.load(f)
        _blue_warn_threshold = _load_blue_warn_threshold()
        _last_mtime = current_mtime
        logger.info("ML models loaded (mtime=%.0f, blue_warn_threshold=%.3f)", current_mtime, _blue_warn_threshold)
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
    skip_recommended: bool = False    # Blue確率 >= しきい値 → スキップ推奨
    entry_boost: bool = False         # Red確率 > 30% → エントリー強化推奨


def predict(multipliers: list[float]) -> MLPrediction:
    """直近の倍率リストから ML 予測を返す。

    モデル未ロードまたはデータ不足の場合は available=False を返す。
    """
    _load_models()

    if _multiclass_model is None or _binary_model is None or len(multipliers) < WINDOW:
        return MLPrediction(available=False)

    window = multipliers[-WINDOW:]
    features_mc = make_feature_vector(window)
    features_bi = make_binary_feature_vector(window)

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mc_proba = _multiclass_model.predict_proba([features_mc])[0]
            bi_proba = _binary_model.predict_proba([features_bi])[0][1]
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
        skip_recommended=prob_blue_binary >= _blue_warn_threshold,
        entry_boost=prob_red > 0.30,
    )
