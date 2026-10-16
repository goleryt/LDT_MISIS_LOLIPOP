import { apiFetch, responseError } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    ActiveAlarmsResponse,
} from "../types/alarms";


export async function getActiveAlarms(
    limit = 100,
): Promise<ActiveAlarmsResponse> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/alarms?limit=${limit}`,
    );

    if (!response.ok) {
        throw responseError(response);
    }

    return response.json();
}
