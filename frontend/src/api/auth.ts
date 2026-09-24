import { API_BASE_URL } from "./config";


export interface AuthSession {
    username: string;
    role: string;
    csrf_token: string;
}

async function readError(
    response: Response,
    fallback: string,
): Promise<string> {
    const body = await response
        .json()
        .catch(() => ({}));

    const detail = body?.detail;

    if (typeof detail === "string") {
        return detail;
    }

    if (detail?.message) {
        return String(detail.message);
    }

    return `${fallback} (${response.status})`;
}


// Контракт входа совпадает с backend напарника (ветка backend):
// POST /api/v1/auth/login {username, password} -> {username, role, csrf_token}.
export async function login(
    username: string,
    password: string,
): Promise<AuthSession> {
    const response = await fetch(
        `${API_BASE_URL}/api/v1/auth/login`,
        {
            method: "POST",
            credentials: "include",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                username,
                password,
            }),
        },
    );

    if (response.status === 404) {
        throw new Error(
            "Сервис авторизации недоступен на этом сервере",
        );
    }

    if (!response.ok) {
        throw new Error(
            await readError(
                response,
                "Не удалось войти",
            ),
        );
    }

    return response.json();
}


// POST /api/v1/auth/logout завершает серверный сеанс. Если сервер
// авторизации не подключён (404) — сеанса на сервере и нет, так что
// выход считается выполненным.
export async function logout(): Promise<void> {
    const response = await fetch(
        `${API_BASE_URL}/api/v1/auth/logout`,
        {
            method: "POST",
            credentials: "include",
        },
    );

    if (
        !response.ok &&
        response.status !== 404 &&
        response.status !== 401
    ) {
        throw new Error(
            await readError(
                response,
                "Не удалось выйти",
            ),
        );
    }
}
