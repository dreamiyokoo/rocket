"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const READY_THRESHOLD = 18;

function hasValidExpiration(token: string): boolean {
  try {
    const [, payload] = token.split(".");
    if (!payload) return false;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const parsed = JSON.parse(atob(padded)) as { exp?: number };
    return typeof parsed.exp === "number" && parsed.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

function getToken(): string | null {
  const token = localStorage.getItem("access_token");
  if (token && hasValidExpiration(token)) return token;
  if (token) localStorage.removeItem("access_token");
  return null;
}

function multiplierBadgeClass(v: number): string {
  if (v >= 10) return "bg-red-700 text-white";
  if (v >= 5)  return "bg-yellow-500 text-black";
  if (v >= 2)  return "bg-green-600 text-white";
  return "bg-blue-600 text-white";
}

type Round = { id: number; multiplier: number; recorded_at: string };
type AnalysisStatus = { total_rounds: number; ready: boolean } | null;

export default function InputPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [text, setText] = useState("");
  const [validationError, setValidationError] = useState("");
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [status, setStatus] = useState<AnalysisStatus>(null);
  const [rounds, setRounds] = useState<Round[]>([]);

  const showToast = (message: string, type: "success" | "error") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis`);
      if (!res.ok) return;
      const data = await res.json() as { total_rounds: number; ready: boolean };
      setStatus({ total_rounds: data.total_rounds, ready: data.ready });
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

  useEffect(() => {
    const token = getToken();
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
      if (isNaN(n) || line === "") return { error: `「${line}」は数値ではありません。` };
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

    const token = getToken();
    if (!token) { router.replace("/login"); return; }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ values: parsed.values }),
      });
      if (!res.ok) {
        showToast("送信に失敗しました。", "error");
        return;
      }
      setText("");
      showToast(`${parsed.values.length}件を送信しました。`, "success");
      await Promise.all([fetchStatus(), fetchRounds()]);
    } catch {
      showToast("送信に失敗しました。", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("全データを削除します。よろしいですか？")) return;

    const token = getToken();
    if (!token) { router.replace("/login"); return; }

    setResetting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/rounds`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        showToast("リセットに失敗しました。", "error");
        return;
      }
      showToast("全データを削除しました。", "success");
      setStatus({ total_rounds: 0, ready: false });
      setRounds([]);
    } catch {
      showToast("リセットに失敗しました。", "error");
    } finally {
      setResetting(false);
    }
  };

  const handleLogout = async () => {
    const token = getToken();
    if (token) {
      try {
        await fetch(`${API_URL}/api/v1/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        // best-effort
      }
    }
    localStorage.removeItem("access_token");
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
            disabled={submitting || resetting}
            className="flex-1 py-2 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {submitting ? "送信中..." : "送信"}
          </button>

          <button
            type="button"
            onClick={handleReset}
            disabled={submitting || resetting}
            className="py-2 px-4 bg-red-700 hover:bg-red-600 disabled:bg-red-900 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
          >
            {resetting ? "削除中..." : "リセット"}
          </button>
        </div>
      </form>

      {/* History */}
      {rounds.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-gray-400">入力履歴（新しい順）</h2>
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
          <div className="flex gap-3 text-xs text-gray-600 mt-1">
            <span><span className="inline-block w-2 h-2 rounded-sm bg-blue-600 mr-1"/>1x台</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-green-600 mr-1"/>2x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-yellow-500 mr-1"/>5x以上</span>
            <span><span className="inline-block w-2 h-2 rounded-sm bg-red-700 mr-1"/>10x以上</span>
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
