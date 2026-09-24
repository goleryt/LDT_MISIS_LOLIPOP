import {
    useState,
} from "react";

import {
    useNavigate,
} from "react-router-dom";

import {
    logout,
} from "../api/auth";

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

const EMAIL_NOTIFICATIONS_KEY =
    "settings.emailNotifications";


function readEmailNotifications(): boolean {
    try {
        return (
            window.localStorage.getItem(
                EMAIL_NOTIFICATIONS_KEY,
            ) === "1"
        );
    } catch {
        return false;
    }
}


function SettingsPage() {
    const navigate = useNavigate();

    const [theme, setTheme] =
        useState<ThemePreference>(
            getThemePreference,
        );
    const [emailNotifications, setEmailNotifications] =
        useState(readEmailNotifications);
    const [logoutError, setLogoutError] =
        useState("");
    const [loggingOut, setLoggingOut] =
        useState(false);

    function changeTheme(value: ThemePreference) {
        setTheme(value);
        setThemePreference(value);
    }

    // Пока на сервере нет профиля пользователя, флажок хранится
    // только в этом браузере.
    function changeEmailNotifications(
        value: boolean,
    ) {
        setEmailNotifications(value);

        try {
            window.localStorage.setItem(
                EMAIL_NOTIFICATIONS_KEY,
                value ? "1" : "0",
            );
        } catch {
            // Без хранилища настройка не переживёт перезагрузку.
        }
    }

    async function signOut() {
        setLogoutError("");
        setLoggingOut(true);

        try {
            await logout();
            navigate("/login", { replace: true });
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
                    <span>Уведомления на почту</span>

                    <input
                        type="checkbox"
                        role="switch"
                        className="settings-switch"
                        checked={emailNotifications}
                        onChange={(event) =>
                            changeEmailNotifications(
                                event.target.checked,
                            )
                        }
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
