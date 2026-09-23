export interface JournalEvent {
    row_id: number;
    event_id: number;
    channel_id: number;

    object_id: number | null;
    object_name: string | null;

    sensor_name: string | null;
    sensor_type: string | null;
    system_type: string | null;

    event_time: string | null;
    alarm: boolean | null;

    raw_value: string | null;
    numeric_value: number | null;
    state_value: string | null;
}


export interface EventsResponse {
    limit: number;
    offset: number;
    returned: number;
    has_more: boolean;
    events: JournalEvent[];
}


export interface EventsQuery {
    limit?: number;
    offset?: number;
    alarm?: boolean | null;
    objectId?: number | null;
    channelId?: number | null;
}
