export interface DataImport {
    id: number;
    file_name: string;
    file_sha256: string;
    import_type: string;
    status: string;
    processed_rows: number;
    inserted_rows: number;
    skipped_rows: number;
    file_size_bytes: number | null;
    error_message: string | null;
    started_at: string;
    completed_at: string | null;
}

export interface ImportEventsResult {
    import_id: number;
    file_sha256: string;
    status: string;
    already_imported: boolean;
    processed_rows?: number;
    inserted_rows?: number;
    repeated_headers?: number;
    skipped_duplicates?: number;
}
