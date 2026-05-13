"use client";

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL;
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
  rsi?: { current: number | null; chart: (number | null)[] };
  macd?: { chart: (MacdPoint | null)[] };
  bollinger_bands?: { current: BB | null; chart: (BB | null)[] };
  chart_data?: { index: number; value: number }[];
  analyzed_at?: string;
};

// ── SVG helpers ─────────────────────────────────────────────────────────────

const PW = 560; const PH = 180; // plot area
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
  const clamped = Math.max(1.01, Math.min(501, v));
  return MT + PH - ((Math.log10(clamped) - lo) / (hi - lo)) * PH;
}

function toPath(pts: (readonly [number, number] | null)[]) {
  let d = "";
  let open = false;
  for (const p of pts) {
    if (!p) { open = false; continue; }
    d += open ? ` L${p[0].toFixed(1)},${p[1].toFixed(1)}` : `M${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    open = true;
  }
  return d;
}

function pct(v: number) { return `${(v * 100).toFixed(1)}%`; }
function fmt(v: number) { return v % 1 === 0 ? v.toString() : v.toFixed(2); }

// ── Probability Transition Chart ─────────────────────────────────────────────

function ProbChart({ data }: { data: AnalysisData }) {
  const h2 = data.prob_2x!.history;
  const h5 = data.prob_5x!.history;
  const h10 = data.prob_10x!.history;
  const n = h2.length;

  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  const pathOf = (arr: number[], color: string) => (
    <path
      d={toPath(arr.map((v, i) => [xOf(i, n), yLinear(v, 0, 1)] as const))}
      fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round"
    />
  );

  const labelOf = (arr: number[], color: string) => {
    const x = xOf(n - 1, n);
    const y = yLinear(arr[arr.length - 1], 0, 1);
    return (
      <text x={x + 4} y={y + 4} fill={color} fontSize="10" fontWeight="bold">
        {pct(arr[arr.length - 1])}
      </text>
    );
  };

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {/* Y grid + labels */}
      {yTicks.map((t) => {
        const y = yLinear(t, 0, 1);
        return (
          <g key={t}>
            <line x1={ML} y1={y} x2={ML + PW} y2={y} stroke="#374151" strokeDasharray="4 2" />
            <text x={ML - 4} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="10">
              {Math.round(t * 100)}%
            </text>
          </g>
        );
      })}
      {pathOf(h2,  "#4ade80")}
      {pathOf(h5,  "#facc15")}
      {pathOf(h10, "#f87171")}
      {n > 0 && labelOf(h2,  "#4ade80")}
      {n > 0 && labelOf(h5,  "#facc15")}
      {n > 0 && labelOf(h10, "#f87171")}
      {/* X axis */}
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

// ── Multiplier + Bollinger Chart ─────────────────────────────────────────────

function MultiplierChart({ data }: { data: AnalysisData }) {
  const cd = data.chart_data!;
  const bb = data.bollinger_bands?.chart ?? [];
  const n = cd.length;

  const logTicks = [1.01, 2, 5, 10, 50, 100, 501];

  const mulPath = toPath(cd.map((d, i) => [xOf(i, n), yLog(d.value)] as const));
  const bbUpper = toPath(bb.map((b, i) => b ? [xOf(i, n), yLog(b.upper)] as const : null));
  const bbMid   = toPath(bb.map((b, i) => b ? [xOf(i, n), yLog(b.middle)] as const : null));
  const bbLower = toPath(bb.map((b, i) => b ? [xOf(i, n), Math.max(MT, yLog(Math.max(b.lower, 1.01)))] as const : null));

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {/* Y grid + labels (log scale) */}
      {logTicks.map((t) => {
        const y = yLog(t);
        if (y < MT || y > MT + PH) return null;
        return (
          <g key={t}>
            <line x1={ML} y1={y} x2={ML + PW} y2={y} stroke="#374151" strokeDasharray="4 2" />
            <text x={ML - 4} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{t}</text>
          </g>
        );
      })}
      {/* Bollinger Bands */}
      <path d={bbUpper} fill="none" stroke="#6b7280" strokeWidth="1" strokeDasharray="4 3" />
      <path d={bbMid}   fill="none" stroke="#9ca3af" strokeWidth="1" strokeDasharray="4 3" />
      <path d={bbLower} fill="none" stroke="#6b7280" strokeWidth="1" strokeDasharray="4 3" />
      {/* Multiplier line */}
      <path d={mulPath} fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinejoin="round" />
      {/* X axis */}
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

// ── RSI Chart ────────────────────────────────────────────────────────────────

function RsiChart({ rsi }: { rsi: (number | null)[] }) {
  const n = rsi.length;
  const refLines = [30, 50, 70];

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {refLines.map((r) => {
        const y = yLinear(r, 0, 100);
        return (
          <g key={r}>
            <line
              x1={ML} y1={y} x2={ML + PW} y2={y}
              stroke={r === 50 ? "#4b5563" : r === 70 ? "#ef4444" : "#3b82f6"}
              strokeDasharray="4 2" strokeOpacity="0.6"
            />
            <text x={ML - 4} y={y + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{r}</text>
          </g>
        );
      })}
      <path
        d={toPath(rsi.map((v, i) => v != null ? [xOf(i, n), yLinear(v, 0, 100)] as const : null))}
        fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinejoin="round"
      />
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

// ── MACD Chart ────────────────────────────────────────────────────────────────

function MacdChart({ macd }: { macd: (MacdPoint | null)[] }) {
  const n = macd.length;
  const values = macd.flatMap((p) =>
    p ? [p.macd, p.signal ?? p.macd, p.histogram ?? 0] : []
  );
  if (values.length === 0) return null;
  const yMin = Math.min(...values);
  const yMax = Math.max(...values);
  const pad = (yMax - yMin) * 0.1 || 0.1;
  const lo = yMin - pad;
  const hi = yMax + pad;
  const yM = (v: number) => yLinear(v, lo, hi);
  const zero = yM(0);

  const barW = Math.max(1, (PW / n) * 0.6);

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-auto">
      {/* Zero line */}
      <line x1={ML} y1={zero} x2={ML + PW} y2={zero} stroke="#4b5563" strokeDasharray="4 2" />
      <text x={ML - 4} y={zero + 4} textAnchor="end" fill="#9ca3af" fontSize="10">0</text>
      {/* Histogram bars */}
      {macd.map((p, i) => {
        if (!p || p.histogram == null) return null;
        const x = xOf(i, n);
        const y1 = Math.min(yM(p.histogram), zero);
        const y2 = Math.max(yM(p.histogram), zero);
        return (
          <rect
            key={i} x={x - barW / 2} y={y1} width={barW} height={Math.max(1, y2 - y1)}
            fill={p.histogram >= 0 ? "#4ade80" : "#f87171"} opacity="0.5"
          />
        );
      })}
      {/* MACD line */}
      <path
        d={toPath(macd.map((p, i) => p ? [xOf(i, n), yM(p.macd)] as const : null))}
        fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinejoin="round"
      />
      {/* Signal line */}
      <path
        d={toPath(macd.map((p, i) => (p?.signal != null) ? [xOf(i, n), yM(p.signal)] as const : null))}
        fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeLinejoin="round" strokeDasharray="5 3"
      />
      <line x1={ML} y1={MT + PH} x2={ML + PW} y2={MT + PH} stroke="#4b5563" />
      <text x={ML} y={VH} fill="#6b7280" fontSize="10">1</text>
      <text x={ML + PW} y={VH} textAnchor="end" fill="#6b7280" fontSize="10">{n}</text>
    </svg>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [error, setError] = useState(false);
  const fetchRef = useRef(false);

  const fetchData = async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis`);
      if (!res.ok) { setError(true); return; }
      setData(await res.json() as AnalysisData);
      setError(false);
    } catch {
      setError(true);
    }
  };

  useEffect(() => {
    if (fetchRef.current) return;
    fetchRef.current = true;
    fetchData();
    const t = setInterval(fetchData, POLL_INTERVAL);
    return () => clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const remaining = data ? Math.max(0, READY_THRESHOLD - data.total_rounds) : null;

  return (
    <main className="min-h-screen p-4 md:p-8 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Rocket Analysis</h1>
        <a href="/input" className="text-sm text-gray-400 hover:text-white transition-colors">
          入力画面 →
        </a>
      </div>

      {/* Status bar */}
      {!data && !error && (
        <p className="text-gray-400 text-sm">読み込み中...</p>
      )}
      {error && (
        <p className="text-red-400 text-sm">データ取得に失敗しました。</p>
      )}
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
              <p className="text-xs text-gray-500">
                {new Date(data.analyzed_at).toLocaleTimeString("ja-JP")}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Probability transition chart */}
      {data?.ready && data.prob_2x && data.prob_5x && data.prob_10x && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
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

      {/* Multiplier + Bollinger chart */}
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
            <h2 className="text-sm font-semibold text-gray-300">RSI（14期間）</h2>
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
            : <p className="text-sm text-gray-500 py-4 text-center">データ不足（15件以上必要、現在 {data.total_rounds} 件）</p>}
        </section>
      )}

      {/* MACD */}
      {data?.ready && data.macd && (
        <section className="bg-gray-900 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-gray-300">MACD（12/26/9）</h2>
            <div className="flex gap-4 text-xs text-gray-400">
              <span><span className="text-blue-400 font-bold">─</span> MACD</span>
              <span><span className="text-yellow-400 font-bold">--</span> シグナル</span>
              <span><span className="text-green-400 font-bold">■</span> ヒストグラム</span>
            </div>
          </div>
          {data.macd.chart.some((p) => p !== null)
            ? <MacdChart macd={data.macd.chart} />
            : <p className="text-sm text-gray-500 py-4 text-center">データ不足（35件以上必要、現在 {data.total_rounds} 件）</p>}
        </section>
      )}

      {/* Metrics */}
      {data?.ready && (
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "移動平均",   value: data.moving_avg != null ? fmt(data.moving_avg) : "—" },
            { label: "中央値",     value: data.median     != null ? fmt(data.median)     : "—" },
            { label: "標準偏差",   value: data.std_dev    != null ? fmt(data.std_dev)    : "—" },
            { label: "ATR",       value: data.atr         != null ? fmt(data.atr)        : "—" },
            { label: "最大値",    value: data.max         != null ? fmt(data.max)        : "—" },
            { label: "最小値",    value: data.min         != null ? fmt(data.min)        : "—" },
            { label: "BB上限",    value: data.bollinger_bands?.current ? fmt(data.bollinger_bands.current.upper)  : "—" },
            { label: "BB下限",    value: data.bollinger_bands?.current ? fmt(data.bollinger_bands.current.lower)  : "—" },
          ].map(({ label, value }) => (
            <div key={label} className="bg-gray-900 rounded-xl p-3">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-lg font-bold text-white">{value}</p>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
