import type {
    DataImport,
    ImportEventsResult,
} from "../types/imports";


const API_BASE_URL =
    import.meta.env.VITE_API_BASE_URL ??
    "http://127.0.0.1:8000";


export async function getImports(): Promise<DataImport[]> {
    const response = await fetch(
        `${API_BASE_URL}/api/v1/imports`,
    );

    if (!response.ok) {
        throw new Error(
            `Не удалось получить историю импортов: HTTP ${response.status}`,
        );
    }

    return response.json();
}


export async function uploadEventsFile(
    file: File,
): Promise<ImportEventsResult> {
    const formData = new FormData();

    formData.append("file", file);

    const response = await fetch(
        `${API_BASE_URL}/api/v1/imports/events`,
        {
            method: "POST",
            body: formData,
        },
    );

    if (!response.ok) {
        let message =
            `Ошибка загрузки: HTTP ${response.status}`;

        try {
            const body = await response.json();

            if (body.detail) {
                message = body.detail;
            }
        } catch {
            // Оставляем стандартное сообщение.
        }

        throw new Error(message);
    }

    return response.json();
}
