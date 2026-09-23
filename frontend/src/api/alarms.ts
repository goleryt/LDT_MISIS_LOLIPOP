import {
    API_BASE_URL,
} from "./config";

import type {
    ActiveAlarmsResponse,
} from "../types/alarms";


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
