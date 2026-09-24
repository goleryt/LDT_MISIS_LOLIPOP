import { canWrite } from "../api/session";
import {
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import {
    CheckCircle2,
    CloudUpload,
    FileText,
    RefreshCw,
    TriangleAlert,
    Upload,
    XCircle,
} from "lucide-react";

import {
    getImports,
    uploadEventsFile,
} from "../api/imports";

import type {
    DataImport,
} from "../types/imports";


function formatBytes(
    bytes: number | null,
): string {
    if (bytes === null) {
        return "—";
    }

    if (bytes < 1024) {
        return `${bytes} Б`;
    }

    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} КБ`;
    }

    return `${(
        bytes /
        (1024 * 1024)
    ).toFixed(1)} МБ`;
}


function formatNumber(
    value: number,
): string {
    return new Intl.NumberFormat(
        "ru-RU",
    ).format(value);
}


function getStatusLabel(
    status: string,
): string {
    switch (status) {
        case "completed":
            return "Завершён";

        case "processing":
            return "Выполняется";

        case "failed":
            return "Ошибка";

        default:
            return status;
    }
}


function ImportsPage() {
    const [kind, setKind] = useState("events_journal");
    const fileInputRef =
        useRef<HTMLInputElement>(null);

    const [imports, setImports] =
        useState<DataImport[]>([]);

    const [selectedFile, setSelectedFile] =
        useState<File | null>(null);

    const [loading, setLoading] =
        useState(true);

    const [uploading, setUploading] =
        useState(false);

    const [dragActive, setDragActive] =
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
                    : "Не удалось получить историю импортов",
            );
        } finally {
            setLoading(false);
        }
    }


    useEffect(() => {
        void loadImports();
    }, []);


    const statistics = useMemo(() => {
        return {
            total: imports.length,

            completed: imports.filter(
                (item) =>
                    item.status === "completed",
            ).length,

            failed: imports.filter(
                (item) =>
                    item.status === "failed",
            ).length,

            processedRows: imports.reduce(
                (sum, item) =>
                    sum + item.processed_rows,
                0,
            ),
        };
    }, [imports]);


    function selectFile(
        file: File | null,
    ) {
        setError(null);
        setMessage(null);

        if (!file) {
            setSelectedFile(null);
            return;
        }

        if (
            !/\.(csv|xlsx|json|xml)$/i.test(file.name)
        ) {
            setSelectedFile(null);

            setError(
                "Поддерживаются CSV, XLSX, JSON, XML.",
            );

            return;
        }

        setSelectedFile(file);
    }


    async function handleUpload() {
        if (!canWrite("imports")) { setError("Недостаточно прав для импорта"); return; }
        if (!selectedFile) {
            setError(
                "Сначала выберите файл CSV/XLSX/JSON/XML.",
            );

            return;
        }

        try {
            setUploading(true);
            setError(null);
            setMessage(null);

            const result =
                await uploadEventsFile(
                    selectedFile, kind,
                );

            if (result.already_imported) {
                setMessage(
                    "Этот файл уже был успешно импортирован ранее.",
                );
            } else {
                setMessage(
                    "Файл успешно обработан и зарегистрирован.",
                );
            }

            setSelectedFile(null);

            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }

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
        <div className="imports-page">
            <header className="imports-header">
                <div>
                    <span className="page-eyebrow">
                        Управление данными
                    </span>

                    <h1>Импорт данных</h1>

                    <p>
                        Загрузка журналов событий в
                        диспетчерскую систему
                    </p>
                </div>

                <button
                    type="button"
                    className="secondary-button"
                    onClick={() =>
                        void loadImports()
                    }
                >
                    <RefreshCw size={17} />
                    Обновить
                </button>
            </header>

            <section className="imports-stats">
                <div className="stat-card">
                    <div className="stat-icon">
                        <FileText size={20} />
                    </div>

                    <div>
                        <span>Всего импортов</span>

                        <strong>
                            {statistics.total}
                        </strong>
                    </div>
                </div>

                <div className="stat-card success">
                    <div className="stat-icon">
                        <CheckCircle2 size={20} />
                    </div>

                    <div>
                        <span>Успешно</span>

                        <strong>
                            {statistics.completed}
                        </strong>
                    </div>
                </div>

                <div className="stat-card danger">
                    <div className="stat-icon">
                        <XCircle size={20} />
                    </div>

                    <div>
                        <span>Ошибки</span>

                        <strong>
                            {statistics.failed}
                        </strong>
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-icon">
                        <Upload size={20} />
                    </div>

                    <div>
                        <span>Обработано строк</span>

                        <strong>
                            {formatNumber(
                                statistics.processedRows,
                            )}
                        </strong>
                    </div>
                </div>
            </section>

            <section className="upload-card">
                <div className="section-heading">
                    <div>
                        <h2>Загрузить журнал событий</h2>

                        <p>
                            Выберите файл CSV/XLSX/JSON/XML или
                            перетащите его в область ниже
                        </p>
                    </div>
                </div>

                <div
                    className={
                        dragActive
                            ? "drop-zone drag-active"
                            : "drop-zone"
                    }
                    onDragEnter={(event) => {
                        event.preventDefault();
                        setDragActive(true);
                    }}
                    onDragOver={(event) => {
                        event.preventDefault();
                        setDragActive(true);
                    }}
                    onDragLeave={(event) => {
                        event.preventDefault();
                        setDragActive(false);
                    }}
                    onDrop={(event) => {
                        event.preventDefault();
                        setDragActive(false);

                        selectFile(
                            event.dataTransfer
                                .files?.[0] ?? null,
                        );
                    }}
                    onClick={() =>
                        fileInputRef.current?.click()
                    }
                >
                    <label>Тип данных <select value={kind} disabled={uploading || !canWrite("imports")} onChange={e => setKind(e.target.value)}>
<option value="events_journal">События датчиков</option><option value="objects">Объекты</option><option value="channels">Каналы датчиков</option>
</select></label>
                        <input
                        ref={fileInputRef}
                        type="file"
                        accept=".csv,text/csv"
                        hidden
                        onChange={(event) => {
                            selectFile(
                                event.target
                                    .files?.[0] ?? null,
                            );
                        }}
                    />

                    <div className="drop-zone-icon">
                        <CloudUpload size={30} />
                    </div>

                    <strong>
                        Перетащите файл CSV/XLSX/JSON/XML сюда
                    </strong>

                    <span>
                        или нажмите, чтобы выбрать
                        файл
                    </span>
                </div>

                {selectedFile && (
                    <div className="selected-file">
                        <div className="selected-file-icon">
                            <FileText size={21} />
                        </div>

                        <div className="selected-file-info">
                            <strong>
                                {selectedFile.name}
                            </strong>

                            <span>
                                {formatBytes(
                                    selectedFile.size,
                                )}
                            </span>
                        </div>

                        <button
                            type="button"
                            className="remove-file-button"
                            onClick={() => {
                                setSelectedFile(null);

                                if (
                                    fileInputRef.current
                                ) {
                                    fileInputRef.current.value =
                                        "";
                                }
                            }}
                        >
                            <XCircle size={19} />
                        </button>
                    </div>
                )}

                <div className="upload-actions">
                    <span className="upload-hint">
                        Поддерживаемый формат: CSV
                    </span>

                    <button
                        type="button"
                        className="primary-button"
                        disabled={
                            !selectedFile ||
                            uploading
                        }
                        onClick={() =>
                            void handleUpload()
                        }
                    >
                        <Upload size={17} />

                        {uploading
                            ? "Обработка..."
                            : "Начать импорт"}
                    </button>
                </div>

                {message && (
                    <div className="notice success">
                        <CheckCircle2 size={18} />
                        {message}
                    </div>
                )}

                {error && (
                    <div className="notice error">
                        <TriangleAlert size={18} />
                        {error}
                    </div>
                )}
            </section>

            <section className="history-card">
                <div className="section-heading">
                    <div>
                        <h2>История импортов</h2>

                        <p>
                            Последние загрузки данных
                            в систему
                        </p>
                    </div>
                </div>

                {loading ? (
                    <div className="history-empty">
                        Загрузка истории...
                    </div>
                ) : imports.length === 0 ? (
                    <div className="history-empty">
                        Импортов пока нет
                    </div>
                ) : (
                    <div className="imports-table-wrapper">
                        <table className="imports-table">
                            <thead>
                                <tr>
                                    <th>Файл</th>
                                    <th>Тип</th>
                                    <th>Статус</th>
                                    <th>Строк</th>
                                    <th>Добавлено</th>
                                    <th>Размер</th>
                                    <th>Дата</th>
                                </tr>
                            </thead>

                            <tbody>
                                {imports.map((item) => (
                                    <tr key={item.id}>
                                        <td>
                                            <div className="file-cell">
                                                <FileText
                                                    size={17}
                                                />

                                                <div>
                                                    <strong>
                                                        {
                                                            item.file_name
                                                        }
                                                    </strong>

                                                    <span>
                                                        ID #{item.id}
                                                    </span>
                                                </div>
                                            </div>
                                        </td>

                                        <td>
                                            Журнал событий
                                        </td>

                                        <td>
                                            <span
                                                className={
                                                    `status-badge ${item.status}`
                                                }
                                            >
                                                <span />

                                                {getStatusLabel(
                                                    item.status,
                                                )}
                                            </span>
                                        </td>

                                        <td>
                                            {formatNumber(
                                                item.processed_rows,
                                            )}
                                        </td>

                                        <td>
                                            {formatNumber(
                                                item.inserted_rows,
                                            )}
                                        </td>

                                        <td>
                                            {formatBytes(
                                                item.file_size_bytes,
                                            )}
                                        </td>

                                        <td>
                                            {new Date(
                                                item.started_at,
                                            ).toLocaleString(
                                                "ru-RU",
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}

export default ImportsPage;
