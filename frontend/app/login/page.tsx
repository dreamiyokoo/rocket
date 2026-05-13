"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

function hasValidExpiration(token: string): boolean {
  try {
    const [, payload] = token.split(".");
    if (!payload) {
      return false;
    }
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const parsed = JSON.parse(json) as { exp?: number };
    return typeof parsed.exp === "number" && parsed.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token && hasValidExpiration(token)) {
      router.replace("/input");
      return;
    }
    if (token) {
      localStorage.removeItem("access_token");
    }
    setCheckingAuth(false);
  }, [router]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (!API_URL) {
        setError("API接続先が設定されていません。");
        return;
      }

      const response = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        setError("ユーザー名またはパスワードが正しくありません。");
        return;
      }

      const data: { access_token: string } = await response.json();
      localStorage.setItem("access_token", data.access_token);
      router.push("/input");
    } catch {
      setError("ログインに失敗しました。時間をおいて再度お試しください。");
    } finally {
      setLoading(false);
    }
  };

  if (checkingAuth) {
    return <main>読み込み中...</main>;
  }

  return (
    <main>
      <h1>ログイン</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">ユーザー名</label>
          <input
            id="username"
            name="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </div>

        <div>
          <label htmlFor="password">パスワード</label>
          <input
            id="password"
            name="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        {error && <p role="alert">{error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "ログイン中..." : "ログイン"}
        </button>
      </form>
    </main>
  );
}
