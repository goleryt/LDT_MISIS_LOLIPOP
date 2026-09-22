export type RequestPriority =
    | "low"
    | "medium"
    | "high"
    | "critical";


export type RequestStatus =
    | "new"
    | "in_progress"
    | "completed"
    | "cancelled";


export interface PreventiveRequest {
    id: number;

    object_id: number;
    object_name: string | null;

    channel_id: number | null;
    sensor_name: string | null;

    title: string;
    description: string | null;

    priority: RequestPriority;
    status: RequestStatus;

    created_at: string | null;
    updated_at: string | null;
    completed_at: string | null;
}


export interface PreventiveRequestCreate {
    object_id: number;
    channel_id: number | null;
    title: string;
    description: string | null;
    priority: RequestPriority;
}


export interface PreventiveRequestUpdate {
    title?: string;
    description?: string | null;
    priority?: RequestPriority;
    status?: RequestStatus;
}
