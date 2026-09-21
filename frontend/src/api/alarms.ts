import type {
    ActiveAlarmsResponse,
} from "../types/alarms";


const API_BASE_URL =
    import.meta.env.VITE_API_BASE_URL ??
    "http://127.0.0.1:8000";


export async function getActiveAlarms(
    limit = 100,
): Promise<ActiveAlarmsResponse> {
    const response = await fetch(
        `${API_BASE_URL}/api/v1/alarms?limit=${limit}`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить тревоги: HTTP ${response.status}`,
        );
    }

    return response.json();
}
