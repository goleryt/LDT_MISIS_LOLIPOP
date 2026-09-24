import { apiFetch } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    ObjectSensorsResponse,
} from "../types/objects";


export async function getObjectSensors(
    objectId: number,
): Promise<ObjectSensorsResponse> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/objects/${objectId}/sensors`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить датчики объекта: HTTP ${response.status}`,
        );
    }

    return response.json();
}
