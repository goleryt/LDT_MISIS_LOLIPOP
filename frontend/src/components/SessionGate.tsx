import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import AuthPage from "../pages/AuthPage";
import { jsonRequest, setSession } from "../api/session";
import type { Session } from "../api/session";

export default function SessionGate({ children }: { children: ReactNode }) {
  const [session, updateSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const expired = () => { setSession(null); updateSession(null); };
    window.addEventListener("session-expired", expired);
    jsonRequest<Session>("/api/v1/auth/me").then(value => {
      if (active) { setSession(value); updateSession(value); }
    }).catch(() => {}).finally(() => { if (active) setLoading(false); });
    return () => { active = false; window.removeEventListener("session-expired", expired); };
  }, []);
  async function login(username: string, password: string) {
    const value = await jsonRequest<Session>("/api/v1/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }),
    });
    setSession(value); updateSession(value);
  }
  async function logout() {
    setError("");
    try {
      await jsonRequest("/api/v1/auth/logout", { method: "POST" });
      setSession(null); updateSession(null);
    } catch { setError("Не удалось завершить сеанс. Повторите выход."); }
  }
  if (loading) return <main className="auth-screen"><section className="auth-card"><p>Проверка сеанса…</p></section></main>;
  if (!session) return <AuthPage onLogin={login} />;
  return <><div className="session-bar"><span>{session.username} · {session.role}</span>
    {error && <span role="alert">{error}</span>}<button onClick={logout}>Выйти</button></div>{children}</>;
}
