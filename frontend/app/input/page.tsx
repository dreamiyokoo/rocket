"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clearAccessToken, getValidAccessToken } from "../lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const READY_THRESHOLD = 18;
const EVAL_ARCHIVE_KEY = "round_eval_archive_v3";
const EVAL_ARCHIVE_UPDATED_AT_KEY = "round_eval_archive_updated_at";
const EVAL_ARCHIVE_MAX = 2000;

function multiplierBadgeClass(v: number): string {
  if (v >= 10) return "bg-red-700 text-white";
  if (v >= 5)  return "bg-yellow-500 text-black";
  if (v >= 2)  return "bg-green-600 text-white";
  return "bg-blue-600 text-white";
}

function predictedBandDotClass(band: PredictedBand): string {
  if (band === "blue") return "bg-blue-200";
  if (band === "green") return "bg-green-200";
  if (band === "yellow") return "bg-yellow-200";
  return "bg-red-200";
}

type Round = { id: number; multiplier: number; recorded_at: string };
type AnalysisStatus = { total_rounds: number; ready: boolean; mlAvailable: boolean } | null;
type PredictedBand = "blue" | "green" | "yellow" | "red";
type RoundEval = {
  predicted_band: PredictedBand;
  actual_band: PredictedBand;
  actual: number;
  verdict: "hit" | "miss";
  emoji: string;
  label: string;
  evaluated_at: string;
};
type RoundEvalArchive = Record<string, RoundEval>;

function loadEvalArchive(): RoundEvalArchive {
  try {
    const raw = localStorage.getItem(EVAL_ARCHIVE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as RoundEvalArchive;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveEvalArchive(archive: RoundEvalArchive): void {
  try {
    localStorage.setItem(EVAL_ARCHIVE_KEY, JSON.stringify(archive));
    localStorage.setItem(EVAL_ARCHIVE_UPDATED_AT_KEY, String(Date.now()));
  } catch {
    // best-effort
  }
}

function pruneEvalArchive(archive: RoundEvalArchive): RoundEvalArchive {
  const ids = Object.keys(archive)
    .map((k) => Number(k))
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => b - a);
  const keep = new Set(ids.slice(0, EVAL_ARCHIVE_MAX).map((n) => String(n)));
  const next: RoundEvalArchive = {};
  for (const [k, v] of Object.entries(archive)) {
    if (keep.has(k)) next[k] = v;
  }
  return next;
}

function bandFromMultiplier(v: number): PredictedBand {
  if (v <= 2.0) return "blue";
  if (v <= 5.0) return "green";
  if (v <= 10.0) return "yellow";
  return "red";
}

function bandLabel(band: PredictedBand): string {
  if (band === "blue") return "Blue";
  if (band === "green") return "Green";
  if (band === "yellow") return "Yellow";
  return "Red";
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
  const [backfilling, setBackfilling] = useState(false);
  const [status, setStatus] = useState<AnalysisStatus>(null);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [evalArchive, setEvalArchive] = useState<RoundEvalArchive>({});
  const broadcastRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    broadcastRef.current = new BroadcastChannel("rocket:data-changed");
    return () => { broadcastRef.current?.close(); };
  }, []);

  useEffect(() => {
    setEvalArchive(loadEvalArchive());
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

  const fetchCurrentPredictionBand = useCallback(async (): Promise<PredictedBand | null> => {
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis`);
      if (!res.ok) return null;
      const data = await res.json() as {
        recommendation?: { target_line?: number | null };
        ml_prediction?: {
          available?: boolean;
          prob_blue?: number;
          prob_green?: number;
          prob_yellow?: number;
          prob_red?: number;
        };
      };

      const ml = data.ml_prediction;
      const hasMl = Boolean(
        ml?.available
          && typeof ml.prob_blue === "number"
          && typeof ml.prob_green === "number"
          && typeof ml.prob_yellow === "number"
          && typeof ml.prob_red === "number"
      );

      if (hasMl) {
        const probs: Array<{ band: PredictedBand; p: number }> = [
          { band: "blue", p: ml!.prob_blue! },
          { band: "green", p: ml!.prob_green! },
          { band: "yellow", p: ml!.prob_yellow! },
          { band: "red", p: ml!.prob_red! },
        ];
        probs.sort((a, b) => b.p - a.p);
        return probs[0].band;
      }

      return null;
    } catch {
      return null;
    }
  }, []);

  const backfillVisibleHistory = async () => {
    if (rounds.length === 0) return;
    setBackfilling(true);
    try {
      const predictedBand = await fetchCurrentPredictionBand();
      if (!predictedBand) {
        showToast("予測クラス取得に失敗しました。", "error");
        return;
      }
      setEvalArchive((prev) => {
        const next: RoundEvalArchive = { ...prev };
        let changed = 0;
        for (const row of rounds) {
          const key = String(row.id);
          if (!next[key]) {
            next[key] = judgePrediction(row.multiplier, predictedBand);
            changed += 1;
          }
        }
        const pruned = pruneEvalArchive(next);
        saveEvalArchive(pruned);
        if (changed > 0) {
          showToast(`${changed}件にマークを付与しました。`, "success");
        } else {
          showToast("未マークの履歴はありません。", "success");
        }
        return pruned;
      });
    } catch {
      showToast("履歴再判定に失敗しました。", "error");
    } finally {
      setBackfilling(false);
    }
  };


  useEffect(() => {
    const token = getValidAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setCheckingAuth(false);
    fetchStatus();
    fetchRounds();
  }, [router, fetchStatus, fetchRounds]);

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
      const predictedBand = await fetchCurrentPredictionBand();
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

      const insertedRounds = postData.inserted_rounds ?? [];
      if (predictedBand !== null && insertedRounds.length > 0) {
        setEvalArchive((prev) => {
          const next: RoundEvalArchive = { ...prev };
          for (const row of insertedRounds) {
            next[String(row.id)] = judgePrediction(row.multiplier, predictedBand);
          }
          const pruned = pruneEvalArchive(next);
          saveEvalArchive(pruned);
          return pruned;
        });
      }

      setText("");
      showToast(`${parsed.values.length}件を送信しました。`, "success");
      broadcastRef.current?.postMessage("update");
      await Promise.all([fetchStatus(), fetchRounds()]);
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
      try {
        localStorage.removeItem(EVAL_ARCHIVE_KEY);
        localStorage.setItem(EVAL_ARCHIVE_UPDATED_AT_KEY, String(Date.now()));
      } catch {
        // best-effort
      }
    } catch {
      showToast("リセットに失敗しました。", "error");
    } finally {
      setResetting(false);
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
            disabled={submitting || resetting || backfilling}
            className="flex-1 py-2 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {submitting ? "送信中..." : "送信"}
          </button>

          <button
            type="button"
            onClick={handleReset}
            disabled={submitting || resetting || backfilling}
            className="py-2 px-4 bg-red-700 hover:bg-red-600 disabled:bg-red-900 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {resetting ? "削除中..." : "リセット"}
          </button>
        </div>
        <button
          type="button"
          onClick={backfillVisibleHistory}
          disabled={submitting || resetting || backfilling || rounds.length === 0}
          className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors"
        >
          {backfilling ? "再判定中..." : "履歴にマークを付与（表示中72件）"}
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
