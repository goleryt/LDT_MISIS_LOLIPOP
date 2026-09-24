import {
    useState,
} from "react";

import type {
    FormEvent,
} from "react";

import {
    useNavigate,
} from "react-router-dom";

import {
    Eye,
    EyeOff,
} from "lucide-react";

import {
    login,
} from "../api/auth";

import "../styles/moscow-map.css";
import "../styles/auth.css";


const REMEMBERED_LOGIN_KEY = "auth.rememberedLogin";


function readRememberedLogin(): string {
    try {
        return (
            window.localStorage.getItem(
                REMEMBERED_LOGIN_KEY,
            ) ?? ""
        );
    } catch {
        return "";
    }
}


function rememberLogin(value: string | null) {
    try {
        if (value) {
            window.localStorage.setItem(
                REMEMBERED_LOGIN_KEY,
                value,
            );
        } else {
            window.localStorage.removeItem(
                REMEMBERED_LOGIN_KEY,
            );
        }
    } catch {
        // Хранилище может быть недоступно — вход от этого не страдает.
    }
}


function AuthPage() {
    const navigate = useNavigate();

    const [username, setUsername] =
        useState(readRememberedLogin);
    const [password, setPassword] =
        useState("");
    const [visible, setVisible] =
        useState(false);
    const [remember, setRemember] =
        useState(() => readRememberedLogin() !== "");
    const [error, setError] =
        useState("");
    const [busy, setBusy] =
        useState(false);

    async function submit(
        event: FormEvent,
    ) {
        event.preventDefault();
        setError("");

        if (!username.trim() || !password) {
            setError(
                "Введите логин и пароль",
            );
            return;
        }

        setBusy(true);

        try {
            await login(
                username.trim(),
                password,
            );

            // Пароль не сохраняется никогда — только логин, и только
            // если пользователь отметил «Запомнить меня».
            rememberLogin(
                remember
                    ? username.trim()
                    : null,
            );

            navigate("/", { replace: true });
        } catch (caught) {
            setError(
                caught instanceof Error
                    ? caught.message
                    : "Не удалось войти",
            );
        } finally {
            setBusy(false);
        }
    }

    return (
        <main className="auth-screen">
            <form
                className="auth-card"
                onSubmit={submit}
                noValidate
            >
                <h1>Вход</h1>

                <label htmlFor="login-username">
                    Почта или номер телефона
                </label>
                <input
                    id="login-username"
                    className="auth-input"
                    placeholder="Логин"
                    autoComplete="username"
                    value={username}
                    onChange={(event) =>
                        setUsername(event.target.value)
                    }
                />

                <label htmlFor="login-password">
                    Пароль
                </label>
                <div className="auth-input-wrap">
                    <input
                        id="login-password"
                        className="auth-input"
                        type={
                            visible
                                ? "text"
                                : "password"
                        }
                        placeholder="Пароль"
                        autoComplete="current-password"
                        value={password}
                        onChange={(event) =>
                            setPassword(
                                event.target.value,
                            )
                        }
                    />

                    <button
                        type="button"
                        className="auth-icon-button"
                        aria-label={
                            visible
                                ? "Скрыть пароль"
                                : "Показать пароль"
                        }
                        onClick={() =>
                            setVisible(
                                (current) => !current,
                            )
                        }
                    >
                        {visible ? (
                            <Eye size={18} />
                        ) : (
                            <EyeOff size={18} />
                        )}
                    </button>
                </div>

                <label className="auth-check">
                    <input
                        type="checkbox"
                        checked={remember}
                        onChange={(event) =>
                            setRemember(
                                event.target.checked,
                            )
                        }
                    />
                    <span>Запомнить меня</span>
                </label>

                {error && (
                    <p
                        className="auth-error"
                        role="alert"
                    >
                        {error}
                    </p>
                )}

                <button
                    type="submit"
                    className="auth-submit"
                    disabled={busy}
                >
                    {busy ? "Вход…" : "Войти"}
                </button>
            </form>
        </main>
    );
}


export default AuthPage;
