import { apiFetch, responseError } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    DataImport,
    ImportEventsResult,
} from "../types/imports";


export async function getImports(): Promise<DataImport[]> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/imports`,
    );

    if (!response.ok) {
        throw responseError(response);
    }

    return response.json();
}


export async function uploadEventsFile(
    file: File,
    kind = "events_journal",
): Promise<ImportEventsResult> {
    const formData = new FormData();

    formData.append("file", file);

    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/imports/events?kind=${encodeURIComponent(kind)}`,
        {
            method: "POST",
            body: formData,
        },
    );

    if (!response.ok) {
        throw responseError(response);
    }

    return response.json();
}
