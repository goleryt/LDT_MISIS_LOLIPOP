import {
    useEffect,
    useState,
} from "react";

import {
    getImports,
    uploadEventsFile,
} from "../api/imports";

import type {
    DataImport,
} from "../types/imports";


function ImportsPage() {
    const [imports, setImports] =
        useState<DataImport[]>([]);

    const [selectedFile, setSelectedFile] =
        useState<File | null>(null);

    const [loading, setLoading] =
        useState(true);

    const [uploading, setUploading] =
        useState(false);

    const [error, setError] =
        useState<string | null>(null);

    const [message, setMessage] =
        useState<string | null>(null);


    async function loadImports() {
        try {
            setError(null);

            const data = await getImports();

            setImports(data);
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Неизвестная ошибка",
            );
        } finally {
            setLoading(false);
        }
    }


    useEffect(() => {
        void loadImports();
    }, []);


    async function handleUpload() {
        if (!selectedFile) {
            setError("Сначала выберите CSV-файл.");
            return;
        }

        try {
            setUploading(true);
            setError(null);
            setMessage(null);

            const result = await uploadEventsFile(
                selectedFile,
            );

            if (result.already_imported) {
                setMessage(
                    "Этот файл уже был успешно импортирован ранее.",
                );
            } else {
                setMessage(
                    "Файл успешно обработан.",
                );
            }

            setSelectedFile(null);

            await loadImports();
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Ошибка загрузки файла",
            );
        } finally {
            setUploading(false);
        }
    }


    return (
        <>
            <header className="page-header">
                <div>
                    <h1>Импорт данных</h1>

                    <p>
                        Загрузка журналов событий в систему
                    </p>
                </div>
            </header>

            <section className="welcome-card import-form">
                <h2>Загрузить журнал событий</h2>

                <input
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(event) => {
                        const file =
                            event.target.files?.[0] ?? null;

                        setSelectedFile(file);
                    }}
                />

                <button
                    className="primary-button"
                    onClick={() => void handleUpload()}
                    disabled={
                        !selectedFile || uploading
                    }
                >
                    {uploading
                        ? "Загрузка..."
                        : "Загрузить CSV"}
                </button>

                {message && (
                    <div className="success-message">
                        {message}
                    </div>
                )}

                {error && (
                    <div className="error-message">
                        {error}
                    </div>
                )}
            </section>

            <section className="welcome-card imports-history">
                <h2>История импортов</h2>

                {loading ? (
                    <p>Загрузка...</p>
                ) : imports.length === 0 ? (
                    <p>Импортов пока нет.</p>
                ) : (
                    <div className="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Файл</th>
                                    <th>Статус</th>
                                    <th>Обработано</th>
                                    <th>Добавлено</th>
                                    <th>Пропущено</th>
                                    <th>Дата</th>
                                </tr>
                            </thead>

                            <tbody>
                                {imports.map((item) => (
                                    <tr key={item.id}>
                                        <td>{item.id}</td>

                                        <td>
                                            {item.file_name}
                                        </td>

                                        <td>
                                            {item.status}
                                        </td>

                                        <td>
                                            {item.processed_rows}
                                        </td>

                                        <td>
                                            {item.inserted_rows}
                                        </td>

                                        <td>
                                            {item.skipped_rows}
                                        </td>

                                        <td>
                                            {new Date(
                                                item.started_at,
                                            ).toLocaleString("ru-RU")}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </>
    );
}

export default ImportsPage;
