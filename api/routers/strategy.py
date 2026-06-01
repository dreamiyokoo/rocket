from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.calculator import WINDOW, _no_entry, _window_stats
from core.database import get_db
from ml.predictor import predict as ml_predict

router = APIRouter(prefix="/api/v1/strategy", tags=["strategy"])

BET_1_STAKE = 100.0
BET_1_TARGET = 2.0
BET_2_STAKE = 50.0
BET_2_TARGET_FIXED = 3.5
FLOW_THRESHOLD = 0.50


@dataclass(frozen=True)
class StrategyConfig:
    key: str
    label: str
    b2_target: float
    use_no_entry: bool
    use_flow: bool
    use_scale: bool


STRATEGIES: tuple[StrategyConfig, ...] = (
    StrategyConfig(
        key="fixed_35_baseline",
        label="固定3.5x（フィルタなし）",
        b2_target=3.5,
        use_no_entry=False,
        use_flow=False,
        use_scale=False,
    ),
    StrategyConfig(
        key="fixed_35_guarded",
        label="固定3.5x（No-Entry + 流れ>=50%）",
        b2_target=3.5,
        use_no_entry=True,
        use_flow=True,
        use_scale=False,
    ),
    StrategyConfig(
        key="fixed_90_guarded",
        label="固定9.0x（No-Entry + 流れ>=50%）",
        b2_target=9.0,
        use_no_entry=True,
        use_flow=True,
        use_scale=False,
    ),
)


def _stake_scale(prob_2x: float) -> float:
    if prob_2x >= 0.60:
        return 1.5
    if prob_2x >= 0.40:
        return 1.0
    return 0.5


def _simulate_single_round(actual: float, b2_target: float, scale: float) -> tuple[float, float, bool, bool]:
    bet1 = BET_1_STAKE * scale
    bet2 = BET_2_STAKE * scale

    pnl = 0.0
    hit_b1 = actual >= BET_1_TARGET
    hit_b2 = actual >= b2_target

    if hit_b1:
        pnl += bet1 * (BET_1_TARGET - 1)
    else:
        pnl -= bet1

    if hit_b2:
        pnl += bet2 * (b2_target - 1)
    else:
        pnl -= bet2

    return pnl, bet1 + bet2, hit_b1, hit_b2


def _simulate_strategy(config: StrategyConfig, multipliers: list[float]) -> dict:
    entries = 0
    skips = 0
    total_pnl = 0.0
    total_staked = 0.0
    hit_b1 = 0
    hit_b2 = 0

    if len(multipliers) <= WINDOW:
        return {
            "key": config.key,
            "label": config.label,
            "b2_target": config.b2_target,
            "entries": 0,
            "skips": 0,
            "total_pnl": 0.0,
            "total_staked": 0.0,
            "roi": 0.0,
            "bet1_hit_rate": 0.0,
            "bet2_hit_rate": 0.0,
        }

    for i in range(WINDOW, len(multipliers)):
        history = multipliers[:i]
        window = multipliers[i - WINDOW : i]
        ws = _window_stats(window)
        no_entry = _no_entry(history, window)

        enter = True
        if config.use_no_entry and no_entry.active:
            enter = False
        if config.use_flow and ws.prob_2x < FLOW_THRESHOLD:
            enter = False

        if not enter:
            skips += 1
            continue

        scale = _stake_scale(ws.prob_2x) if config.use_scale else 1.0
        pnl, staked, b1_win, b2_win = _simulate_single_round(multipliers[i], config.b2_target, scale)
        entries += 1
        total_pnl += pnl
        total_staked += staked
        hit_b1 += 1 if b1_win else 0
        hit_b2 += 1 if b2_win else 0

    roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0

    return {
        "key": config.key,
        "label": config.label,
        "b2_target": config.b2_target,
        "entries": entries,
        "skips": skips,
        "total_pnl": round(total_pnl, 1),
        "total_staked": round(total_staked, 1),
        "roi": round(roi, 2),
        "bet1_hit_rate": round((hit_b1 / entries * 100), 1) if entries > 0 else 0.0,
        "bet2_hit_rate": round((hit_b2 / entries * 100), 1) if entries > 0 else 0.0,
    }


def _build_current_decision(multipliers: list[float]) -> dict:
    if len(multipliers) < WINDOW:
        return {
            "ready": False,
            "entry": False,
            "reasons": ["データ不足"],
            "flow_prob_2x": 0.0,
            "no_entry_active": False,
            "no_entry_reasons": [],
            "stake_scale": 1.0,
            "bet1_stake": int(BET_1_STAKE),
            "bet1_target": BET_1_TARGET,
            "bet2_stake": int(BET_2_STAKE),
            "bet2_target": BET_2_TARGET_FIXED,
            "ml": {"available": False},
        }

    window = multipliers[-WINDOW:]
    ws = _window_stats(window)
    no_entry = _no_entry(multipliers, window)
    ml = ml_predict(multipliers)

    entry = True
    reasons: list[str] = []

    if no_entry.active:
        entry = False
        reasons.append("No-Entryゾーン")

    if ws.prob_2x < FLOW_THRESHOLD:
        entry = False
        reasons.append(f"流れ不足（2x到達率 {ws.prob_2x * 100:.0f}%）")

    b2_target = BET_2_TARGET_FIXED
    if ml.available:
        if ml.skip_recommended:
            entry = False
            reasons.append("ML: Blue高確率で見送り")
        elif ml.entry_boost:
            reasons.append("ML: Red高確率（参考）")

    if not reasons:
        reasons.append("No-Entryなし・流れ条件クリア")

    return {
        "ready": True,
        "entry": entry,
        "reasons": reasons,
        "flow_prob_2x": round(ws.prob_2x, 4),
        "no_entry_active": no_entry.active,
        "no_entry_reasons": no_entry.reasons,
        "stake_scale": 1.0,
        "bet1_stake": int(BET_1_STAKE),
        "bet1_target": BET_1_TARGET,
        "bet2_stake": int(BET_2_STAKE),
        "bet2_target": b2_target,
        "ml": {
            "available": ml.available,
            "skip_recommended": ml.skip_recommended if ml.available else False,
            "entry_boost": ml.entry_boost if ml.available else False,
            "prob_blue_binary": ml.prob_blue_binary if ml.available else None,
            "prob_red": ml.prob_red if ml.available else None,
        },
    }


def _simulate_signal_follow(multipliers: list[float]) -> dict:
    """"今回は掛ける" シグナルを各ラウンドで実践した場合の総合収支を返す。"""
    entries = 0
    skips = 0
    total_pnl = 0.0
    total_staked = 0.0
    hit_b1 = 0
    hit_b2 = 0

    if len(multipliers) <= WINDOW:
        return {
            "entries": 0,
            "skips": 0,
            "total_pnl": 0.0,
            "total_staked": 0.0,
            "roi": 0.0,
            "bet1_hit_rate": 0.0,
            "bet2_hit_rate": 0.0,
            "avg_b2_target": BET_2_TARGET_FIXED,
        }

    for i in range(WINDOW, len(multipliers)):
        history = multipliers[:i]
        window = multipliers[i - WINDOW : i]
        ws = _window_stats(window)
        no_entry = _no_entry(history, window)
        ml = ml_predict(history)

        entry = True

        if no_entry.active:
            entry = False
        if ws.prob_2x < FLOW_THRESHOLD:
            entry = False

        if ml.available:
            if ml.skip_recommended:
                entry = False

        if not entry:
            skips += 1
            continue

        pnl, staked, b1_win, b2_win = _simulate_single_round(multipliers[i], BET_2_TARGET_FIXED, 1.0)
        entries += 1
        total_pnl += pnl
        total_staked += staked
        hit_b1 += 1 if b1_win else 0
        hit_b2 += 1 if b2_win else 0

    roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0
    return {
        "entries": entries,
        "skips": skips,
        "total_pnl": round(total_pnl, 1),
        "total_staked": round(total_staked, 1),
        "roi": round(roi, 2),
        "bet1_hit_rate": round((hit_b1 / entries * 100), 1) if entries > 0 else 0.0,
        "bet2_hit_rate": round((hit_b2 / entries * 100), 1) if entries > 0 else 0.0,
        "avg_b2_target": BET_2_TARGET_FIXED,
    }


@router.get("/simulate")
async def get_strategy_simulation(
    lookback: int = Query(default=5000, ge=200, le=50000),
    db: AsyncSession = Depends(get_db),
):
    rows_result = await db.execute(
        text(
            "SELECT multiplier FROM ("
            "  SELECT multiplier, recorded_at, id FROM rounds "
            "  ORDER BY recorded_at DESC, id DESC LIMIT :lim"
            ") t ORDER BY recorded_at ASC, id ASC"
        ),
        {"lim": lookback},
    )
    rows = rows_result.fetchall()

    # 重いシミュレーション計算前にトランザクションを閉じて接続を解放
    await db.rollback()

    multipliers = [float(r.multiplier) for r in rows]

    strategies = [_simulate_strategy(config, multipliers) for config in STRATEGIES]

    return {
        "lookback": lookback,
        "rounds_used": len(multipliers),
        "window": WINDOW,
        "current_decision": _build_current_decision(multipliers),
        "signal_follow_summary": _simulate_signal_follow(multipliers),
        "strategies": strategies,
    }


@router.get("/current")
async def get_current_strategy_signal(
    lookback: int = Query(default=300, ge=WINDOW, le=5000),
    db: AsyncSession = Depends(get_db),
):
    rows_result = await db.execute(
        text(
            "SELECT multiplier FROM ("
            "  SELECT multiplier, recorded_at, id FROM rounds "
            "  ORDER BY recorded_at DESC, id DESC LIMIT :lim"
            ") t ORDER BY recorded_at ASC, id ASC"
        ),
        {"lim": lookback},
    )
    rows = rows_result.fetchall()

    # 判定ロジック計算前に接続を解放
    await db.rollback()

    multipliers = [float(r.multiplier) for r in rows]
    return {
        "rounds_used": len(multipliers),
        "window": WINDOW,
        "current_decision": _build_current_decision(multipliers),
    }
