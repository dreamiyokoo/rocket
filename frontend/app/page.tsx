"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const POLL_INTERVAL = 30_000;
const READY_THRESHOLD = 18;

// ── Types ───────────────────────────────────────────────────────────────────

type BB = { upper: number; middle: number; lower: number };
type MacdPoint = { macd: number; signal: number | null; histogram: number | null };

type AnalysisData = {
  ready: boolean;
  total_rounds: number;
  window: number;
  prob_2x?: { current: number; history: number[] };
  prob_5x?: { current: number; history: number[] };
  prob_10x?: { current: number; history: number[] };
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
  analyzed_at?: string;
};

type Params = { rsi_period: number; macd_fast: number; macd_slow: number; macd_signal: number };
type Round = { id: number; multiplier: number; recorded_at: string };

const DEFAULT_PARAMS: Params = { rsi_period: 14, macd_fast: 12, macd_slow: 26, macd_signal: 9 };

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

// ── Charts ───────────────────────────────────────────────────────────────────

function ProbChart({ data }: { data: AnalysisData }) {
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
      {pathOf(h2, "#4ade80")} {pathOf(h5, "#facc15")} {pathOf(h10, "#f87171")}
      {n > 0 && <>{labelOf(h2, "#4ade80")} {labelOf(h5, "#facc15")} {labelOf(h10, "#f87171")}</>}
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
  const lo = Math.min(...vals) - Math.abs(Math.min(...vals)) * 0.1 - 0.01;
  const hi = Math.max(...vals) + Math.abs(Math.max(...vals)) * 0.1 + 0.01;
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
  if (v >= 10) return "bg-red-700 text-white";
  if (v >= 5)  return "bg-yellow-500 text-black";
  if (v >= 2)  return "bg-green-600 text-white";
  return "bg-blue-600 text-white";
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [data, setData]     = useState<AnalysisData | null>(null);
  const [error, setError]   = useState(false);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [params, setParams] = useState<Params>(DEFAULT_PARAMS);
  const [draft, setDraft]   = useState<Params>(DEFAULT_PARAMS);
  const [showSettings, setShowSettings] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  useEffect(() => {
    fetchData(params);
    fetchRounds();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => { fetchData(params); fetchRounds(); }, POLL_INTERVAL);

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/ws`);
    ws.onmessage = () => { fetchData(params); fetchRounds(); };

    const ch = new BroadcastChannel("rocket:data-changed");
    ch.onmessage = () => { fetchData(params); fetchRounds(); };

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      ws.close();
      ch.close();
    };
  }, [params, fetchData, fetchRounds]);

  const applySettings = () => {
    setParams(draft);
    setShowSettings(false);
  };

  const remaining = data ? Math.max(0, READY_THRESHOLD - data.total_rounds) : null;
  const rsiNeeded  = READY_THRESHOLD + params.rsi_period;
  const macdNeeded = READY_THRESHOLD + params.macd_slow + params.macd_signal - 2;

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
        <div className="bg-gray-900 rounded-xl p-4 flex items-center gap-6">
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
      )}

      {/* Probability transition */}
      {data?.ready && data.prob_2x && data.prob_5x && data.prob_10x && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-gray-300">確率遷移</h2>
            <div className="flex gap-4 text-xs text-gray-400">
              <span><span className="text-green-400 font-bold">■</span> 2x以上 {pct(data.prob_2x.current)}</span>
              <span><span className="text-yellow-400 font-bold">■</span> 5x以上 {pct(data.prob_5x.current)}</span>
              <span><span className="text-red-400 font-bold">■</span> 10x以上 {pct(data.prob_10x.current)}</span>
            </div>
          </div>
          <ProbChart data={data} />
        </section>
      )}

      {/* Multiplier + Bollinger */}
      {data?.ready && data.chart_data && data.chart_data.length > 0 && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-gray-300">倍率履歴（対数スケール）</h2>
            <div className="flex gap-4 text-xs text-gray-400">
              <span><span className="text-blue-400 font-bold">■</span> 倍率</span>
              <span><span className="text-gray-400 font-bold">--</span> ボリンジャーバンド</span>
            </div>
          </div>
          <MultiplierChart data={data} />
        </section>
      )}

      {/* RSI */}
      {data?.ready && data.rsi && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-gray-300">RSI（{data.rsi.period}期間・移動平均ベース）</h2>
            <div className="flex gap-4 text-xs text-gray-400">
              <span className="text-red-400">── 70 過買い</span>
              <span className="text-blue-400">── 30 過売り</span>
              {data.rsi.current != null && (
                <span className="text-purple-400 font-bold">現在 {data.rsi.current.toFixed(1)}</span>
              )}
            </div>
          </div>
          {data.rsi.chart.some((v) => v !== null)
            ? <RsiChart rsi={data.rsi.chart} />
            : <p className="text-sm text-gray-500 py-4 text-center">
                データ不足（{rsiNeeded}件以上必要、現在 {data.total_rounds} 件）
              </p>}
        </section>
      )}

      {/* MACD */}
      {data?.ready && data.macd && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-gray-300">
              MACD（{data.macd.fast}/{data.macd.slow}/{data.macd.signal_period}・移動平均ベース）
            </h2>
            <div className="flex gap-4 text-xs text-gray-400">
              <span><span className="text-blue-400 font-bold">─</span> MACD</span>
              <span><span className="text-yellow-400 font-bold">--</span> シグナル</span>
              <span><span className="text-green-400 font-bold">■</span> ヒストグラム</span>
            </div>
          </div>
          {data.macd.chart.some((p) => p !== null)
            ? <MacdChart macd={data.macd.chart} />
            : <p className="text-sm text-gray-500 py-4 text-center">
                データ不足（{macdNeeded}件以上必要、現在 {data.total_rounds} 件）
              </p>}
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
            {rounds.map((r) => (
              <span
                key={r.id}
                className={`px-2 py-0.5 rounded text-xs font-mono font-semibold text-center ${multiplierBadgeClass(r.multiplier)}`}
              >
                {r.multiplier % 1 === 0 ? r.multiplier.toFixed(0) : r.multiplier}
              </span>
            ))}
          </div>
          <div className="flex gap-3 text-xs text-gray-600">
            <span><span className="inline-block w-2 h-2 rounded-sm bg-blue-600 mr-1"/>1x台</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-green-600 mr-1"/>2x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-yellow-500 mr-1"/>5x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-red-700 mr-1"/>10x以上</span>
          </div>
        </section>
      )}
    </main>
  );
}
