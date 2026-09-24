import { useEffect, useState } from "react";
import type { ReactNode, FormEvent } from "react";
import { jsonRequest, setSession } from "../api/session";
import type { Session } from "../api/session";

export default function SessionGate({ children }: { children: ReactNode }) {
  const [session, updateSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const expired = () => { setSession(null); updateSession(null); };
    window.addEventListener("session-expired", expired);
    jsonRequest<Session>("/api/v1/auth/me").then(value => {
      if (active) { setSession(value); updateSession(value); }
    }).catch(() => {}).finally(() => { if (active) setLoading(false); });
    return () => { active = false; window.removeEventListener("session-expired", expired); };
  }, []);
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const value = await jsonRequest<Session>("/api/v1/auth/login", {
        method: "POST", body: JSON.stringify({ username, password }),
      });
      setSession(value); updateSession(value); setPassword("");
    } catch (err) { setError(err instanceof Error ? err.message : "Не удалось войти"); }
    finally { setBusy(false); }
  }
  async function logout() {
    setError("");
    try {
      await jsonRequest("/api/v1/auth/logout", { method: "POST" });
      setSession(null); updateSession(null);
    } catch { setError("Не удалось завершить сеанс. Повторите выход."); }
  }
  if (loading) return <main className="auth-screen">Проверка сеанса…</main>;
  if (!session) return <main className="auth-screen"><form className="auth-card" onSubmit={login}>
    <h1>Москоллектор</h1><p>Вход в систему мониторинга</p>
    <label>Имя пользователя<input required autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label>
    <label>Пароль<input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} type="submit">{busy ? "Вход…" : "Войти"}</button>
  </form></main>;
  return <><div className="session-bar"><span>{session.username} · {session.role}</span>
    {error && <span role="alert">{error}</span>}<button onClick={logout}>Выйти</button></div>{children}</>;
}
