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

    if (query.timeFrom) params.set("time_from", query.timeFrom);
    if (query.timeTo) params.set("time_to", query.timeTo);
    if (query.alarmState) params.set("alarm_state", query.alarmState);
    if (query.objectQuery) params.set("object_query", query.objectQuery);
    if (query.sensorQuery) params.set("sensor_query", query.sensorQuery);
    if (query.eventQuery) params.set("event_query", query.eventQuery);
    if (query.sortBy) params.set("sort_by", query.sortBy);
    if (query.sortDesc !== undefined) params.set("sort_desc", String(query.sortDesc));

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
