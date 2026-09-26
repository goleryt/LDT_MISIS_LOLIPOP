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

    /**
     * Stored result of the daily ML batch (backend `app/ml_job.py`) for a
     * gas channel: a proxy score of an observed CH4 >= 1 % crossing in the
     * forecast window. Not a fire probability, not a confirmed incident.
     * Null for channels the model does not cover or has not scored yet.
     */
    risk_score: number | null;
    risk_is_alert_candidate: boolean | null;
    risk_window_start: string | null;
    risk_window_end_exclusive: string | null;
    risk_decision_status: string | null;
    risk_model_version: string | null;
    risk_reason_codes: string[];
    risk_maintenance_context: string | null;
    risk_as_of_date: string | null;
}


export interface ObjectSensorsResponse {
    object_id: number;
    name: string | null;
    object_type: string | null;

    sensor_count: number;

    sensors: ObjectSensor[];
}
