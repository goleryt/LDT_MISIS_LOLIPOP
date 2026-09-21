export interface ActiveAlarm {
    event_row_id: number;
    event_id: number;

    channel_id: number;

    object_id: number | null;
    object_name: string | null;
    object_type: string | null;

    sensor_name: string | null;
    sensor_type: string | null;
    system_type: string | null;

    tag: string | null;

    event_time: string | null;

    alarm: boolean;

    raw_value: string | null;
    numeric_value: number | null;
    state_value: string | null;
}


export interface ActiveAlarmsResponse {
    count: number;
    alarms: ActiveAlarm[];
}
