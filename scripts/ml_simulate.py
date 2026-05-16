"""
ML ベースのベッティング戦略シミュレーション

使い方:
  python3 scripts/ml_simulate.py
  python3 scripts/ml_simulate.py --csv docs/rounds_export_ml.csv

戦略:
  - ML戦略A: High確率 > HIGH_THRESH でエントリー
  - ML戦略B: Low確率 > LOW_SKIP_THRESH のときスキップ（+ ルールベースと組み合わせ）
  - ルールベース⑤（比較対象）: No-Entry + 流れ>=50% + スケール
"""

import argparse
import os
import pickle
import numpy as np
import pandas as pd

WINDOW = 20
FEATURE_COLS = [
    'mean', 'median', 'std', 'max', 'min', 'cv',
    'prob_2x', 'prob_5x', 'prob_10x', 'low_streak',
    'slope', 'log_mean', 'log_std', 'momentum',
]
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'docs', 'ml_models')

# ベット設定
BET1_AMOUNT = 100
BET1_TARGET = 2.0
BET2_AMOUNT = 50
BET2_TARGET = 3.5

# MLしきい値
HIGH_THRESH = 0.30     # High確率 > 30% でエントリー
LOW_SKIP_THRESH = 0.60 # Low確率 > 60% でスキップ

# ルールベース設定
RB_WINDOW = 18
RB_FLOW_THRESH = 0.50
RB_NO_ENTRY_MEDIAN = 1.50


def make_features(df: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    rows = []
    for i in range(window, len(df)):
        w = df['multiplier'].iloc[i - window:i].values
        row = {
            'mean':       np.mean(w),
            'median':     np.median(w),
            'std':        np.std(w),
            'max':        np.max(w),
            'min':        np.min(w),
            'cv':         np.std(w) / (np.mean(w) + 1e-6),
            'prob_2x':    np.mean(w >= 2.0),
            'prob_5x':    np.mean(w >= 5.0),
            'prob_10x':   np.mean(w >= 10.0),
            'low_streak': sum(1 for x in reversed(w) if x < 1.5),
            'slope':      np.polyfit(np.arange(window), np.log(np.maximum(w, 0.01)), 1)[0],
            'log_mean':   np.mean(np.log(np.maximum(w, 0.01))),
            'log_std':    np.std(np.log(np.maximum(w, 0.01))),
            'momentum':   np.mean(w[-5:]) - np.mean(w[:5]),
            'target':     df['multiplier'].iloc[i],
            'round_idx':  i,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def simulate_bet(actual: float, scale: float = 1.0) -> float:
    """1ラウンド分の損益を返す"""
    pnl = 0.0
    b1 = BET1_AMOUNT * scale
    b2 = BET2_AMOUNT * scale
    # Bet1
    if actual >= BET1_TARGET:
        pnl += b1 * (BET1_TARGET - 1)
    else:
        pnl -= b1
    # Bet2
    if actual >= BET2_TARGET:
        pnl += b2 * (BET2_TARGET - 1)
    else:
        pnl -= b2
    return pnl


def run_strategy(name: str, entries: list, actuals: list, scales: list) -> dict:
    """エントリーした各ラウンドの損益を集計"""
    pnl_list = []
    total_bet = 0.0
    for entered, actual, scale in zip(entries, actuals, scales):
        if entered:
            p = simulate_bet(actual, scale)
            pnl_list.append(p)
            total_bet += (BET1_AMOUNT + BET2_AMOUNT) * scale
    cumulative = np.cumsum(pnl_list)
    # 最大ドローダウン計算
    peak = 0.0
    max_drawdown = 0.0
    running = 0.0
    for p in pnl_list:
        running += p
        if running > peak:
            peak = running
        dd = running - peak
        if dd < max_drawdown:
            max_drawdown = dd

    n_entries = sum(entries)
    total_pnl = sum(pnl_list)
    roi = total_pnl / total_bet * 100 if total_bet > 0 else 0
    bet1_wins = sum(1 for entered, actual in zip(entries, actuals) if entered and actual >= BET1_TARGET)
    bet2_wins = sum(1 for entered, actual in zip(entries, actuals) if entered and actual >= BET2_TARGET)
    return {
        'name': name,
        'entries': n_entries,
        'skips': len(entries) - n_entries,
        'total_bet': round(total_bet),
        'total_pnl': round(total_pnl),
        'roi': round(roi, 1),
        'max_dd': round(max_drawdown),
        'bet1_win_rate': round(bet1_wins / n_entries * 100, 1) if n_entries > 0 else 0,
        'bet2_win_rate': round(bet2_wins / n_entries * 100, 1) if n_entries > 0 else 0,
    }


def print_result(r: dict):
    print(f"\n  【{r['name']}】")
    print(f"  エントリー: {r['entries']}  スキップ: {r['skips']}")
    print(f"  総賭け額: {r['total_bet']:,}  損益: {r['total_pnl']:+,}  ROI: {r['roi']}%")
    print(f"  最大DD: {r['max_dd']:+,}  Bet1勝率: {r['bet1_win_rate']}%  Bet2勝率: {r['bet2_win_rate']}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', default='docs/rounds_export_ml.csv')
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.path.dirname(__file__), '..', csv_path)

    print(f'データ読み込み: {csv_path}')
    df = pd.read_csv(csv_path, parse_dates=['recorded_at'])
    df = df.sort_values('recorded_at').reset_index(drop=True)
    print(f'件数: {len(df)}')

    feat_df = make_features(df)
    print(f'特徴量行数: {len(feat_df)}\n')

    # モデル読み込み
    mc_path = os.path.join(MODEL_DIR, 'multiclass.pkl')
    bi_path = os.path.join(MODEL_DIR, 'binary.pkl')
    with open(mc_path, 'rb') as f:
        mc_model = pickle.load(f)
    with open(bi_path, 'rb') as f:
        bi_model = pickle.load(f)

    X = feat_df[FEATURE_COLS]
    actuals = feat_df['target'].tolist()

    # 全データで予測（train/testを気にせずシミュレーション用に全件使う）
    mc_proba = mc_model.predict_proba(X)  # [Low, Mid, High]
    bi_proba = bi_model.predict_proba(X)[:, 1]  # Low確率

    prob_low  = mc_proba[:, 0]
    prob_mid  = mc_proba[:, 1]
    prob_high = mc_proba[:, 2]

    n = len(feat_df)

    # ルールベース: 流れ + No-Entry スケール
    def rb_scale_and_entry(i):
        w = feat_df[FEATURE_COLS].iloc[i]
        prob_2x = w['prob_2x']
        median  = w['median']
        if median < RB_NO_ENTRY_MEDIAN:
            return False, 1.0
        if prob_2x < RB_FLOW_THRESH:
            return False, 1.0
        if prob_2x >= 0.60:
            scale = 1.5
        elif prob_2x >= 0.50:
            scale = 1.0
        else:
            scale = 0.5
        return True, scale

    # 各戦略のエントリー配列
    baseline_entries   = [True] * n
    baseline_scales    = [1.0] * n

    rb_entries, rb_scales = zip(*[rb_scale_and_entry(i) for i in range(n)])
    rb_entries = list(rb_entries)
    rb_scales  = list(rb_scales)

    # ML戦略A: High確率 > HIGH_THRESH でエントリー
    ml_a_entries = [p > HIGH_THRESH for p in prob_high]
    ml_a_scales  = [1.0] * n

    # ML戦略B: Low確率 > LOW_SKIP_THRESH ならスキップ（それ以外はエントリー）
    ml_b_entries = [p <= LOW_SKIP_THRESH for p in bi_proba]
    ml_b_scales  = [1.0] * n

    # ML戦略C: ルールベース + ML Low確率スキップを組み合わせ
    ml_c_entries = [rb and (bi_proba[i] <= LOW_SKIP_THRESH) for i, rb in enumerate(rb_entries)]
    ml_c_scales  = rb_scales[:]

    # ML戦略D: High確率に応じてスケール（0〜1.5倍）
    def ml_d_scale(i):
        ph = prob_high[i]
        if ph >= 0.40:
            return 1.5
        elif ph >= 0.30:
            return 1.2
        else:
            return 1.0
    ml_d_entries = [True] * n
    ml_d_scales  = [ml_d_scale(i) for i in range(n)]

    print('=' * 55)
    print('  シミュレーション結果（全データ対象）')
    print('=' * 55)

    results = []
    for strat in [
        run_strategy('ベースライン（全ラウンド固定）', baseline_entries, actuals, baseline_scales),
        run_strategy('ルールベース⑤（No-Entry+流れ+スケール）', rb_entries, actuals, rb_scales),
        run_strategy('ML-A（High確率>30%でエントリー）', ml_a_entries, actuals, ml_a_scales),
        run_strategy('ML-B（Low確率>60%でスキップ）', ml_b_entries, actuals, ml_b_scales),
        run_strategy('ML-C（ルールベース + ML-Lowスキップ）', ml_c_entries, actuals, ml_c_scales),
        run_strategy('ML-D（High確率でスケール調整）', ml_d_entries, actuals, ml_d_scales),
    ]:
        print_result(strat)
        results.append(strat)

    # 結果ファイル出力
    output_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'ml_simulation_results.md')
    write_results_md(results, len(df), output_path)
    print(f'\n結果を保存: {output_path}')


def write_results_md(results: list, data_count: int, path: str):
    lines = [
        '# ML シミュレーション結果',
        '',
        '## 概要',
        '',
        f'- データ件数: {data_count} ラウンド',
        f'- ベット構成: Bet1={BET1_AMOUNT}コイン@{BET1_TARGET}x / Bet2={BET2_AMOUNT}コイン@{BET2_TARGET}x',
        f'- MLしきい値: High確率>{HIGH_THRESH} でエントリー / Low確率>{LOW_SKIP_THRESH} でスキップ',
        '',
        '## 戦略別結果',
        '',
        '| 戦略 | エントリー | スキップ | 総賭け額 | 損益 | ROI | 最大DD | Bet1勝率 | Bet2勝率 |',
        '|------|----------|--------|--------|-----|-----|-------|--------|--------|',
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | {r['entries']} | {r['skips']} | {r['total_bet']:,} "
            f"| {r['total_pnl']:+,} | {r['roi']}% | {r['max_dd']:+,} "
            f"| {r['bet1_win_rate']}% | {r['bet2_win_rate']}% |"
        )

    lines += [
        '',
        '## 特徴量重要度（参考）',
        '',
        '- slope（直近傾き）・momentum（モメンタム）・log_mean（対数平均）が上位',
        '- これらは「流れ」を定量化する特徴量であり、ルールベース戦略とも整合する',
        '',
        '## 注意',
        '',
        '- 2826件はデータ不足ライン（推奨5000件以上）',
        '- 3クラス分類精度: ~35%、2値分類AUC: ~0.48 と現段階では低精度',
        '- 5000件超後に再学習することで精度向上が期待される',
    ]

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
