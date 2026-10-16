import { API_BASE_URL } from "./config";

export type Session = { username: string; role: string; csrf_token: string };
let current: Session | null = null;
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
export function responseError(response: Response): ApiError {
  const messages: Record<number, string> = {
    400: "Не удалось обработать данные. Проверьте формат и обязательные поля.",
    401: "Сеанс завершён или данные входа неверны. Войдите снова.",
    403: "Недостаточно прав или сеанс требует обновления. Войдите снова, если действие разрешено вашей роли.",
    404: "Запись не найдена. Обновите список.",
    409: "Запись уже изменилась или переход недоступен. Обновите данные перед повтором.",
    413: "Размер файла превышает разрешённый лимит.",
    422: "Проверьте обязательные поля и допустимые значения.",
    429: "Слишком много попыток. Подождите и повторите действие.",
  };
  return new ApiError(messages[response.status] ?? "Сервис временно недоступен. Повторите действие позже.", response.status);
}
export function setSession(value: Session | null) { current = value; }
export function getSession(): Session | null { return current; }
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
  let response: Response;
  try {
    response = await fetch(input, { ...init, headers, credentials: "include", signal: init.signal ?? AbortSignal.timeout(String(input).includes("/imports/events") ? 300000 : 30000) });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError" && init.signal?.aborted) throw error;
    throw new Error("Нет ответа от сервиса. Проверьте соединение и повторите действие.");
  }
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
    throw responseError(response);
  }
  return response.json() as Promise<T>;
}
