"""
ベッティング戦略シミュレーション
- 実DBデータを使い「100コイン@2x + 50コイン@Nx」の複合戦略を検証する
- 流れ判定エントリー（窓内 2x 到達率 >= しきい値のときのみ賭ける）
- 賭け額スケール戦略（流れが強いほど賭け額を増やす）
- No-Entry フィルタ・推奨ライン活用あり/なし を比較する

Usage:
  python scripts/simulate_strategy.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field

import asyncpg

# calculator をインポートするためパスを通す（ホスト側: api/ , コンテナ側: /app/）
_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api")
if os.path.isdir(_base):
    sys.path.insert(0, _base)
else:
    sys.path.insert(0, "/app")
from analysis.calculator import (
    WINDOW,
    _no_entry,
    _recommendation,
    _window_stats,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://rocket:changeme@localhost:5432/rocket",
).replace("postgresql+asyncpg://", "postgresql://")

# ──────────────────────────────────────────────
# ベッティングパラメータ
BET_1_STAKE   = 100   # コイン
BET_1_TARGET  = 2.0   # x
BET_2_STAKE   = 50    # コイン
# BET_2_TARGET は戦略ごとに変える

TARGET_PROFIT_LINE = 271.45  # ユーザー指定の利確ライン参照値

# ─── 流れ判定しきい値 ───────────────────────────
# 直近 WINDOW ラウンド内の「2x 到達率」がこれ以上のときだけエントリー
FLOW_ENTRY_THRESHOLD_2X   = 0.50   # 50%（デフォルト）
FLOW_ENTRY_THRESHOLD_HOT  = 0.60   # 60%（熱い流れ）

# ─── 賭け額スケール定義 ──────────────────────────
# 流れが強い (prob_2x >= HOT) → 増額 / 普通 → 標準 / 弱い → 減額
SCALE_COLD   = 0.5   # 弱い流れ（prob_2x < 0.40）
SCALE_NORMAL = 1.0   # 標準
SCALE_HOT    = 1.5   # 熱い流れ（prob_2x >= 0.60）
# ──────────────────────────────────────────────


@dataclass
class RoundResult:
    round_idx: int
    multiplier: float
    no_entry_active: bool
    no_entry_reasons: list[str]
    regime: str
    floor_line: float
    target_line: float
    prob_2x: float   # 直近 WINDOW の 2x 到達率
    prob_5x: float   # 直近 WINDOW の 5x 到達率


@dataclass
class SimStats:
    name: str
    bets: int = 0
    skipped: int = 0
    balance: float = 0.0
    wins_b1: int = 0
    wins_b2: int = 0
    losses_b1: int = 0
    losses_b2: int = 0
    peak: float = 0.0
    trough: float = 0.0
    b2_targets: list[float] = field(default_factory=list)
    total_staked: float = 0.0   # 実際に賭けた総額（スケール考慮）

    def apply_bet(self, multiplier: float, b2_target: float,
                  stake_scale: float = 1.0) -> None:
        self.bets += 1
        self.b2_targets.append(b2_target)

        s1 = BET_1_STAKE * stake_scale
        s2 = BET_2_STAKE * stake_scale
        self.total_staked += s1 + s2

        # Bet 1
        if multiplier >= BET_1_TARGET:
            self.balance += s1 * (BET_1_TARGET - 1)
            self.wins_b1 += 1
        else:
            self.balance -= s1
            self.losses_b1 += 1

        # Bet 2
        if multiplier >= b2_target:
            self.balance += s2 * (b2_target - 1)
            self.wins_b2 += 1
        else:
            self.balance -= s2
            self.losses_b2 += 1

        if self.balance > self.peak:
            self.peak = self.balance
        if self.balance < self.trough:
            self.trough = self.balance

    def skip(self) -> None:
        self.skipped += 1

    def avg_b2_target(self) -> float:
        return sum(self.b2_targets) / len(self.b2_targets) if self.b2_targets else 0.0

    def roi(self) -> float:
        return (self.balance / self.total_staked * 100) if self.total_staked > 0 else 0.0

    def print_summary(self) -> None:
        total = self.bets + self.skipped
        print(f"\n{'='*58}")
        print(f"  戦略: {self.name}")
        print(f"{'='*58}")
        print(f"  対象ラウンド数  : {total}")
        print(f"  エントリー      : {self.bets}  スキップ: {self.skipped}")
        print(f"  総賭け額        : {self.total_staked:.0f} コイン")
        print(f"  最終損益        : {self.balance:+.1f} コイン")
        print(f"  ROI             : {self.roi():+.2f}%")
        print(f"  ピーク          : {self.peak:+.1f}  最大DD: {self.trough:+.1f}")
        if self.bets:
            print(f"  Bet1(2x) 勝率   : {self.wins_b1}/{self.bets} ({self.wins_b1/self.bets*100:.1f}%)")
            print(f"  Bet2 勝率       : {self.wins_b2}/{self.bets} ({self.wins_b2/self.bets*100:.1f}%)")
        print(f"  Bet2 平均目標x  : {self.avg_b2_target():.2f}x")


# ──────────────────────────────────────────────
# 分析済みラウンドリストを作る
# ──────────────────────────────────────────────

def build_rounds(multipliers: list[float]) -> list[RoundResult]:
    results = []
    for i in range(WINDOW, len(multipliers)):
        window   = multipliers[i - WINDOW: i]
        history  = multipliers[:i]
        rec      = _recommendation(window)
        no_e     = _no_entry(history, window)
        ws       = _window_stats(window)
        results.append(RoundResult(
            round_idx        = i,
            multiplier       = multipliers[i],
            no_entry_active  = no_e.active,
            no_entry_reasons = no_e.reasons,
            regime           = rec.regime,
            floor_line       = rec.floor_line,
            target_line      = rec.target_line,
            prob_2x          = ws.prob_2x,
            prob_5x          = ws.prob_5x,
        ))
    return results


# ──────────────────────────────────────────────
# 戦略群
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# 戦略群
# ──────────────────────────────────────────────

def _scale_for(prob_2x: float) -> float:
    """prob_2x に応じた賭け額スケールを返す"""
    if prob_2x >= FLOW_ENTRY_THRESHOLD_HOT:
        return SCALE_HOT
    if prob_2x >= 0.40:
        return SCALE_NORMAL
    return SCALE_COLD


def run_strategy_fixed(
    rounds: list[RoundResult],
    b2_target: float,
    use_no_entry_filter: bool,
    label: str,
    flow_threshold: float | None = None,
    use_scale: bool = False,
) -> SimStats:
    """固定 N 戦略。
    flow_threshold: prob_2x がこれ未満のラウンドはスキップ（None=無条件エントリー）
    use_scale: True なら prob_2x に応じて賭け額を増減
    """
    stats = SimStats(name=label)
    for r in rounds:
        if use_no_entry_filter and r.no_entry_active:
            stats.skip()
            continue
        if flow_threshold is not None and r.prob_2x < flow_threshold:
            stats.skip()
            continue
        scale = _scale_for(r.prob_2x) if use_scale else 1.0
        stats.apply_bet(r.multiplier, b2_target, stake_scale=scale)
    return stats


def run_strategy_dynamic(
    rounds: list[RoundResult],
    use_no_entry_filter: bool,
    label: str,
    use_floor_as_b2: bool = False,
    flow_threshold: float | None = None,
    use_scale: bool = False,
) -> SimStats:
    """Bet2 に推奨ライン（target_line or floor_line）を使う動的戦略"""
    stats = SimStats(name=label)
    for r in rounds:
        if use_no_entry_filter and r.no_entry_active:
            stats.skip()
            continue
        if flow_threshold is not None and r.prob_2x < flow_threshold:
            stats.skip()
            continue
        b2_t = r.floor_line if use_floor_as_b2 else r.target_line
        b2_t = max(b2_t, 1.02)
        scale = _scale_for(r.prob_2x) if use_scale else 1.0
        stats.apply_bet(r.multiplier, b2_t, stake_scale=scale)
    return stats


# ──────────────────────────────────────────────
# 流れ統計
# ──────────────────────────────────────────────

def print_flow_stats(rounds: list[RoundResult]) -> None:
    total = len(rounds)
    hot   = sum(1 for r in rounds if r.prob_2x >= FLOW_ENTRY_THRESHOLD_HOT)
    warm  = sum(1 for r in rounds if FLOW_ENTRY_THRESHOLD_2X <= r.prob_2x < FLOW_ENTRY_THRESHOLD_HOT)
    cold  = sum(1 for r in rounds if r.prob_2x < FLOW_ENTRY_THRESHOLD_2X)

    # 各ゾーンの実際の到達率
    def win2(rs: list[RoundResult]) -> str:
        n = len(rs)
        if n == 0: return "–"
        w = sum(1 for r in rs if r.multiplier >= 2.0)
        return f"{w}/{n} ({w/n*100:.0f}%)"

    hot_rs  = [r for r in rounds if r.prob_2x >= FLOW_ENTRY_THRESHOLD_HOT]
    warm_rs = [r for r in rounds if FLOW_ENTRY_THRESHOLD_2X <= r.prob_2x < FLOW_ENTRY_THRESHOLD_HOT]
    cold_rs = [r for r in rounds if r.prob_2x < FLOW_ENTRY_THRESHOLD_2X]

    print(f"\n{'='*58}")
    print(f"  流れ分布統計 (ウィンドウ内 2x 到達率)")
    print(f"{'='*58}")
    print(f"  HOT  (prob_2x >= {FLOW_ENTRY_THRESHOLD_HOT:.0%}) : {hot:>3} ラウンド  実際の2x到達: {win2(hot_rs)}")
    print(f"  WARM (>={FLOW_ENTRY_THRESHOLD_2X:.0%}〜<{FLOW_ENTRY_THRESHOLD_HOT:.0%})  : {warm:>3} ラウンド  実際の2x到達: {win2(warm_rs)}")
    print(f"  COLD (<{FLOW_ENTRY_THRESHOLD_2X:.0%})             : {cold:>3} ラウンド  実際の2x到達: {win2(cold_rs)}")


# ──────────────────────────────────────────────
# No-Entry 統計
# ──────────────────────────────────────────────

def print_no_entry_stats(rounds: list[RoundResult]) -> None:
    total       = len(rounds)
    no_entry_on = [r for r in rounds if r.no_entry_active]
    reasons: dict[str, int] = {}
    for r in no_entry_on:
        for rsn in r.no_entry_reasons:
            reasons[rsn] = reasons.get(rsn, 0) + 1

    print(f"\n{'='*58}")
    print(f"  No-Entry Zone 統計 ({total} ラウンド分析済)")
    print(f"{'='*58}")
    print(f"  No-Entry 発動     : {len(no_entry_on)} / {total} ({len(no_entry_on)/total*100:.1f}%)")
    for rsn, cnt in sorted(reasons.items()):
        print(f"    - {rsn:<30}: {cnt}")

    print(f"\n  倍率到達率（全{total}ラウンド）")
    for x in [2.0, 3.0, 5.0, 10.0, 20.0, 50.0, TARGET_PROFIT_LINE]:
        cnt = sum(1 for r in rounds if r.multiplier >= x)
        print(f"    >= {x:>7.2f}x : {cnt:>3} / {total}  ({cnt/total*100:5.1f}%)")


# ──────────────────────────────────────────────
# 最適 N 探索（流れ条件あり）
# ──────────────────────────────────────────────

def find_optimal_n(
    rounds: list[RoundResult],
    use_no_entry_filter: bool,
    flow_threshold: float | None,
    use_scale: bool,
) -> None:
    parts = []
    if use_no_entry_filter: parts.append("No-Entryフィルタ")
    if flow_threshold is not None: parts.append(f"流れ>={flow_threshold:.0%}")
    if use_scale: parts.append("賭け額スケール")
    label = "、".join(parts) if parts else "フィルタなし"
    print(f"\n━━  Bet2 最適 N 探索（{label}）  ━━")
    print(f"  {'N':>6}  {'損益':>9}  {'ROI':>7}  {'勝率':>7}  {'エントリー':>8}")
    best_balance = float("-inf")
    best_n = 0.0
    for n_10 in range(15, 301, 5):
        n = n_10 / 10
        s = run_strategy_fixed(rounds, n, use_no_entry_filter, "",
                               flow_threshold=flow_threshold, use_scale=use_scale)
        if s.bets == 0:
            continue
        win_rate = s.wins_b2 / s.bets * 100
        print(f"  {n:>6.1f}  {s.balance:>+9.1f}  {s.roi():>+6.1f}%  {win_rate:>5.1f}%  {s.bets:>7}")
        if s.balance > best_balance:
            best_balance = s.balance
            best_n = n
    print(f"  → 最適 N = {best_n:.1f}x  (損益 {best_balance:+.1f} コイン)")


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

async def fetch_multipliers() -> list[float]:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT multiplier FROM rounds ORDER BY id ASC")
        return [float(r["multiplier"]) for r in rows]
    finally:
        await conn.close()


async def main() -> None:
    print("DB からデータ取得中…")
    multipliers = await fetch_multipliers()
    print(f"  {len(multipliers)} ラウンド読み込み完了")

    print("\n分析ラウンド構築中…")
    rounds = build_rounds(multipliers)
    print(f"  {len(rounds)} ラウンドで分析可能")

    print_no_entry_stats(rounds)
    print_flow_stats(rounds)

    # ─── 最適 N 探索（条件の組み合わせ）─────
    find_optimal_n(rounds, False, None,  False)   # ベースライン
    find_optimal_n(rounds, True,  None,  False)   # No-Entryのみ
    find_optimal_n(rounds, True,  0.50,  False)   # No-Entry + 流れ>=50%
    find_optimal_n(rounds, True,  0.50,  True)    # No-Entry + 流れ>=50% + スケール

    # ─── 代表戦略の詳細サマリー ──────────────
    strategies: list[SimStats] = []

    # ① ベースライン（固定）
    strategies.append(run_strategy_fixed(rounds, 3.5, False, "固定3.5x フィルタなし"))
    strategies.append(run_strategy_fixed(rounds, 3.5, True,  "固定3.5x No-Entryフィルタ"))

    # ② 流れ判定エントリー（prob_2x >= 50% のときのみ）
    strategies.append(run_strategy_fixed(
        rounds, 3.5, True, "固定3.5x No-Entry+流れ>=50%",
        flow_threshold=0.50))
    strategies.append(run_strategy_fixed(
        rounds, 3.5, True, "固定3.5x No-Entry+流れ>=60%",
        flow_threshold=0.60))

    # ③ 賭け額スケール（流れが強いほど増額）
    strategies.append(run_strategy_fixed(
        rounds, 3.5, True, "固定3.5x No-Entry+流れ>=50%+スケール",
        flow_threshold=0.50, use_scale=True))

    # ④ 流れ判定 + 目標も変える版
    strategies.append(run_strategy_fixed(
        rounds, 2.0, True, "固定2.0x No-Entry+流れ>=50%+スケール",
        flow_threshold=0.50, use_scale=True))
    strategies.append(run_strategy_fixed(
        rounds, 5.0, True, "固定5.0x No-Entry+流れ>=50%+スケール",
        flow_threshold=0.50, use_scale=True))

    for s in strategies:
        s.print_summary()

    best = max(strategies, key=lambda s: s.balance)
    print(f"\n\n★ 最高損益戦略: {best.name}")
    print(f"   損益: {best.balance:+.1f} コイン  ROI: {best.roi():+.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
