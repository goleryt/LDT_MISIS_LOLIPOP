import { apiFetch } from "./session";
import {
    API_BASE_URL,
} from "./config";

import type {
    PreventiveRequest,
    PreventiveRequestCreate,
    PreventiveRequestUpdate,
} from "../types/requests";


export async function getRequests(): Promise<PreventiveRequest[]> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/requests`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить заявки: HTTP ${response.status}`,
        );
    }

    return response.json();
}


export async function createRequest(
    payload: PreventiveRequestCreate,
): Promise<PreventiveRequest> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/requests`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        },
    );

    if (!response.ok) {
        const detail = await response
            .json()
            .catch(() => null);

        throw new Error(
            detail?.detail ??
            `Не удалось создать заявку: HTTP ${response.status}`,
        );
    }

    return response.json();
}


export async function updateRequest(
    requestId: number,
    payload: PreventiveRequestUpdate,
): Promise<PreventiveRequest> {
    const response = await apiFetch(
        `${API_BASE_URL}/api/v1/requests/${requestId}`,
        {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        },
    );

    if (!response.ok) {
        const detail = await response
            .json()
            .catch(() => null);

        throw new Error(
            detail?.detail ??
            `Не удалось обновить заявку: HTTP ${response.status}`,
        );
    }

    return response.json();
}
