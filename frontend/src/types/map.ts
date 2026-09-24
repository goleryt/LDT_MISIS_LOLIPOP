export type MapObjectStatus =
    | "normal"
    | "alarm"
    | "unknown";


export interface MapObject {
    object_id: number;
    name: string | null;
    object_type: string | null;
    status: MapObjectStatus;

    sensor_count: number;
    sensors_with_data: number;
    alarm_sensor_count: number;

    last_event_time: string | null;

    geometry: {
        type: "Point";
        coordinates: [number, number];
    };

    geometry_is_synthetic: boolean;
    data_is_synthetic?: boolean;
}
