import { apiFetch } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    SensorHistoryResponse,
} from "../types/sensors";


export async function getSensorHistory(
    channelId: number,
    limit = 200,
): Promise<SensorHistoryResponse> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/sensors/${channelId}/history?limit=${limit}`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить историю датчика: HTTP ${response.status}`,
        );
    }

    return response.json();
}
