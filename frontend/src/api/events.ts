import { apiFetch } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    EventsQuery,
    EventsResponse,
} from "../types/events";


export async function getEvents(
    query: EventsQuery = {},
): Promise<EventsResponse> {
    const params =
        new URLSearchParams();

    params.set(
        "limit",
        String(query.limit ?? 100),
    );

    params.set(
        "offset",
        String(query.offset ?? 0),
    );

    if (query.alarm !== undefined &&
        query.alarm !== null) {
        params.set(
            "alarm",
            String(query.alarm),
        );
    }

    if (query.objectId) {
        params.set(
            "object_id",
            String(query.objectId),
        );
    }

    if (query.channelId) {
        params.set(
            "channel_id",
            String(query.channelId),
        );
    }

    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/events?${params.toString()}`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить журнал событий: HTTP ${response.status}`,
        );
    }

    return response.json();
}
