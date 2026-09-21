export interface SensorHistoryEvent {
    id: number;
    event_id: number;
    event_time: string | null;

    alarm: boolean | null;

    raw_value: string | null;
    numeric_value: number | null;
    state_value: string | null;
}


export interface SensorHistoryResponse {
    channel_id: number;
    name: string | null;
    sensor_type: string | null;
    system_type: string | null;
    object_id: number | null;

    returned_events: number;
    numeric_event_count: number;
    alarm_event_count: number;

    events: SensorHistoryEvent[];
}
