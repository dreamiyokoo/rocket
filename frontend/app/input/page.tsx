"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clearAccessToken, getValidAccessToken } from "../lib/auth";
import {
  bandLabel,
  bandLabelJa,
  buildEvalArchive,
  buildPredictionSummary,
  type EvalStatsResponse,
  type PredictedBand,
  type RoundEval,
  type RoundEvalArchive,
} from "../lib/evals";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const READY_THRESHOLD = 18;
const PREVIEW_POLL_INTERVAL = 3_000;

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

type Round = { id: number; multiplier: number; recorded_at: string };
type AnalysisStatus = { total_rounds: number; ready: boolean; mlAvailable: boolean } | null;
type CapturePreview = {
  captured_at: string;
  bar_image: string;
  mask_image: string;
  raw_text: string;
  values: number[];
  scale: number;
};

function bandFromMultiplier(v: number): PredictedBand {
  if (v > 10.0) return "red";
  if (v > 5.0) return "yellow";
  if (v > 2.0) return "green";
  return "blue";
}

function judgePrediction(actual: number, predictedBand: PredictedBand): RoundEval {
  const actualBand = bandFromMultiplier(actual);
  if (actualBand === predictedBand) {
    return {
      predicted_band: predictedBand,
      actual_band: actualBand,
      actual,
      verdict: "hit",
      emoji: "✅",
      label: `的中（予測:${bandLabel(predictedBand)} / 実績:${bandLabel(actualBand)}）`,
      evaluated_at: new Date().toISOString(),
    };
  }
  return {
    predicted_band: predictedBand,
    actual_band: actualBand,
    actual,
    verdict: "miss",
    emoji: "❌",
    label: `ハズレ（予測:${bandLabel(predictedBand)} / 実績:${bandLabel(actualBand)}）`,
    evaluated_at: new Date().toISOString(),
  };
}

export default function InputPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [text, setText] = useState("");
  const [validationError, setValidationError] = useState("");
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resettingEvals, setResettingEvals] = useState(false);
  const [status, setStatus] = useState<AnalysisStatus>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [preview, setPreview] = useState<CapturePreview | null>(null);
  const [evalArchive, setEvalArchive] = useState<RoundEvalArchive>({});
  const [evalStats, setEvalStats] = useState<EvalStatsResponse | null>(null);
  const broadcastRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    broadcastRef.current = new BroadcastChannel("rocket:data-changed");
    return () => { broadcastRef.current?.close(); };
  }, []);

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const handleUnauthorized = useCallback(() => {
    clearAccessToken();
    router.replace("/login");
  }, [router]);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis`);
      if (!res.ok) return;
      const data = await res.json() as {
        total_rounds: number;
        ready: boolean;
        ml_prediction?: { available?: boolean };
      };
      setStatus({
        total_rounds: data.total_rounds,
        ready: data.ready,
        mlAvailable: Boolean(data.ml_prediction?.available),
      });
    } catch {
      // best-effort
    }
  }, []);

  const fetchRounds = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds?limit=72`);
      if (!res.ok) return;
      const data = await res.json() as { rounds: Round[] };
      setRounds(data.rounds);
    } catch {
      // best-effort
    }
  }, []);

  const fetchEvalStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/evals/stats`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json() as EvalStatsResponse;
      setEvalStats(data);
      setEvalArchive(buildEvalArchive(data.recent, { missEmoji: "❌", labelSeparator: " / " }));
    } catch {
      // best-effort
    }
  }, []);

  const fetchPreview = useCallback(async () => {
    const token = getValidAccessToken();
    if (!token) return;

    try {
      const res = await fetch(`${API_URL}/api/v1/capture/preview`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (res.status === 401) {
        handleUnauthorized();
        return;
      }
      if (res.status === 404) {
        setPreview(null);
        return;
      }
      if (!res.ok) return;
      const data = await res.json() as CapturePreview;
      setPreview(data);
    } catch {
      // best-effort
    }
  }, [handleUnauthorized]);

  useEffect(() => {
    const token = getValidAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setCheckingAuth(false);
    fetchStatus();
    fetchRounds();
    fetchEvalStats();
    fetchPreview();
  }, [router, fetchStatus, fetchRounds, fetchEvalStats, fetchPreview]);

  useEffect(() => {
    if (checkingAuth) return;

    const timer = setInterval(() => {
      fetchPreview();
    }, PREVIEW_POLL_INTERVAL);

    return () => {
      clearInterval(timer);
    };
  }, [checkingAuth, fetchPreview]);

  const parseValues = (): { values: number[] } | { error: string } => {
    const lines = text.split("\n").map((s) => s.trim()).filter(Boolean);
    if (lines.length === 0) return { error: "1行以上の値を入力してください。" };
    const values: number[] = [];
    for (const line of lines) {
      const n = Number(line);
      if (isNaN(n)) return { error: `「${line}」は数値ではありません。` };
      if (n <= 0) return { error: `「${line}」は0より大きい値を入力してください。` };
      values.push(n);
    }
    return { values };
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setValidationError("");

    const parsed = parseValues();
    if ("error" in parsed) {
      setValidationError(parsed.error);
      return;
    }

    const token = getValidAccessToken();
    if (!token) { router.replace("/login"); return; }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ values: parsed.values }),
      });
      if (!res.ok) {
        if (res.status === 401) {
          handleUnauthorized();
          return;
        }
        showToast("送信に失敗しました。", "error");
        return;
      }
      const postData = await res.json() as {
        inserted: number;
        total: number;
        ready: boolean;
        inserted_rounds?: Round[];
      };

      setText("");

      showToast(`${postData.inserted}件を送信しました。`, "success");
      broadcastRef.current?.postMessage("update");
      await Promise.all([fetchStatus(), fetchRounds(), fetchEvalStats()]);
    } catch {
      showToast("送信に失敗しました。", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("全データを削除します。よろしいですか？")) return;

    const token = getValidAccessToken();
    if (!token) { router.replace("/login"); return; }

    setResetting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 401) {
          handleUnauthorized();
          return;
        }
        showToast("リセットに失敗しました。", "error");
        return;
      }
      showToast("全データを削除しました。", "success");
      broadcastRef.current?.postMessage("update");
      setStatus({ total_rounds: 0, ready: false, mlAvailable: false });
      setRounds([]);
      setEvalArchive({});
      setEvalStats({ total: 0, hits: 0, hit_rate: null, by_band: [], recent: [] });
    } catch {
      showToast("リセットに失敗しました。", "error");
    } finally {
      setResetting(false);
    }
  };

  const handleResetPredictionSimulation = async () => {
    if (!confirm("予測収支シミュレーションの履歴（予測評価）を削除します。よろしいですか？")) return;

    const token = getValidAccessToken();
    if (!token) { router.replace("/login"); return; }

    setResettingEvals(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/evals`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 401) {
          handleUnauthorized();
          return;
        }
        showToast("予測シミュレーションのリセットに失敗しました。", "error");
        return;
      }
      showToast("予測シミュレーションをリセットしました。", "success");
      setEvalArchive({});
      setEvalStats({ total: 0, hits: 0, hit_rate: null, by_band: [], recent: [] });
      broadcastRef.current?.postMessage("update");
    } catch {
      showToast("予測シミュレーションのリセットに失敗しました。", "error");
    } finally {
      setResettingEvals(false);
    }
  };

  const handleLogout = async () => {
    const token = getValidAccessToken();
    if (token) {
      try {
        const res = await fetch(`${API_URL}/api/v1/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 401) {
          handleUnauthorized();
          return;
        }
      } catch {
        // best-effort
      }
    }
    clearAccessToken();
    router.replace("/login");
  };

  if (checkingAuth) {
    return (
      <main className="flex items-center justify-center min-h-screen">
        <p className="text-gray-400">読み込み中...</p>
      </main>
    );
  }

  const remaining = status ? Math.max(0, READY_THRESHOLD - status.total_rounds) : null;
  const previewUpdatedAt = preview ? new Date(preview.captured_at) : null;
  const predictionSummary = buildPredictionSummary(evalStats?.by_band ?? []);
  const totalPredictionCount = predictionSummary.reduce((sum, row) => sum + row.predictedCount, 0);
  const totalPredictionHitCount = predictionSummary.reduce((sum, row) => sum + row.hitCount, 0);
  const totalPredictionOverCount = predictionSummary.reduce((sum, row) => sum + (row.overCount ?? 0), 0);
  const totalPredictionHitRate = totalPredictionCount > 0 ? (totalPredictionHitCount / totalPredictionCount) * 100 : null;

  return (
    <main className="min-h-screen p-6 max-w-xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">倍率入力</h1>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-400 hover:text-white transition-colors"
        >
          ログアウト
        </button>
      </div>

      {/* Status */}
      {status !== null && (
        <div className="bg-gray-900 rounded-xl p-4 space-y-1">
          <p className="text-sm text-gray-400">
            蓄積件数: <span className="text-white font-semibold">{status.total_rounds}件</span>
          </p>
          <p className="text-sm text-gray-400">
            {status.ready
              ? <span className="text-green-400 font-semibold">分析中</span>
              : <>分析開始まであと <span className="text-yellow-400 font-semibold">{remaining}件</span></>}
          </p>
        </div>
      )}

      <section className="bg-gray-900 rounded-xl p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">OCR プレビュー</h2>
            <p className="text-xs text-gray-400">
              最新キャプチャのバー画像と OCR マスクを 3 秒ごとに更新します。
            </p>
          </div>
          <button
            type="button"
            onClick={() => { void fetchPreview(); }}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-800 text-gray-200 hover:bg-gray-700 transition-colors"
          >
            更新
          </button>
        </div>

        {preview ? (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <p className="text-xs text-gray-400">キャプチャバー</p>
                <img
                  src={preview.bar_image}
                  alt="最新の OCR キャプチャバー"
                  className="w-full rounded-lg border border-gray-800 bg-black"
                />
              </div>
              <div className="space-y-2">
                <p className="text-xs text-gray-400">OCR マスク</p>
                <img
                  src={preview.mask_image}
                  alt="OCR 用の白文字マスク"
                  className="w-full rounded-lg border border-gray-800 bg-black"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-gray-950 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-gray-500">抽出値</p>
                <p className="mt-1 text-sm font-mono text-green-300">
                  {preview.values.length > 0 ? preview.values.join(", ") : "なし"}
                </p>
              </div>
              <div className="rounded-lg bg-gray-950 px-3 py-2 sm:col-span-2">
                <p className="text-[11px] uppercase tracking-wide text-gray-500">OCR Raw</p>
                <p className="mt-1 text-sm font-mono text-gray-200 break-all">
                  {preview.raw_text || "(empty)"}
                </p>
              </div>
            </div>

            <p className="text-xs text-gray-500">
              更新時刻: {previewUpdatedAt?.toLocaleString("ja-JP") ?? "-"} / scale {preview.scale}x
            </p>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-gray-700 px-4 py-6 text-sm text-gray-400 text-center">
            まだ OCR プレビューはありません。capture が新しいスクリーンショットを送るとここに表示されます。
          </div>
        )}
      </section>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label htmlFor="values" className="block text-sm text-gray-400">
            倍率（1行1値）
          </label>
          <textarea
            id="values"
            value={text}
            onChange={(e) => { setText(e.target.value); setValidationError(""); }}
            rows={10}
            placeholder={"1.01\n1.5\n20\n2.05\n100"}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-600 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
          />
        </div>

        {validationError && (
          <p role="alert" className="text-sm text-red-400 bg-red-900/30 border border-red-700 rounded-lg px-3 py-2">
            {validationError}
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={submitting || resetting || resettingEvals}
            className="flex-1 py-2 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {submitting ? "送信中..." : "送信"}
          </button>

          <button
            type="button"
            onClick={handleReset}
            disabled={submitting || resetting || resettingEvals}
            className="py-2 px-4 bg-red-700 hover:bg-red-600 disabled:bg-red-900 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {resetting ? "削除中..." : "リセット"}
          </button>
        </div>

        <button
          type="button"
          onClick={handleResetPredictionSimulation}
          disabled={submitting || resetting || resettingEvals}
          className="w-full py-2 px-4 bg-amber-700 hover:bg-amber-600 disabled:bg-amber-900 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
        >
          {resettingEvals ? "予測履歴を削除中..." : "予測シミュレーションをリセット"}
        </button>
      </form>

      {/* History */}
      {rounds.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-gray-400">入力履歴（新しい順）</h2>
          <div className="grid grid-cols-6 gap-2">
            {rounds.map((r) => {
              const canShowEval = Boolean(status?.mlAvailable);
              const ev = evalArchive[String(r.id)];
              return (
                <span
                  key={r.id}
                  title={canShowEval && ev
                    ? `${ev.label} / 実績:${r.multiplier.toFixed(2)}`
                    : "予測比較なし"}
                  className={`px-2 py-0.5 rounded text-xs font-mono font-semibold text-center flex items-center justify-center gap-1 ${multiplierBadgeClass(r.multiplier)}`}
                >
                  <span>{r.multiplier % 1 === 0 ? r.multiplier.toFixed(0) : r.multiplier}</span>
                  {canShowEval && ev && (
                    ev.verdict === "hit"
                      ? <span>✅</span>
                      : <span className={`inline-block w-2.5 h-2.5 rounded-full ${predictedBandDotClass(ev.predicted_band)}`} aria-hidden="true" />
                  )}
                </span>
              );
            })}
          </div>
          <div className="flex gap-3 text-xs text-gray-600 mt-1">
            <span><span className="inline-block w-2 h-2 rounded-sm bg-blue-600 mr-1"/>1x台</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-green-600 mr-1"/>2x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-yellow-500 mr-1"/>5x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-red-700 mr-1"/>10x以上</span>
          </div>
          {status?.mlAvailable ? (
            <div className="flex gap-3 text-xs text-gray-500 mt-1">
              <span>✅ 的中（予測帯と実績帯が一致）</span>
              <span>● ハズレ（予測帯の色を表示）</span>
            </div>
          ) : (
            <div className="text-xs text-gray-500 mt-1">予測未提供（ML準備中）のため判定マークは非表示</div>
          )}

          <div className="mt-4 overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/70">
            <div className="border-b border-gray-800 px-3 py-2 text-xs text-gray-500">
              総予測件数: <span className="text-gray-200 font-semibold">{evalStats?.total ?? totalPredictionCount}</span>
            </div>
            <table className="min-w-full text-sm text-gray-200">
              <thead className="bg-gray-800/80 text-gray-300">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">予測色</th>
                  <th className="px-3 py-2 text-right font-medium">予測件数</th>
                  <th className="px-3 py-2 text-right font-medium">的中件数</th>
                  <th className="px-3 py-2 text-right font-medium">オーバー</th>
                  <th className="px-3 py-2 text-right font-medium">的中率</th>
                </tr>
              </thead>
              <tbody>
                {predictionSummary.map((row) => (
                  <tr key={row.band} className="border-t border-gray-800">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className={`inline-block h-2.5 w-2.5 rounded-full ${predictedBandDotClass(row.band)}`} aria-hidden="true" />
                        <span>{bandLabelJa(row.band)}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{row.predictedCount}</td>
                    <td className="px-3 py-2 text-right font-mono">{row.hitCount}</td>
                    <td className="px-3 py-2 text-right font-mono">{row.overCount ?? "-"}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {row.hitRate === null ? "-" : `${row.hitRate.toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-gray-700 bg-gray-950/70">
                <tr>
                  <td className="px-3 py-2 font-semibold text-gray-200">合計</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionHitCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">{totalPredictionOverCount}</td>
                  <td className="px-3 py-2 text-right font-mono text-gray-200">
                    {totalPredictionHitRate === null ? "-" : `${totalPredictionHitRate.toFixed(1)}%`}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      )}

      {/* Toast */}
      {toast && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all ${
            toast.type === "success"
              ? "bg-green-700 text-white"
              : "bg-red-700 text-white"
          }`}
        >
          {toast.message}
        </div>
      )}
    </main>
  );
}
