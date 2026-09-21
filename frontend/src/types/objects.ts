export type SensorStatus =
    | "normal"
    | "alarm"
    | "unknown";


export interface ObjectSensor {
    channel_id: number;
    name: string | null;

    sensor_type: string | null;
    system_type: string | null;

    tag: string | null;
    site: string | null;
    picket: number | null;

    status: SensorStatus;
    has_data: boolean;
    alarm: boolean | null;

    last_event_time: string | null;

    latest_value_raw: string | null;
    latest_value_numeric: number | null;
    latest_value_state: string | null;
}


export interface ObjectSensorsResponse {
    object_id: number;
    name: string | null;
    object_type: string | null;

    sensor_count: number;

    sensors: ObjectSensor[];
}
