import { API_BASE_URL } from "./config";

export type Session = { username: string; role: string; csrf_token: string };
let current: Session | null = null;
export function setSession(value: Session | null) { current = value; }
export function canWrite(domain: "imports" | "requests" | "predictions") {
  const roles = domain === "imports" ? ["admin", "dispatcher"] :
    domain === "requests" ? ["admin", "dispatcher", "technician"] : ["admin", "dispatcher", "analyst"];
  return !!current && roles.includes(current.role);
}
export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (current && !["GET", "HEAD"].includes((init.method ?? "GET").toUpperCase())) {
    headers.set("X-CSRF-Token", current.csrf_token);
  }
  const response = await fetch(input, { ...init, headers, credentials: "include" });
  if (response.status === 401 && !String(input).endsWith("/auth/login")) {
    setSession(null);
    window.dispatchEvent(new Event("session-expired"));
  }
  return response;
}
export async function jsonRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await apiFetch(API_BASE_URL + path, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.message;
    throw new Error(detail ?? `Ошибка запроса (${response.status})`);
  }
  return response.json() as Promise<T>;
}
