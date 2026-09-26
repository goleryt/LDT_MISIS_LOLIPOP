import {
    useState,
} from "react";

import {
    getSession,
    jsonRequest,
} from "../api/session";

import {
    getThemePreference,
    setThemePreference,
} from "../theme";

import type {
    ThemePreference,
} from "../theme";

import "../styles/settings.css";


const THEME_OPTIONS: {
    value: ThemePreference;
    label: string;
}[] = [
    { value: "light", label: "Светлая" },
    { value: "dark", label: "Тёмная" },
    { value: "system", label: "Как на устройстве" },
];

function SettingsPage() {
    const [theme, setTheme] =
        useState<ThemePreference>(
            getThemePreference,
        );
    const [logoutError, setLogoutError] =
        useState("");
    const [loggingOut, setLoggingOut] =
        useState(false);

    function changeTheme(value: ThemePreference) {
        setTheme(value);
        setThemePreference(value);
    }

    async function signOut() {
        setLogoutError("");
        setLoggingOut(true);

        try {
            await jsonRequest("/api/v1/auth/logout", {
                method: "POST",
            });

            // SessionGate слушает это событие и показывает вход.
            window.dispatchEvent(
                new Event("session-expired"),
            );
        } catch (caught) {
            setLogoutError(
                caught instanceof Error
                    ? caught.message
                    : "Не удалось выйти",
            );
        } finally {
            setLoggingOut(false);
        }
    }

    return (
        <div className="settings-page">
            <section
                className="settings-card"
                aria-labelledby="settings-title"
            >
                <h1 id="settings-title">
                    Настройки
                </h1>

                {getSession() && (
                    <p className="settings-account">
                        Вы вошли как{" "}
                        <strong>
                            {getSession()?.username}
                        </strong>
                        {" · "}
                        {getSession()?.role}
                    </p>
                )}

                <fieldset className="settings-group">
                    <legend>Тема</legend>

                    {THEME_OPTIONS.map((option) => (
                        <label
                            key={option.value}
                            className="settings-radio"
                        >
                            <input
                                type="radio"
                                name="theme"
                                value={option.value}
                                checked={
                                    theme === option.value
                                }
                                onChange={() =>
                                    changeTheme(
                                        option.value,
                                    )
                                }
                            />
                            <span>{option.label}</span>
                        </label>
                    ))}
                </fieldset>

                <label className="settings-switch-row">
                    <span>Уведомления на почту — не подключены</span>

                    <input
                        type="checkbox"
                        role="switch"
                        className="settings-switch"
                        checked={false}
                        disabled
                        title="Почтовая доставка не подключена. Уведомления доступны внутри приложения."
                    />
                </label>

                {logoutError && (
                    <p
                        className="settings-error"
                        role="alert"
                    >
                        {logoutError}
                    </p>
                )}

                <button
                    type="button"
                    className="settings-logout"
                    disabled={loggingOut}
                    onClick={signOut}
                >
                    Выйти из аккаунта
                </button>
            </section>
        </div>
    );
}


export default SettingsPage;
