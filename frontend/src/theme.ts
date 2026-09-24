export type ThemePreference = "light" | "dark" | "system";

const THEME_KEY = "settings.theme";
const DEFAULT_PREFERENCE: ThemePreference = "dark";


function isPreference(
    value: unknown,
): value is ThemePreference {
    return (
        value === "light" ||
        value === "dark" ||
        value === "system"
    );
}


export function getThemePreference(): ThemePreference {
    try {
        const stored =
            window.localStorage.getItem(THEME_KEY);

        return isPreference(stored)
            ? stored
            : DEFAULT_PREFERENCE;
    } catch {
        return DEFAULT_PREFERENCE;
    }
}


function resolveTheme(
    preference: ThemePreference,
): "light" | "dark" {
    if (preference !== "system") {
        return preference;
    }

    return window.matchMedia(
        "(prefers-color-scheme: dark)",
    ).matches
        ? "dark"
        : "light";
}


function apply(preference: ThemePreference) {
    document.documentElement.dataset.theme =
        resolveTheme(preference);
}


export function setThemePreference(
    preference: ThemePreference,
) {
    try {
        window.localStorage.setItem(
            THEME_KEY,
            preference,
        );
    } catch {
        // Без хранилища тема просто не переживёт перезагрузку.
    }

    apply(preference);
}


// Вызывается до первого рендера, чтобы страница не мигала другой темой.
export function initTheme() {
    apply(getThemePreference());

    // «Как на устройстве» должно следовать за системой вживую.
    window
        .matchMedia("(prefers-color-scheme: dark)")
        .addEventListener("change", () => {
            if (getThemePreference() === "system") {
                apply("system");
            }
        });
}
