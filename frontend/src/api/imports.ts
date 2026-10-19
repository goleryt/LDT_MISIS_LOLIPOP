import { ApiError, apiFetch, responseError } from "./session";
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
        if (response.status === 429) throw new ApiError("Сервис импорта занят. Файл не принят в обработку. Подождите несколько секунд и нажмите «Начать импорт» снова.",429);
        if (response.status === 409) throw new ApiError("Этот файл уже обрабатывается. Дождитесь завершения, обновите историю и повторите загрузку при необходимости.",409);
        if (response.status === 408) throw new ApiError("Превышено время обработки. Данные файла не сохранены. Разделите файл на меньшие части и повторите загрузку.",408);
        throw responseError(response);
    }

    return response.json();
}
