import { apiFetch } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type { MapObject } from "../types/map";


export async function getMapObjects(): Promise<MapObject[]> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/map/objects`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить объекты: HTTP ${response.status}`,
        );
    }

    return response.json();
}
