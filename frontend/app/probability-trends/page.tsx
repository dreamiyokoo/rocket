"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

type TrendPoint = {
  bucket: string;
  total: number;
  prob_1_2x: number;
  prob_2_0x: number;
  prob_blue: number;
  prob_green: number;
  prob_yellow: number;
  prob_red: number;
};

type TrendsResponse = {
  timezone: string;
  days: number;
  hourly: TrendPoint[];
  daily: TrendPoint[];
  hourly_stats?: Array<{
    hour: number;
    total: number;
    prob_1_2x: number;
    prob_2_0x: number;
    prob_green: number;
    prob_yellow: number;
    prob_red: number;
  }>;
};

const CHART_W = 900;
const CHART_H = 280;
const MARGIN = { top: 20, right: 20, bottom: 34, left: 42 };
const PLOT_W = CHART_W - MARGIN.left - MARGIN.right;
const PLOT_H = CHART_H - MARGIN.top - MARGIN.bottom;

function xOf(i: number, n: number): number {
  if (n <= 1) return MARGIN.left + PLOT_W / 2;
  return MARGIN.left + (i / (n - 1)) * PLOT_W;
}

function yOf(v: number): number {
  return MARGIN.top + (1 - v) * PLOT_H;
}

function toPath(values: number[]): string {
  if (values.length === 0) return "";
  return values
    .map((v, i) => `${i === 0 ? "M" : "L"}${xOf(i, values.length).toFixed(1)},${yOf(v).toFixed(1)}`)
    .join(" ");
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function timeLabel(iso: string, mode: "hourly" | "daily"): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  if (mode === "daily") return `${mm}/${dd}`;
  const hh = String(d.getHours()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:00`;
}

function TrendChart({
  title,
  points,
  mode,
}: {
  title: string;
  points: TrendPoint[];
  mode: "hourly" | "daily";
}) {
  if (points.length === 0) {
    return (
      <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="mt-4 text-sm text-gray-400">表示できるデータがありません。</p>
      </div>
    );
  }

  const p12 = points.map((p) => p.prob_1_2x);
  const p20 = points.map((p) => p.prob_2_0x);
  const green = points.map((p) => p.prob_green);
  const yellow = points.map((p) => p.prob_yellow);
  const red = points.map((p) => p.prob_red);

  const xLabelIndexes = new Set<number>([
    0,
    Math.max(0, Math.floor((points.length - 1) / 3)),
    Math.max(0, Math.floor(((points.length - 1) * 2) / 3)),
    points.length - 1,
  ]);

  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <span className="text-xs text-gray-400">{points.length}バケット</span>
      </div>

      <div className="mt-4 overflow-x-auto">
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="min-w-[680px] w-full h-auto">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line
                x1={MARGIN.left}
                y1={yOf(t)}
                x2={MARGIN.left + PLOT_W}
                y2={yOf(t)}
                stroke="#334155"
                strokeDasharray="4 4"
              />
              <text x={MARGIN.left - 6} y={yOf(t) + 4} textAnchor="end" fill="#94a3b8" fontSize="11">
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}

          <path d={toPath(p12)} fill="none" stroke="#f97316" strokeWidth="3" />
          <path d={toPath(p20)} fill="none" stroke="#38bdf8" strokeWidth="3" />
          <path d={toPath(green)} fill="none" stroke="#4ade80" strokeWidth="2.5" />
          <path d={toPath(yellow)} fill="none" stroke="#facc15" strokeWidth="2.5" />
          <path d={toPath(red)} fill="none" stroke="#f87171" strokeWidth="2.5" />

          <line
            x1={MARGIN.left}
            y1={MARGIN.top + PLOT_H}
            x2={MARGIN.left + PLOT_W}
            y2={MARGIN.top + PLOT_H}
            stroke="#475569"
          />

          {points.map((p, i) => {
            if (!xLabelIndexes.has(i)) return null;
            return (
              <text
                key={i}
                x={xOf(i, points.length)}
                y={MARGIN.top + PLOT_H + 16}
                textAnchor="middle"
                fill="#94a3b8"
                fontSize="10"
              >
                {timeLabel(p.bucket, mode)}
              </text>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs">
        <span className="text-orange-300">1.2以下: {pct(p12[p12.length - 1])}</span>
        <span className="text-cyan-300">2.0以下: {pct(p20[p20.length - 1])}</span>
        <span className="text-green-300">Green(2.01-5.0): {pct(green[green.length - 1])}</span>
        <span className="text-yellow-300">Yellow(5.01-10.0): {pct(yellow[yellow.length - 1])}</span>
        <span className="text-red-300">Red({">"}10.0): {pct(red[red.length - 1])}</span>
      </div>
    </div>
  );
}

function HourlyCountBarChart({
  stats,
}: {
  stats: Array<{ hour: number; sample: number }>;
}) {
  if (stats.length === 0) {
    return <p className="text-sm text-gray-500">表示できるデータがありません。</p>;
  }

  const maxSample = Math.max(...stats.map((s) => s.sample), 1);

  return (
    <div>
      <div className="flex items-end gap-1 h-44 rounded-xl border border-gray-800 bg-gray-950/40 p-3 overflow-x-auto">
        {stats.map((s) => {
          const h = Math.max(2, Math.round((s.sample / maxSample) * 140));
          return (
            <div key={s.hour} className="flex flex-col items-center min-w-[24px] gap-1">
              <div className="text-[9px] text-gray-400 leading-none">{s.sample.toLocaleString()}</div>
              <div
                className="w-4 rounded-t bg-cyan-400/80"
                style={{ height: `${h}px` }}
                title={`${String(s.hour).padStart(2, "0")}:00 ${s.sample.toLocaleString()}件`}
              />
              <div className="text-[10px] text-gray-500">{String(s.hour).padStart(2, "0")}</div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-gray-500">時間帯ごとの件数（全データ/JST）</p>
    </div>
  );
}

export default function ProbabilityTrendsPage() {
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TrendsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_URL}/api/v1/rounds/probability-trends?days=${days}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json = (await res.json()) as TrendsResponse;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "failed to fetch");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [days]);

  const summary = useMemo(() => {
    if (!data || data.daily.length === 0) return null;
    const last = data.daily[data.daily.length - 1];
    return {
      date: timeLabel(last.bucket, "daily"),
      total: last.total,
      p12: pct(last.prob_1_2x),
      p20: pct(last.prob_2_0x),
      green: pct(last.prob_green),
      yellow: pct(last.prob_yellow),
      red: pct(last.prob_red),
    };
  }, [data]);

  const hourlyStats = useMemo(() => {
    if (!data || !data.hourly_stats || data.hourly_stats.length === 0) return [] as Array<{
      hour: number;
      sample: number;
      p12: number;
      p20: number;
      green: number;
      yellow: number;
      red: number;
    }>;

    return data.hourly_stats.map((row) => ({
      hour: row.hour,
      sample: row.total,
      p12: row.prob_1_2x,
      p20: row.prob_2_0x,
      green: row.prob_green,
      yellow: row.prob_yellow,
      red: row.prob_red,
    }));
  }, [data]);

  return (
    <main className="min-h-screen max-w-6xl mx-auto p-4 md:p-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white">確率推移ダッシュボード</h1>
          <p className="text-sm text-gray-400 mt-1">時間別・日別に Blue/Green/Yellow/Red の構成比を可視化</p>
        </div>
        <Link href="/" className="text-sm text-cyan-300 hover:text-cyan-200">← メインへ戻る</Link>
      </div>

      <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-4 flex flex-wrap items-center gap-3">
        <label className="text-sm text-gray-300">集計期間</label>
        {[7, 14, 30, 60, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
              days === d
                ? "bg-cyan-600 text-white border-cyan-500"
                : "bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700"
            }`}
          >
            {d}日
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-500">timezone: UTC</span>
      </div>

      {loading && <p className="text-gray-400">読み込み中...</p>}
      {error && <p className="text-red-300">取得失敗: {error}</p>}

      {!loading && !error && data && (
        <>
          {summary && (
            <div className="grid grid-cols-2 md:grid-cols-8 gap-3 text-sm">
              <div className="rounded-xl border border-gray-800 bg-gray-900/70 p-3 md:col-span-2">
                <p className="text-gray-500">最新日</p>
                <p className="text-white font-semibold">{summary.date}</p>
                <p className="text-gray-400 text-xs mt-1">サンプル数: {summary.total}</p>
              </div>
              <div className="rounded-xl border border-orange-900/50 bg-orange-950/30 p-3 text-orange-200">1.2以下 {summary.p12}</div>
              <div className="rounded-xl border border-cyan-900/50 bg-cyan-950/30 p-3 text-cyan-200">2.0以下 {summary.p20}</div>
              <div className="rounded-xl border border-green-900/50 bg-green-950/40 p-3 text-green-200">Green {summary.green}</div>
              <div className="rounded-xl border border-yellow-900/50 bg-yellow-950/30 p-3 text-yellow-200">Yellow {summary.yellow}</div>
              <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-3 text-red-200">Red {summary.red}</div>
            </div>
          )}

          <TrendChart title="時間別 確率推移" points={data.hourly} mode="hourly" />

          <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-white">時間帯別 確率統計</h2>
              <span className="text-xs text-gray-400">0〜23時集計（全データ / JST）</span>
            </div>

            <div className="mt-4">
              <HourlyCountBarChart stats={hourlyStats.map((row) => ({ hour: row.hour, sample: row.sample }))} />
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-xs md:text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-gray-300">
                    <th className="px-2 py-2 text-left">時刻</th>
                    <th className="px-2 py-2 text-right">件数</th>
                    <th className="px-2 py-2 text-right text-orange-300">1.2以下</th>
                    <th className="px-2 py-2 text-right text-cyan-300">2.0以下</th>
                    <th className="px-2 py-2 text-right text-green-300">Green</th>
                    <th className="px-2 py-2 text-right text-yellow-300">Yellow</th>
                    <th className="px-2 py-2 text-right text-red-300">Red</th>
                  </tr>
                </thead>
                <tbody>
                  {hourlyStats.map((row) => (
                    <tr key={row.hour} className="border-b border-gray-800/80 text-gray-200">
                      <td className="px-2 py-1.5">{String(row.hour).padStart(2, "0")}:00</td>
                      <td className="px-2 py-1.5 text-right text-gray-300">{row.sample.toLocaleString()}</td>
                      <td className="px-2 py-1.5 text-right text-orange-200">{pct(row.p12)}</td>
                      <td className="px-2 py-1.5 text-right text-cyan-200">{pct(row.p20)}</td>
                      <td className="px-2 py-1.5 text-right text-green-200">{pct(row.green)}</td>
                      <td className="px-2 py-1.5 text-right text-yellow-200">{pct(row.yellow)}</td>
                      <td className="px-2 py-1.5 text-right text-red-200">{pct(row.red)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <TrendChart title="日別 確率推移" points={data.daily} mode="daily" />
        </>
      )}
    </main>
  );
}
