"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  bandLabelJa,
  buildEvalArchive,
  buildPredictionSummary,
  type EvalStatsResponse,
  type PredictedBand,
  type PredictionSummaryRow,
  type RoundEvalArchive,
} from "./lib/evals";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const POLL_INTERVAL = 10_000;
const WS_RECONNECT_DELAY = 3_000; // WebSocket 切断後の再接続待機（ms）
const READY_THRESHOLD = 18;

// ── Types ───────────────────────────────────────────────────────────────────

type BB = { upper: number; middle: number; lower: number };
type MacdPoint = { macd: number; signal: number | null; histogram: number | null };

type Recommendation = {
  volatility_cv: number;
  regime: "low" | "medium" | "high";
  floor_line: number;
  target_line: number;
  flow_state: "hot" | "warm" | "cold";
  stake_scale: 0.5 | 1.0 | 1.5;
  entry_ok: boolean;
};

type NoEntryReason = "low_consecutive" | "post_spike" | "low_volatility" | "low_expected_value";

type NoEntryData = {
  active: boolean;
  reasons: NoEntryReason[];
  low_consecutive_count: number;
  volatility_cv: number;
  median_value: number;
};

type MLPrediction = {
  available: boolean;
  prob_blue?: number;
  prob_green?: number;
  prob_yellow?: number;
  prob_red?: number;
  prob_blue_binary?: number;
  skip_recommended?: boolean;
  entry_boost?: boolean;
};

type AnalysisData = {
  ready: boolean;
  total_rounds: number;
  window: number;
  prob_2x?: { current: number; history: number[] };
  prob_5x?: { current: number; history: number[] };
  prob_10x?: { current: number; history: number[] };
  prob_1_2x?: { current: number; history: number[] };
  prob_2_0x?: { current: number; history: number[] };
  moving_avg?: number;
  median?: number;
  std_dev?: number;
  max?: number;
  min?: number;
  atr?: number;
  rsi?: { period: number; current: number | null; chart: (number | null)[] };
  macd?: { fast: number; slow: number; signal_period: number; chart: (MacdPoint | null)[] };
  bollinger_bands?: { current: BB | null; chart: (BB | null)[] };
  chart_data?: { index: number; value: number }[];
  recommendation?: Recommendation;
  no_entry?: NoEntryData;
  ml_prediction?: MLPrediction;
  analyzed_at?: string;
};

type Params = { rsi_period: number; macd_fast: number; macd_slow: number; macd_signal: number };
type Round = { id: number; multiplier: number; recorded_at: string };

const DEFAULT_PARAMS: Params = { rsi_period: 14, macd_fast: 12, macd_slow: 26, macd_signal: 9 };

// ── Prob MACD helper ─────────────────────────────────────────────────────────
function calcEma(data: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const ema: number[] = [data[0]];
  for (let i = 1; i < data.length; i++) {
    ema.push(data[i] * k + ema[i - 1] * (1 - k));
  }
  return ema;
}

/** prob_2_0x の履歴に MACD(fast,slow,sig) を適用し現在の状態を返す
 *  戻り値: "warn" (histogram>0 = Blue率上昇中) | "buy" (histogram<=0 = Blue率下降中) | "neutral"
 */
function probMacdSignal(
  history: number[],
  fast = 3,
  slow = 8,
  sig = 3,
): { state: "warn" | "buy" | "neutral"; histogram: number; macdLine: number; signalLine: number } {
  if (history.length < slow + sig) return { state: "neutral", histogram: 0, macdLine: 0, signalLine: 0 };
  const emaFast = calcEma(history, fast);
  const emaSlow = calcEma(history, slow);
  const macdLine = emaFast.map((f, i) => f - emaSlow[i]);
  const macdSlice = macdLine.slice(slow - 1);
  const signalLine = calcEma(macdSlice, sig);
  const lastMacd = macdSlice[macdSlice.length - 1];
  const lastSignal = signalLine[signalLine.length - 1];
  const histogram = lastMacd - lastSignal;
  const state = histogram > 0 ? "warn" : histogram < 0 ? "buy" : "neutral";
  return { state, histogram, macdLine: lastMacd, signalLine: lastSignal };
}

// ── SVG helpers ─────────────────────────────────────────────────────────────

const PW = 560; const PH = 180;
const ML = 44;  const MT = 12; const MB = 24; const MR = 8;
const VW = ML + PW + MR;
const VH = MT + PH + MB;

function xOf(i: number, n: number) {
  return ML + (n <= 1 ? PW / 2 : (i / (n - 1)) * PW);
}
function yLinear(v: number, min: number, max: number) {
  return MT + PH - ((v - min) / (max - min || 1)) * PH;
}
function yLog(v: number) {
  const lo = Math.log10(1.01), hi = Math.log10(501);
  return MT + PH - ((Math.log10(Math.max(1.01, Math.min(501, v))) - lo) / (hi - lo)) * PH;
}
function toPath(pts: (readonly [number, number] | null)[]) {
  let d = ""; let open = false;
  for (const p of pts) {
    if (!p) { open = false; continue; }
    d += open ? ` L${p[0].toFixed(1)},${p[1].toFixed(1)}` : `M${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    open = true;
  }
  return d;
}
function pct(v: number) { return `${(v * 100).toFixed(1)}%`; }
function fmt(v: number) { return v % 1 === 0 ? v.toString() : v.toFixed(2); }

const COIN_OPTIONS = [10, 50, 100] as const;
const MIN_PAYOUT_MULTIPLIER: Record<PredictedBand, number> = {
  blue: 1.01,
  green: 2.0,
  yellow: 5.0,
  red: 10.0,
};

function calcPredictionPnL(
  coinSize: number,
  predictedCount: number,
  hitCount: number,
  overCount: number | null,
  band: PredictedBand,
) {
  if (band === "blue") {
    return 0;
  }
  const payoutHits = hitCount + (overCount ?? 0);
  return Math.round((-coinSize * predictedCount + coinSize * MIN_PAYOUT_MULTIPLIER[band] * payoutHits) * 100) / 100;
}

// ── Charts ───────────────────────────────────────────────────────────────────

function ProbChart({ data }: { data: AnalysisData }) {
  const h12 = data.prob_1_2x?.history ?? [];
  const h20 = data.prob_2_0x?.history ?? [];
  const h2 = data.prob_2x!.history;
  const h5 = data.prob_5x!.history;
  const h10 = data.prob_10x!.history;
  const n = h2.length;
  const pathOf = (arr: number[], color: string) => (
    <path d={toPath(arr.map((v, i) => [xOf(i, n), yLinear(v, 0, 1)] as const))}
      fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
  );
  const labelOf = (arr: number[], color: string) => (
    <text x={xOf(n - 1, n) + 4} y={yLinear(arr[arr.length - 1], 0, 1) + 4}
      fill={color} fontSize="10" fontWeight="bold">{pct(arr[arr.length - 1])}</text>
  );
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {[0, 0.25, 0.5, 0.75, 1.0].map((t) => (
        <g key={t}>
          <line x1={ML} y1={yLinear(t, 0, 1)} x2={ML + PW} y2={yLinear(t, 0, 1)} stroke="#374151" strokeDasharray="4 2" />
          <text x={ML - 4} y={yLinear(t, 0, 1) + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{Math.round(t * 100)}%</text>
        </g>
      ))}
      {h12.length > 0 && pathOf(h12, "#94a3b8")}
      {h20.length > 0 && pathOf(h20, "#fb923c")}
      {pathOf(h2, "#4ade80")} {pathOf(h5, "#facc15")} {pathOf(h10, "#f87171")}
      {n > 0 && <>
        {h12.length > 0 && labelOf(h12, "#94a3b8")}
        {h20.length > 0 && labelOf(h20, "#fb923c")}
        {labelOf(h2, "#4ade80")} {labelOf(h5, "#facc15")} {labelOf(h10, "#f87171")}
      </>}
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

function ProbMacdChart({ data }: { data: AnalysisData }) {
  const fast = 3, slow = 8, sig = 3;

  function buildMacdSeries(history: number[]) {
    if (history.length < slow + sig) return { macdLine: [], signalLine: [], histogram: [] };
    const emaF = calcEma(history, fast);
    const emaS = calcEma(history, slow);
    const macdLine = emaF.map((f, i) => f - emaS[i]);
    const macdSlice = macdLine.slice(slow - 1);
    const signalLine = calcEma(macdSlice, sig);
    const offset = slow - 1 + sig - 1;
    const histogram = macdSlice.slice(sig - 1).map((m, i) => m - signalLine[i]);
    return { macdLine: macdLine.slice(offset), signalLine: signalLine.slice(sig - 1), histogram, offset };
  }

  const h20 = data.prob_2_0x?.history ?? [];
  const h12 = data.prob_1_2x?.history ?? [];
  const m20 = buildMacdSeries(h20);
  const m12 = buildMacdSeries(h12);

  const allVals = [...m20.histogram, ...m20.macdLine, ...m20.signalLine,
                   ...m12.histogram, ...m12.macdLine, ...m12.signalLine].filter(isFinite);
  if (allVals.length === 0) return <p className="text-sm text-gray-500 py-8 text-center">データ不足</p>;

  const sorted = [...allVals].sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)];
  const mads = sorted.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  const mad = mads[Math.floor(mads.length / 2)];
  const spread = Math.max(mad * 6, 0.005);
  const lo = med - spread, hi = med + spread;
  const yM = (v: number) => yLinear(Math.max(lo, Math.min(hi, v)), lo, hi);
  const zero = yM(0);
  const n = m20.histogram.length;
  const barW = Math.max(1, (PW / Math.max(n, 1)) * 0.5);

  function histBars(histogram: number[], color1: string, color2: string) {
    return histogram.map((h, i) => {
      const x = xOf(i, n);
      const y0 = zero, yh = yM(h);
      const top = Math.min(y0, yh), ht = Math.abs(y0 - yh);
      return <rect key={i} x={x - barW / 2} y={top} width={barW} height={Math.max(1, ht)}
        fill={h >= 0 ? color1 : color2} opacity="0.5" />;
    });
  }
  function linePath(arr: number[], color: string, dash?: string) {
    return <path d={toPath(arr.map((v, i) => [xOf(i, n), yM(v)] as const))}
      fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round"
      strokeDasharray={dash} />;
  }

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      <line x1={ML} y1={zero} x2={ML + PW} y2={zero} stroke="#4b5563" strokeDasharray="4 2" />
      <text x={ML - 4} y={zero + 4} textAnchor="end" fill="#9ca3af" fontSize="10">0</text>
      {/* 2.0x以下 */}
      {histBars(m20.histogram, "#fb923c", "#1d4ed8")}
      {linePath(m20.macdLine, "#fb923c")}
      {linePath(m20.signalLine, "#f97316", "4 2")}
      {/* 1.2x以下 */}
      {histBars(m12.histogram, "#94a3b880", "#1e3a5f80")}
      {linePath(m12.macdLine, "#94a3b8")}
      {linePath(m12.signalLine, "#64748b", "4 2")}
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

function MultiplierChart({ data }: { data: AnalysisData }) {
  const cd = data.chart_data!; const bb = data.bollinger_bands?.chart ?? []; const n = cd.length;
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {[1.01, 2, 5, 10, 50, 100, 501].map((t) => {
        const y = yLog(t);
        if (y < MT || y > MT + PH) return null;
        return (
          <g key={t}>
            <line x1={ML} y1={y} x2={ML + PW} y2={y} stroke="#374151" strokeDasharray="4 2" />
            <text x={ML - 4} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{t}</text>
          </g>
        );
      })}
      <path d={toPath(bb.map((b, i) => b ? [xOf(i, n), yLog(b.upper)] as const : null))} fill="none" stroke="#6b7280" strokeWidth="1" strokeDasharray="4 3" />
      <path d={toPath(bb.map((b, i) => b ? [xOf(i, n), yLog(b.middle)] as const : null))} fill="none" stroke="#9ca3af" strokeWidth="1" strokeDasharray="4 3" />
      <path d={toPath(bb.map((b, i) => b ? [xOf(i, n), Math.max(MT, yLog(Math.max(b.lower, 1.01)))] as const : null))} fill="none" stroke="#6b7280" strokeWidth="1" strokeDasharray="4 3" />
      <path d={toPath(cd.map((d, i) => [xOf(i, n), yLog(d.value)] as const))} fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinejoin="round" />
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

function RsiChart({ rsi }: { rsi: (number | null)[] }) {
  const n = rsi.length;
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {[30, 50, 70].map((r) => (
        <g key={r}>
          <line x1={ML} y1={yLinear(r, 0, 100)} x2={ML + PW} y2={yLinear(r, 0, 100)}
            stroke={r === 70 ? "#ef4444" : r === 30 ? "#3b82f6" : "#4b5563"} strokeDasharray="4 2" strokeOpacity="0.6" />
          <text x={ML - 4} y={yLinear(r, 0, 100) + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{r}</text>
        </g>
      ))}
      <path d={toPath(rsi.map((v, i) => v != null ? [xOf(i, n), yLinear(v, 0, 100)] as const : null))}
        fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinejoin="round" />
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

function MacdChart({ macd }: { macd: (MacdPoint | null)[] }) {
  const n = macd.length;
  const vals = macd.flatMap((p) => p ? [p.macd, p.signal ?? p.macd, p.histogram ?? 0] : []);
  if (vals.length === 0) return null;
  // MAD（中央絶対偏差）ベースの堅牢なスケール計算
  const sorted = [...vals].sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)];
  const mads = sorted.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  const mad = mads[Math.floor(mads.length / 2)];
  const spread = Math.max(mad * 5, 0.01);
  const lo = med - spread;
  const hi = med + spread;
  const yM = (v: number) => yLinear(v, lo, hi);
  const zero = yM(0);
  const barW = Math.max(1, (PW / n) * 0.6);
  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      <line x1={ML} y1={zero} x2={ML + PW} y2={zero} stroke="#4b5563" strokeDasharray="4 2" />
      <text x={ML - 4} y={zero + 4} textAnchor="end" fill="#9ca3af" fontSize="10">0</text>
      {macd.map((p, i) => {
        if (!p || p.histogram == null) return null;
        const y1 = Math.min(yM(p.histogram), zero);
        const y2 = Math.max(yM(p.histogram), zero);
        return <rect key={i} x={xOf(i, n) - barW / 2} y={y1} width={barW} height={Math.max(1, y2 - y1)}
          fill={p.histogram >= 0 ? "#4ade80" : "#f87171"} opacity="0.5" />;
      })}
      <path d={toPath(macd.map((p, i) => p ? [xOf(i, n), yM(p.macd)] as const : null))}
        fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinejoin="round" />
      <path d={toPath(macd.map((p, i) => (p?.signal != null) ? [xOf(i, n), yM(p.signal)] as const : null))}
        fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeLinejoin="round" strokeDasharray="5 3" />
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

// ── Settings panel ────────────────────────────────────────────────────────────

function NumInput({ label, value, min, max, onChange }: {
  label: string; value: number; min: number; max: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-500">{label}</span>
      <input
        type="number" min={min} max={max} value={value}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
        className="w-20 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
    </label>
  );
}

function multiplierBadgeClass(v: number): string {
  if (v > 10) return "bg-red-700 text-white";
  if (v > 5)  return "bg-yellow-500 text-black";
  if (v > 2)  return "bg-green-600 text-white";
  return "bg-blue-600 text-white";
}

function predictedBandDotClass(band: PredictedBand): string {
  if (band === "blue") return "bg-blue-600";
  if (band === "green") return "bg-green-600";
  if (band === "yellow") return "bg-yellow-500";
  return "bg-red-700";
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  type ChartTab = "prob" | "multiplier" | "rsi" | "macd" | "prob_macd";
  const [data, setData]         = useState<AnalysisData | null>(null);
  const [error, setError]       = useState(false);
  const [rounds, setRounds]     = useState<Round[]>([]);
  const [evalArchive, setEvalArchive] = useState<RoundEvalArchive>({});
  const [evalStats, setEvalStats] = useState<EvalStatsResponse | null>(null);
  const [selectedCoinSize, setSelectedCoinSize] = useState<(typeof COIN_OPTIONS)[number]>(10);
  const [params, setParams]     = useState<Params>(DEFAULT_PARAMS);
  const [draft, setDraft]       = useState<Params>(DEFAULT_PARAMS);
  const [showSettings, setShowSettings] = useState(false);
  const [activeTab, setActiveTab] = useState<ChartTab>("prob");
  const [soundEnabled, setSoundEnabled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const evalStatsRequestRef = useRef<Promise<void> | null>(null);
  const paramsRef = useRef<Params>(params);
  const prevEntryOkRef = useRef<boolean>(false);

  useEffect(() => { paramsRef.current = params; }, [params]);

  const fetchRounds = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds`);
      if (!res.ok) return;
      const json = await res.json() as { rounds: Round[] };
      setRounds(json.rounds);
    } catch { /* best-effort */ }
  }, []);

  const fetchData = useCallback(async (p: Params) => {
    try {
      const qs = new URLSearchParams({
        rsi_period:  String(p.rsi_period),
        macd_fast:   String(p.macd_fast),
        macd_slow:   String(p.macd_slow),
        macd_signal: String(p.macd_signal),
      });
      const res = await fetch(`${API_URL}/api/v1/analysis?${qs}`);
      if (!res.ok) { setError(true); return; }
      setData(await res.json() as AnalysisData);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  const fetchEvalStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/evals/stats`, { cache: "no-store" });
      if (!res.ok) return;
      const evalData = await res.json() as EvalStatsResponse;
      setEvalStats(evalData);
      setEvalArchive(buildEvalArchive(evalData.recent));
    } catch {
      // best-effort
    }
  }, []);

  const refreshEvalStats = useCallback(() => {
    if (evalStatsRequestRef.current) return evalStatsRequestRef.current;
    const request = fetchEvalStats().finally(() => {
      evalStatsRequestRef.current = null;
    });
    evalStatsRequestRef.current = request;
    return request;
  }, [fetchEvalStats]);

  useEffect(() => {
    fetchData(params);
    fetchRounds();
    refreshEvalStats();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      fetchData(params);
      fetchRounds();
      refreshEvalStats();
    }, POLL_INTERVAL);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [params, fetchData, fetchRounds, refreshEvalStats]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let destroyed = false;

    const connect = () => {
      if (destroyed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${window.location.host}/api/v1/ws`);
      ws.onmessage = () => {
        fetchData(paramsRef.current);
        fetchRounds();
        refreshEvalStats();
      };
      ws.onclose = () => {
        if (!destroyed) {
          reconnectTimer = setTimeout(connect, WS_RECONNECT_DELAY);
        }
      };
      ws.onerror = () => { ws?.close(); };
    };
    connect();

    const ch = new BroadcastChannel("rocket:data-changed");
    ch.onmessage = () => {
      fetchData(paramsRef.current);
      fetchRounds();
      refreshEvalStats();
    };

    return () => {
      destroyed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      ch.close();
    };
  }, [fetchData, fetchRounds, refreshEvalStats]);

  const applySettings = () => {
    setParams(draft);
    setShowSettings(false);
  };

  // データ更新のたびに entry_ok が true なら通知音を鳴らす
  // 最新倍率 ≤ 2.0x → blue.mp3 / 2.01x以上 → notify.mp3
  useEffect(() => {
    const entryOk = data?.recommendation?.entry_ok ?? false;
    if (soundEnabled && entryOk) {
      try {
        const lastMultiplier = data?.chart_data?.at(-1)?.value ?? 999;
        const soundFile = lastMultiplier <= 2.0 ? "/blue.mp3" : "/notify.mp3";
        const audio = new Audio(soundFile);
        audio.play().catch(() => {/* autoplay ブロック時は無視 */});
      } catch { /* Audio 非対応環境では無視 */ }
    }
    prevEntryOkRef.current = entryOk;
  }, [data, soundEnabled]);

  const remaining = data ? Math.max(0, READY_THRESHOLD - data.total_rounds) : null;
  const rsiNeeded  = READY_THRESHOLD + params.rsi_period;
  const macdNeeded = READY_THRESHOLD + params.macd_slow + params.macd_signal - 2;
  const predictionSummary: PredictionSummaryRow[] = buildPredictionSummary(evalStats?.by_band ?? []);
  const totalPredictionCount = predictionSummary.reduce((sum, row) => sum + row.predictedCount, 0);
  const totalPredictionHitCount = predictionSummary.reduce((sum, row) => sum + row.hitCount, 0);
  const totalPredictionOverCount = predictionSummary.reduce((sum, row) => sum + (row.overCount ?? 0), 0);
  const totalPredictionHitRate = totalPredictionCount > 0 ? (totalPredictionHitCount / totalPredictionCount) * 100 : null;
  const predictionSimulation = predictionSummary.map((row) => ({
    ...row,
    pnl: calcPredictionPnL(selectedCoinSize, row.predictedCount, row.hitCount, row.overCount, row.band),
  }));
  const totalPredictionPnL = predictionSimulation.reduce((sum, row) => sum + row.pnl, 0);
  return (
    <main className="min-h-screen p-4 md:p-8 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Rocket Analysis</h1>
        <div className="flex items-center gap-4">
          <button onClick={() => { setShowSettings((s) => !s); setDraft(params); }}
            className="text-sm text-gray-400 hover:text-white transition-colors">
            {showSettings ? "▲ 設定を閉じる" : "⚙ 期間設定"}
          </button>
          <button
            onClick={() => {
              const next = !soundEnabled;
              setSoundEnabled(next);
              if (next) {
                try {
                  const lastMultiplier = data?.chart_data?.at(-1)?.value ?? 999;
                  const soundFile = lastMultiplier <= 2.0 ? "/blue.mp3" : "/notify.mp3";
                  const audio = new Audio(soundFile);
                  audio.play().catch(() => {});
                } catch { /* ignore */ }
              }
            }}
            title={soundEnabled ? "サウンド ON（クリックでOFF）" : "サウンド OFF（クリックでON）"}
            className={`text-lg transition-colors ${soundEnabled ? "text-green-400 hover:text-green-300" : "text-gray-500 hover:text-gray-300"}`}
          >
            {soundEnabled ? "🔔" : "🔕"}
          </button>
          <a href="/probability-trends" className="text-sm text-cyan-300 hover:text-cyan-200 transition-colors">確率推移 →</a>
          <a href="/input" className="text-sm text-gray-400 hover:text-white transition-colors">入力画面 →</a>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="bg-gray-900 rounded-xl p-4 space-y-4">
          <p className="text-xs text-gray-400">RSI・MACDは移動平均の履歴（18件ウィンドウ）に適用されます。</p>
          <div className="flex flex-wrap gap-6">
            <NumInput label="RSI 期間" value={draft.rsi_period} min={2} max={50}
              onChange={(v) => setDraft((d) => ({ ...d, rsi_period: v }))} />
            <NumInput label="MACD Fast" value={draft.macd_fast} min={2} max={50}
              onChange={(v) => setDraft((d) => ({ ...d, macd_fast: v }))} />
            <NumInput label="MACD Slow" value={draft.macd_slow} min={3} max={100}
              onChange={(v) => setDraft((d) => ({ ...d, macd_slow: v }))} />
            <NumInput label="MACD Signal" value={draft.macd_signal} min={2} max={30}
              onChange={(v) => setDraft((d) => ({ ...d, macd_signal: v }))} />
          </div>
          <button onClick={applySettings}
            className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors">
            適用
          </button>
        </div>
      )}

      {/* Status bar */}
      {!data && !error && <p className="text-gray-400 text-sm">読み込み中...</p>}
      {error && <p className="text-red-400 text-sm">データ取得に失敗しました。</p>}
      {data && (
        <div className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-6">
            <div>
              <p className="text-xs text-gray-500">蓄積件数</p>
              <p className="text-xl font-bold text-white">{data.total_rounds}<span className="text-sm text-gray-400 ml-1">rounds</span></p>
            </div>
            <div>
              <p className="text-xs text-gray-500">状態</p>
              {data.ready
                ? <p className="text-green-400 font-semibold">分析中</p>
                : <p className="text-yellow-400 font-semibold">あと {remaining} 件で分析開始</p>}
            </div>
            {data.ready && data.analyzed_at && (
              <div className="ml-auto">
                <p className="text-xs text-gray-600">最終更新</p>
                <p className="text-xs text-gray-500">{new Date(data.analyzed_at).toLocaleTimeString("ja-JP")}</p>
              </div>
            )}
          </div>
          {data.ready && data.no_entry && (() => {
            const ne = data.no_entry;
            const count = ne.reasons.length;
            const { bg, label } = count === 0
              ? { bg: "bg-green-700", label: "エントリー可" }
              : count === 1
              ? { bg: "bg-yellow-500 text-black", label: "注意" }
              : { bg: "bg-red-600", label: "買い禁止" };
            const conditions: { key: string; label: string; value: string; threshold: string; triggered: boolean }[] = [
              {
                key: "low_consecutive",
                label: "① 低倍率連続",
                value: `${ne.low_consecutive_count}連続`,
                threshold: "5連続以上で発動",
                triggered: ne.reasons.includes("low_consecutive"),
              },
              {
                key: "post_spike",
                label: "② 高倍率後調整",
                value: ne.reasons.includes("post_spike") ? "検出" : "なし",
                threshold: "10x直後に3件平均<1.3で発動",
                triggered: ne.reasons.includes("post_spike"),
              },
              {
                key: "low_volatility",
                label: "③ 低ボラティリティ",
                value: `CV ${ne.volatility_cv.toFixed(2)}`,
                threshold: "CV 0.25未満で発動",
                triggered: ne.reasons.includes("low_volatility"),
              },
              {
                key: "low_expected_value",
                label: "④ 期待値不足",
                value: `中央値 ${ne.median_value.toFixed(2)}x`,
                threshold: "中央値 1.50x未満で発動",
                triggered: ne.reasons.includes("low_expected_value"),
              },
            ];
            return (
              <div className="space-y-2">
              <div role="status" className={`flex flex-wrap items-center gap-3 rounded-lg px-3 py-2 ${bg} ${count < 2 ? "" : "text-white"}`}>
                  <span className="font-bold text-sm">{label}</span>
                  {ne.reasons.map((r) => (
                    <span key={r} className="text-xs opacity-80">
                      {conditions.find((c) => c.key === r)?.label}
                    </span>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-1">
                  {conditions.map((c) => (
                    <div key={c.key} className={`flex items-start gap-2 rounded px-2 py-1.5 text-xs ${c.triggered ? "bg-red-950 border border-red-800" : "bg-gray-800"}`}>
                      <span className={`mt-0.5 shrink-0 ${c.triggered ? "text-red-400" : "text-green-500"}`}>
                        {c.triggered ? "✗" : "✓"}
                      </span>
                      <div className="min-w-0">
                        <p className={`font-semibold ${c.triggered ? "text-red-300" : "text-gray-300"}`}>{c.label}</p>
                        <p className={`font-mono ${c.triggered ? "text-red-200" : "text-white"}`}>{c.value}</p>
                        <p className="text-gray-500">{c.threshold}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Recommendation */}
      {data?.ready && data.recommendation && (() => {
        const rec = data.recommendation;
        const regimeLabel = { low: "低ボラ", medium: "中ボラ", high: "高ボラ" }[rec.regime];
        const regimeColor = { low: "bg-blue-700 text-white", medium: "bg-yellow-500 text-black", high: "bg-red-600 text-white" }[rec.regime];
        const flowLabel = { hot: "🔥 HOT", warm: "流れあり", cold: "❄ COLD" }[rec.flow_state];
        const flowColor = { hot: "bg-orange-500 text-white", warm: "bg-green-600 text-white", cold: "bg-gray-600 text-white" }[rec.flow_state];
        const scaleLabel = { 1.5: "1.5倍増額", 1.0: "通常", 0.5: "0.5倍減額" }[rec.stake_scale];
        const prob2x = data.prob_2x?.current ?? 0;
        return (
          <section className="bg-gray-900 rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-gray-300">推奨ライン</h2>
              <span className={`text-xs font-bold px-2 py-0.5 rounded ${regimeColor}`}>{regimeLabel}</span>
              <span className={`text-xs font-bold px-2 py-0.5 rounded ${flowColor}`}>{flowLabel}</span>
              <span className="text-xs text-gray-500 ml-auto">CV {rec.volatility_cv.toFixed(2)}</span>
            </div>

            {/* Bet advice banner */}
            <div className={`rounded-lg px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3 ${
              rec.entry_ok ? "bg-green-900 border border-green-700" : "bg-gray-800 border border-gray-700"
            }`}>
              <div className="flex items-center gap-2">
                <span className={`text-lg font-bold ${ rec.entry_ok ? "text-green-300" : "text-gray-400" }`}>
                  {rec.entry_ok ? "✅ エントリー推奨" : "⏸ 待機"}
                </span>
              </div>
              {rec.entry_ok && (
                <div className="flex flex-wrap gap-3 sm:ml-auto">
                  <div className="text-center">
                    <p className="text-xs text-gray-400">Bet1</p>
                    <p className="text-sm font-bold text-white">{Math.round(100 * rec.stake_scale)}コイン <span className="text-green-400">@ 2.0x</span></p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">Bet2</p>
                    <p className="text-sm font-bold text-white">{Math.round(50 * rec.stake_scale)}コイン <span className="text-green-400">@ 3.5x</span></p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">賭け額</p>
                    <p className={`text-sm font-bold ${ rec.stake_scale === 1.5 ? "text-orange-400" : rec.stake_scale === 0.5 ? "text-blue-400" : "text-white" }`}>{scaleLabel}</p>
                  </div>
                </div>
              )}
              {!rec.entry_ok && (
                <p className="text-xs text-gray-500 sm:ml-auto">
                  {data.no_entry?.active ? "No-Entryゾーン発動中" : `流れ不足（2x到達率 ${(prob2x * 100).toFixed(0)}% < 50%）`}
                </p>
              )}
            </div>

            <div className="space-y-3">
              {/* 4段階シグナル */}
              {(() => {
                const ml = data.ml_prediction;
                const available = ml?.available && ml.prob_blue != null;
                const probBlue   = available ? ml!.prob_blue!   : null;
                const probGreen  = available ? ml!.prob_green!  : null;
                const probYellow = available ? ml!.prob_yellow! : null;
                const probRed    = available ? ml!.prob_red!    : null;

                // 最も高い確率のレベルをアクティブに、2番目をセミアクティブに
                type Level = "blue" | "green" | "yellow" | "red";
                let level: Level = "blue";
                let level2nd: Level | null = null;
                if (available) {
                  const probs: [Level, number][] = [
                    ["blue",   probBlue!],
                    ["green",  probGreen!],
                    ["yellow", probYellow!],
                    ["red",    probRed!],
                  ];
                  const sorted = [...probs].sort((a, b) => b[1] - a[1]);
                  level = sorted[0][0];
                  level2nd = sorted[1][0];
                }

                const levelDefs: { id: Level; label: string; range: string; active: string; semi: string; inactive: string; dot: string; text: string; textSemi: string; bar: string }[] = [
                  { id: "blue",   label: "🔵 Blue",   range: "≤ 2.0x",
                    active:   "bg-blue-900 border-2 border-blue-400",
                    semi:     "bg-blue-950 border border-blue-700 opacity-70",
                    inactive: "bg-gray-800 border border-gray-700 opacity-30",
                    dot: "bg-blue-400", text: "text-blue-300", textSemi: "text-blue-500", bar: "bg-blue-500" },
                  { id: "green",  label: "🟢 Green",  range: "2.01〜5.0x",
                    active:   "bg-green-900 border-2 border-green-400",
                    semi:     "bg-green-950 border border-green-700 opacity-70",
                    inactive: "bg-gray-800 border border-gray-700 opacity-30",
                    dot: "bg-green-400", text: "text-green-300", textSemi: "text-green-600", bar: "bg-green-500" },
                  { id: "yellow", label: "🟡 Yellow", range: "5.01〜10.0x",
                    active:   "bg-yellow-900 border-2 border-yellow-400",
                    semi:     "bg-yellow-950 border border-yellow-700 opacity-70",
                    inactive: "bg-gray-800 border border-gray-700 opacity-30",
                    dot: "bg-yellow-400", text: "text-yellow-300", textSemi: "text-yellow-600", bar: "bg-yellow-500" },
                  { id: "red",    label: "🔴 Red",    range: "10.01x〜",
                    active:   "bg-red-900 border-2 border-red-400",
                    semi:     "bg-red-950 border border-red-700 opacity-70",
                    inactive: "bg-gray-800 border border-gray-700 opacity-30",
                    dot: "bg-red-400", text: "text-red-300", textSemi: "text-red-600", bar: "bg-red-500" },
                ];

                const probMap: Record<Level, number | null> = {
                  blue: probBlue, green: probGreen, yellow: probYellow, red: probRed,
                };

                const activeLevelDef = levelDefs.find(lv => lv.id === level);

                return (
                  <>
                    {/* 予測色表示 */}
                    {available && activeLevelDef && (
                      <div className={`rounded-lg p-4 text-center ${activeLevelDef.active}`}>
                        <p className="text-xs text-gray-300 mb-2">予測色</p>
                        <p className={`text-3xl font-bold ${activeLevelDef.text}`}>
                          {activeLevelDef.label}
                        </p>
                        <p className={`text-2xl font-bold ${activeLevelDef.text} mt-1`}>
                          {(probMap[level]! * 100).toFixed(0)}%
                        </p>
                      </div>
                    )}

                    {/* 4色インジケーター */}
                    <div className="grid grid-cols-4 gap-2">
                      {levelDefs.map(lv => {
                        const isActive = available && level === lv.id;
                        const isSemi   = available && !isActive && level2nd === lv.id;
                        const prob = probMap[lv.id];
                        const cardClass = isActive ? lv.active : isSemi ? lv.semi : lv.inactive;
                        const textClass = isActive ? lv.text : isSemi ? lv.textSemi : "text-gray-600";
                        return (
                          <div key={lv.id} className={`rounded-lg p-3 text-center space-y-1.5 ${cardClass}`}>
                            <p className={`text-xs font-bold ${textClass}`}>{lv.label}</p>
                            <p className={`text-xl font-bold ${textClass}`}>
                              {available && prob != null ? `${(prob * 100).toFixed(0)}%` : "—"}
                            </p>
                            {available && prob != null && (
                              <div className="w-full bg-gray-700 rounded-full h-1">
                                <div className={`${lv.bar} h-1 rounded-full`} style={{ width: `${prob * 100}%` }} />
                              </div>
                            )}
                            <p className="text-xs text-gray-500">{lv.range}</p>
                          </div>
                        );
                      })}
                    </div>
                    {!available && (
                      <p className="text-xs text-gray-500 text-center">ML データ未取得</p>
                    )}
                  </>
                );
              })()}

              {(() => {
                const ml = data.ml_prediction;
                const hasMl = Boolean(ml?.available && ml?.prob_blue_binary != null);
                const p20hist = data.prob_2_0x?.current ?? 0;

                // 直前倍率によるRed後補正
                const lastMult = data.chart_data?.at(-1)?.value ?? 0;
                const afterExplosion = lastMult > 100;  // 爆発(>100x)直後 → Blue率0.433 ↓
                const afterRed       = lastMult > 10 && !afterExplosion; // Red直後 → Blue率0.582 ↑

                // 確率遷移MACDによる判定
                const probHistory = data.prob_2_0x?.history ?? [];
                const probMacd = probMacdSignal(probHistory);  // fast=3,slow=8,sig=3
                const macdReady = probHistory.length >= 11; // slow+sig-1=10

                // 連続Blue数（ファストトリガー）
                const blueStreak = data.no_entry?.low_consecutive_count ?? 0;
                const streakWarn = blueStreak >= 5; // 4回を超えたら（5回目以降）警告

                // RSI 判定（移動平均ベース RSI < 30 → 売られすぎ → 危険）
                const currentRsi = data.rsi?.current ?? null;
                const rsiWarn = currentRsi !== null && currentRsi < 30;

                // warn判定: 爆発直後は逆に安全(Blue率↓) / Red直後は危険(Blue率↑) / RSI<30 / 連続Blue / MACD / 窓内60%
                const warn20 = afterExplosion
                  ? false // 爆発(>100x)直後 Blue率↓43% → 安全 → 強制「買い」
                  : afterRed
                    ? true  // Red(10-100x)直後 Blue率↑58% → 危険 → 非推奨
                    : rsiWarn
                      ? true  // RSI<30 → 売られすぎ → 危険
                      : streakWarn
                        ? true
                        : macdReady
                          ? probMacd.state === "warn" || p20hist >= 0.60
                          : p20hist >= 0.60 || (hasMl && Boolean(ml?.skip_recommended));

                // 理由テキスト
                const reasons: string[] = [];
                if (afterExplosion) {
                  reasons.push(`爆発直後(${lastMult.toFixed(2)}x) Blue率↓43% → 安全`);
                } else if (afterRed) {
                  reasons.push(`Red直後(${lastMult.toFixed(2)}x) Blue率↑58% → 危険`);
                }
                if (rsiWarn) {
                  reasons.push(`RSI ${currentRsi!.toFixed(1)} → 売られすぎ 危険`);
                }
                if (streakWarn) {
                  reasons.push(`連続Blue ${blueStreak}回 → 転換警戒`);
                }
                if (macdReady) {
                  if (probMacd.state === "warn") reasons.push("確率MACD ゴールデンクロス");
                  else if (probMacd.state === "buy") reasons.push("確率MACD デッドクロス");
                  else reasons.push("確率MACD ニュートラル");
                } else {
                  reasons.push(hasMl ? "しきい値判定（ML）" : "しきい値判定（履歴）");
                }
                if (p20hist >= 0.60) reasons.push(`窓内Blue率 ${(p20hist * 100).toFixed(0)}%`);

                const leftCard = warn20
                  ? "bg-red-950 border border-red-800"
                  : "bg-green-950 border border-green-800";
                const leftTone = warn20 ? "text-red-300" : "text-green-300";

                // ── 1.20以下 判定 ──────────────────────────────────
                const p12hist = data.prob_1_2x?.current ?? 0;
                const probHistory12 = data.prob_1_2x?.history ?? [];
                const probMacd12 = probMacdSignal(probHistory12);
                const macdReady12 = probHistory12.length >= 11;

                // warn: Red直後は危険 / RSI<30 / 窓内25%超 OR MACD上昇 / 爆発直後は安全
                const warn12 = afterExplosion
                  ? false // 爆発直後は2.0x同様に安全 → 強制「安全圏」
                  : afterRed
                    ? true  // Red直後は危険
                    : rsiWarn
                      ? true  // RSI<30 → 危険
                      : macdReady12
                        ? probMacd12.state === "warn" || p12hist >= 0.25
                        : p12hist >= 0.25;

                const reasons12: string[] = [];
                if (afterExplosion) {
                  reasons12.push(`爆発直後(${lastMult.toFixed(2)}x) 安全`);
                } else if (afterRed) {
                  reasons12.push(`Red直後(${lastMult.toFixed(2)}x) 危険`);
                }
                if (rsiWarn) {
                  reasons12.push(`RSI ${currentRsi!.toFixed(1)} → 売られすぎ 危険`);
                }
                if (macdReady12) {
                  if (probMacd12.state === "warn") reasons12.push("確率MACD 上昇トレンド");
                  else if (probMacd12.state === "buy") reasons12.push("確率MACD 下降トレンド");
                  else reasons12.push("確率MACD ニュートラル");
                }
                if (p12hist >= 0.25) reasons12.push(`窓内即死率 ${(p12hist * 100).toFixed(0)}%`);

                const rightCard = warn12
                  ? "bg-orange-950 border border-orange-800"
                  : "bg-green-950 border border-green-800";
                const rightTone = warn12 ? "text-orange-300" : "text-green-300";

                return (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className={`rounded-lg px-3 py-3 space-y-2 ${leftCard}`}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-gray-200">2.00以下 警告</p>
                        <span className="text-[10px] px-2 py-0.5 rounded bg-blue-900 text-blue-200 border border-blue-700">第一段階</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className={`text-base font-bold ${leftTone}`}>
                            {warn20 ? "非推奨" : "買い"}
                          </p>
                          <div className="mt-1 space-y-0.5">
                            {reasons.map((r, i) => (
                              <p key={i} className="text-[11px] text-gray-500">{r}</p>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className={`rounded-lg px-3 py-3 space-y-2 ${rightCard}`}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-gray-200">1.20以下 警告</p>
                        <span className="text-[10px] px-2 py-0.5 rounded bg-orange-900 text-orange-200 border border-orange-700">第二段階</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className={`text-base font-bold ${rightTone}`}>
                            {warn12 ? "即死注意" : "安全圏"}
                          </p>
                          <div className="mt-1 space-y-0.5">
                            {reasons12.map((r, i) => (
                              <p key={i} className="text-[11px] text-gray-500">{r}</p>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          </section>
        );
      })()}

      {/* Charts with tab switcher */}
      {data?.ready && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          {/* Tab bar */}
          <div className="flex gap-1 border-b border-gray-700 pb-2">
            {(
              [
                { key: "prob",       label: "確率遷移" },
                { key: "prob_macd",  label: "確率MACD" },
                { key: "multiplier", label: "倍率履歴" },
                { key: "rsi",        label: "RSI" },
                { key: "macd",       label: "MACD" },
              ] as { key: ChartTab; label: string }[]
            ).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-3 py-1 text-xs rounded-t transition-colors ${
                  activeTab === key
                    ? "bg-gray-700 text-white font-semibold"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Probability */}
          {activeTab === "prob" && data.prob_2x && data.prob_5x && data.prob_10x && (
            <div className="space-y-3">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex gap-4 text-xs text-gray-400">
                  {data.prob_1_2x && <span><span className="text-slate-400 font-bold">■</span> 1.2x以下 {pct(data.prob_1_2x.current)}</span>}
                  {data.prob_2_0x && <span><span className="text-orange-400 font-bold">■</span> 2.0x以下 {pct(data.prob_2_0x.current)}</span>}
                  <span><span className="text-green-400 font-bold">■</span> 2x以上 {pct(data.prob_2x.current)}</span>
                  <span><span className="text-yellow-400 font-bold">■</span> 5x以上 {pct(data.prob_5x.current)}</span>
                  <span><span className="text-red-400 font-bold">■</span> 10x以上 {pct(data.prob_10x.current)}</span>
                </div>
              </div>
              <ProbChart data={data} />
            </div>
          )}

          {/* Prob MACD */}
          {activeTab === "prob_macd" && (
            <div className="space-y-3">
              <div className="flex gap-4 text-xs text-gray-400">
                <span><span className="text-orange-400 font-bold">■</span> 2.0x以下 MACD</span>
                <span><span className="text-slate-400 font-bold">■</span> 1.2x以下 MACD</span>
                <span><span className="text-gray-500 font-bold">──</span> ゼロライン</span>
              </div>
              <ProbMacdChart data={data} />
            </div>
          )}

          {/* Multiplier + Bollinger */}
          {activeTab === "multiplier" && data.chart_data && data.chart_data.length > 0 && (
            <div className="space-y-3">
              <div className="flex gap-4 text-xs text-gray-400">
                <span><span className="text-blue-400 font-bold">■</span> 倍率（対数スケール）</span>
                <span><span className="text-gray-400 font-bold">--</span> ボリンジャーバンド</span>
              </div>
              <MultiplierChart data={data} />
            </div>
          )}

          {/* RSI */}
          {activeTab === "rsi" && data.rsi && (
            <div className="space-y-3">
              <div className="flex gap-4 text-xs text-gray-400">
                <span className="text-gray-300">{data.rsi.period}期間・移動平均ベース</span>
                <span className="text-red-400">── 70 過買い</span>
                <span className="text-blue-400">── 30 過売り</span>
                {data.rsi.current != null && (
                  <span className="text-purple-400 font-bold ml-auto">現在 {data.rsi.current.toFixed(1)}</span>
                )}
              </div>
              {data.rsi.chart.some((v) => v !== null)
                ? <RsiChart rsi={data.rsi.chart} />
                : <p className="text-sm text-gray-500 py-8 text-center">
                    データ不足（{rsiNeeded}件以上必要、現在 {data.total_rounds} 件）
                  </p>}
            </div>
          )}

          {/* MACD */}
          {activeTab === "macd" && data.macd && (
            <div className="space-y-3">
              <div className="flex gap-4 text-xs text-gray-400">
                <span className="text-gray-300">{data.macd.fast}/{data.macd.slow}/{data.macd.signal_period}・移動平均ベース</span>
                <span><span className="text-blue-400 font-bold">─</span> MACD</span>
                <span><span className="text-yellow-400 font-bold">--</span> シグナル</span>
                <span><span className="text-green-400 font-bold">■</span> ヒストグラム</span>
              </div>
              {data.macd.chart.some((p) => p !== null)
                ? <MacdChart macd={data.macd.chart} />
                : <p className="text-sm text-gray-500 py-8 text-center">
                    データ不足（{macdNeeded}件以上必要、現在 {data.total_rounds} 件）
                  </p>}
            </div>
          )}
        </section>
      )}

      {/* Metrics */}
      {data?.ready && (
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "移動平均",  value: data.moving_avg != null ? fmt(data.moving_avg) : "—" },
            { label: "中央値",    value: data.median     != null ? fmt(data.median)     : "—" },
            { label: "標準偏差",  value: data.std_dev    != null ? fmt(data.std_dev)    : "—" },
            { label: "ATR",      value: data.atr         != null ? fmt(data.atr)        : "—" },
            { label: "最大値",   value: data.max         != null ? fmt(data.max)        : "—" },
            { label: "最小値",   value: data.min         != null ? fmt(data.min)        : "—" },
            { label: "BB上限",   value: data.bollinger_bands?.current ? fmt(data.bollinger_bands.current.upper) : "—" },
            { label: "BB下限",   value: data.bollinger_bands?.current ? fmt(data.bollinger_bands.current.lower) : "—" },
          ].map(({ label, value }) => (
            <div key={label} className="bg-gray-900 rounded-xl p-3">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-lg font-bold text-white">{value}</p>
            </div>
          ))}
        </section>
      )}

      {/* Round history */}
      {rounds.length > 0 && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <h2 className="text-sm font-semibold text-gray-300">入力履歴（新しい順）</h2>
          <div className="grid grid-cols-6 gap-2">
            {rounds.map((r) => {
              const evalResult = evalArchive[String(r.id)];
              const canShowEval = Boolean(data?.ml_prediction?.available);
              return (
                <span
                  key={r.id}
                  title={canShowEval && evalResult
                    ? `${evalResult.label} / 実績:${r.multiplier.toFixed(2)}`
                    : "予測比較なし"}
                  className={`px-2 py-0.5 rounded text-xs font-mono font-semibold text-center flex items-center justify-center gap-1 ${multiplierBadgeClass(r.multiplier)}`}
                >
                  <span>{r.multiplier % 1 === 0 ? r.multiplier.toFixed(0) : r.multiplier}</span>
                  {canShowEval && evalResult && (
                    evalResult.verdict === "miss"
                      ? <span className={`inline-block w-2.5 h-2.5 rounded-full ${predictedBandDotClass(evalResult.predicted_band)}`} aria-hidden="true" />
                      : <span>{evalResult.emoji}</span>
                  )}
                </span>
              );
            })}
          </div>
          <div className="flex gap-3 text-xs text-gray-600">
            <span><span className="inline-block w-2 h-2 rounded-sm bg-blue-600 mr-1"/>1x台</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-green-600 mr-1"/>2x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-yellow-500 mr-1"/>5x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-red-700 mr-1"/>10x以上</span>
          </div>
          {data?.ml_prediction?.available ? (
            <div className="flex gap-3 text-xs text-gray-500">
              <span>✅ 的中（予測帯と実績帯が一致）</span>
              <span>● ハズレ（予測帯の色を表示）</span>
            </div>
          ) : (
            <div className="text-xs text-gray-500">予測未提供（ML準備中）のため判定マークは非表示</div>
          )}
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-950/60">
            <div className="flex flex-col gap-3 border-b border-gray-800 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-200">予測収支シミュレーション</p>
                <p className="text-xs text-gray-500">直近表示ラウンドベース。収支 = -コイン x 予測件数 + コイン x 最低倍率 x (的中件数 + オーバー)</p>
              </div>
              <div className="flex items-center gap-2">
                {COIN_OPTIONS.map((coin) => (
                  <button
                    key={coin}
                    type="button"
                    onClick={() => setSelectedCoinSize(coin)}
                    className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                      selectedCoinSize === coin
                        ? "bg-cyan-500 text-slate-950"
                        : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    {coin}コイン
                  </button>
                ))}
              </div>
            </div>
            <table className="min-w-full text-sm text-gray-200">
              <thead className="bg-gray-800/80 text-gray-300">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">予測色</th>
                  <th className="px-3 py-2 text-right font-medium">最低倍率</th>
                  <th className="px-3 py-2 text-right font-medium">予測件数</th>
                  <th className="px-3 py-2 text-right font-medium">的中件数</th>
                  <th className="px-3 py-2 text-right font-medium">オーバー</th>
                  <th className="px-3 py-2 text-right font-medium">的中率</th>
                  <th className="px-3 py-2 text-right font-medium">収支</th>
                </tr>
              </thead>
              <tbody>
                {predictionSimulation.map((row) => (
                  <tr key={row.band} className="border-t border-gray-800">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className={`inline-block h-2.5 w-2.5 rounded-full ${predictedBandDotClass(row.band)}`} aria-hidden="true" />
                        <span>{bandLabelJa(row.band)}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(MIN_PAYOUT_MULTIPLIER[row.band])}x</td>
                    <td className="px-3 py-2 text-right font-mono">{row.predictedCount}</td>
                    <td className="px-3 py-2 text-right font-mono">{row.hitCount}</td>
                    <td className="px-3 py-2 text-right font-mono">{row.overCount ?? "-"}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {row.hitRate === null ? "-" : `${row.hitRate.toFixed(1)}%`}
                    </td>
                    <td className={`px-3 py-2 text-right font-mono font-semibold ${row.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {row.pnl >= 0 ? "+" : ""}{fmt(row.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-gray-700 bg-gray-900/70">
                <tr>
                  <td className="px-3 py-2 font-semibold text-gray-200">合計</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">-</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionHitCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionOverCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">
                    {totalPredictionHitRate === null ? "-" : `${totalPredictionHitRate.toFixed(1)}%`}
                  </td>
                  <td className={`px-3 py-2 text-right font-mono font-bold ${totalPredictionPnL >= 0 ? "text-green-300" : "text-red-300"}`}>
                    {totalPredictionPnL >= 0 ? "+" : ""}{fmt(totalPredictionPnL)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
