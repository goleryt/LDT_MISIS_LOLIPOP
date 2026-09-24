import { canWrite } from "../api/session";
import {
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    ClipboardPlus,
    ExternalLink,
    RefreshCw,
    Search,
    Wrench,
} from "lucide-react";

import {
    useNavigate,
    useSearchParams,
} from "react-router-dom";

import {
    getMapObjects,
} from "../api/map";

import {
    getObjectSensors,
} from "../api/objects";

import {
    createRequest,
    getRequests,
    updateRequest,
} from "../api/requests";

import type {
    MapObject,
} from "../types/map";

import type {
    ObjectSensor,
} from "../types/objects";

import type {
    PreventiveRequest,
    RequestPriority,
    RequestStatus,
} from "../types/requests";


const PRIORITY_LABELS: Record<
    RequestPriority,
    string
> = {
    low: "Низкий",
    medium: "Средний",
    high: "Высокий",
    critical: "Критический",
};


const STATUS_LABELS: Record<
    RequestStatus,
    string
> = {
    new: "Новая",
    in_progress: "В работе",
    completed: "Выполнена",
    cancelled: "Отменена",
};


function formatDateTime(
    value: string | null,
): string {
    if (!value) {
        return "Нет данных";
    }

    return new Date(value)
        .toLocaleString("ru-RU");
}


function RequestsPage() {
    const navigate = useNavigate();

    const [searchParams] =
        useSearchParams();

    const [requests, setRequests] =
        useState<PreventiveRequest[]>([]);

    const [objects, setObjects] =
        useState<MapObject[]>([]);

    const [sensors, setSensors] =
        useState<ObjectSensor[]>([]);

    const [loading, setLoading] =
        useState(true);

    const [saving, setSaving] =
        useState(false);

    const [refreshing, setRefreshing] =
        useState(false);

    const [error, setError] =
        useState<string | null>(null);

    const [search, setSearch] =
        useState("");

    const [showCreate, setShowCreate] =
        useState(false);

    const [objectId, setObjectId] =
        useState<number | null>(null);

    const [channelId, setChannelId] =
        useState<number | null>(null);

    const [title, setTitle] =
        useState("");

    const [description, setDescription] =
        useState("");

    const [priority, setPriority] =
        useState<RequestPriority>(
            "medium",
        );


    async function loadData(
        background = false,
    ) {
        try {
            if (background) {
                setRefreshing(true);
            } else {
                setLoading(true);
            }

            setError(null);

            const [
                requestData,
                objectData,
            ] = await Promise.all([
                getRequests(),
                getMapObjects(),
            ]);

            setRequests(requestData);
            setObjects(objectData);
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось загрузить заявки",
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }


    useEffect(() => {
        void loadData();
    }, []);


    useEffect(() => {
        const objectIdRaw =
            searchParams.get("objectId");

        const channelIdRaw =
            searchParams.get("channelId");

        const parsedObjectId =
            objectIdRaw
                ? Number(objectIdRaw)
                : null;

        const parsedChannelId =
            channelIdRaw
                ? Number(channelIdRaw)
                : null;

        if (
            parsedObjectId !== null &&
            Number.isInteger(parsedObjectId) &&
            parsedObjectId > 0
        ) {
            setObjectId(parsedObjectId);
            setShowCreate(true);

            if (
                parsedChannelId !== null &&
                Number.isInteger(parsedChannelId) &&
                parsedChannelId > 0
            ) {
                setChannelId(
                    parsedChannelId,
                );
                setTitle(
                    `Профилактическая проверка датчика #${parsedChannelId}`,
                );
            }
        }
    }, [searchParams]);


    useEffect(() => {
        let cancelled = false;
        if (objectId === null) {
            setSensors([]);
            return;
        }

        async function loadSensors() {
            try {
                const data =
                    await getObjectSensors(
                        objectId!,
                    );

                if (cancelled) return;
                setSensors(data.sensors);
                setChannelId(current => current !== null && !data.sensors.some(sensor => sensor.channel_id === current) ? null : current);
            } catch {
                if (!cancelled) setSensors([]);
            }
        }

        void loadSensors();
        return () => { cancelled = true; };
        // channelId is intentionally not a dependency:
        // changing the sensor must not reload the whole object.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [objectId]);


    const filteredRequests =
        useMemo(() => {
            const query =
                search
                    .trim()
                    .toLowerCase();

            if (!query) {
                return requests;
            }

            return requests.filter(
                (request) => {
                    return [
                        request.title,
                        request.description,
                        request.object_name,
                        request.sensor_name,
                        String(request.id),
                        String(request.object_id),
                        request.channel_id !== null
                            ? String(
                                request.channel_id,
                            )
                            : null,
                    ]
                        .filter(Boolean)
                        .some((value) =>
                            String(value)
                                .toLowerCase()
                                .includes(query),
                        );
                },
            );
        }, [requests, search]);


    const statistics = useMemo(() => {
        return {
            total: requests.length,
            new: requests.filter(
                (item) =>
                    item.status === "new",
            ).length,
            inProgress: requests.filter(
                (item) =>
                    item.status ===
                    "in_progress",
            ).length,
            completed: requests.filter(
                (item) =>
                    item.status ===
                    "completed",
            ).length,
        };
    }, [requests]);


    function resetForm() {
        setObjectId(null);
        setChannelId(null);
        setTitle("");
        setDescription("");
        setPriority("medium");
    }


    async function submitRequest() {
        if (
            objectId === null ||
            !title.trim()
        ) {
            return;
        }

        try {
            setSaving(true);
            setError(null);

            const created =
                await createRequest({
                    object_id: objectId,
                    channel_id: channelId,
                    title: title.trim(),
                    description:
                        description.trim() ||
                        null,
                    priority,
                });

            setRequests((current) => [
                created,
                ...current,
            ]);

            setShowCreate(false);
            resetForm();
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось создать заявку",
            );
        } finally {
            setSaving(false);
        }
    }


    async function changeStatus(
        request: PreventiveRequest,
        status: RequestStatus,
    ) {
        try {
            const updated =
                await updateRequest(
                    request.id,
                    { status },
                );

            setRequests((current) =>
                current.map((item) =>
                    item.id === updated.id
                        ? updated
                        : item,
                ),
            );
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось обновить заявку",
            );
        }
    }


    function openRequestOnMap(
        request: PreventiveRequest,
    ) {
        const channelPart =
            request.channel_id !== null
                ? `&channelId=${request.channel_id}`
                : "";

        navigate(
            `/?objectId=${request.object_id}${channelPart}`,
        );
    }


    return (
        <div className="requests-page">
            <header className="requests-header">
                <div>
                    <span className="page-eyebrow">
                        Эксплуатация
                    </span>
                    <h1>
                        Профилактические заявки
                    </h1>
                    <p>
                        Фиксация действий диспетчера по объектам
                        и датчикам, требующим проверки.
                    </p>
                </div>

                <div className="requests-header-actions">
                    <button
                        type="button"
                        className="requests-secondary-button"
                        disabled={loading || refreshing}
                        onClick={() =>
                            void loadData(true)
                        }
                    >
                        <RefreshCw
                            size={16}
                            className={
                                refreshing
                                    ? "spinning"
                                    : undefined
                            }
                        />
                        Обновить
                    </button>

                    <button
                        type="button"
                        className="requests-primary-button"
                        onClick={() =>
                            setShowCreate(true)
                        }
                    >
                        <ClipboardPlus size={16} />
                        Новая заявка
                    </button>
                </div>
            </header>

            <section className="requests-stats">
                <div className="request-stat-card">
                    <span>Всего</span>
                    <strong>
                        {loading
                            ? "…"
                            : statistics.total}
                    </strong>
                </div>
                <div className="request-stat-card new">
                    <span>Новые</span>
                    <strong>
                        {statistics.new}
                    </strong>
                </div>
                <div className="request-stat-card progress">
                    <span>В работе</span>
                    <strong>
                        {statistics.inProgress}
                    </strong>
                </div>
                <div className="request-stat-card completed">
                    <span>Выполнены</span>
                    <strong>
                        {statistics.completed}
                    </strong>
                </div>
            </section>

            {showCreate && (
                <section className="request-create-panel">
                    <div className="request-create-heading">
                        <div>
                            <Wrench size={18} />
                            <div>
                                <h2>
                                    Новая профилактическая заявка
                                </h2>
                                <span>
                                    ML-риск будет подключён позднее;
                                    сейчас заявка создаётся по фактическим данным.
                                </span>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => {
                                setShowCreate(false);
                                resetForm();
                            }}
                        >
                            Закрыть
                        </button>
                    </div>

                    <div className="request-form-grid">
                        <label>
                            <span>Объект</span>
                            <select
                                value={
                                    objectId ?? ""
                                }
                                onChange={(event) => {
                                    const value =
                                        event.target.value;

                                    setObjectId(
                                        value
                                            ? Number(value)
                                            : null,
                                    );
                                    setChannelId(null);
                                }}
                            >
                                <option value="">
                                    Выберите объект
                                </option>
                                {objects.map(
                                    (object) => (
                                        <option
                                            key={object.object_id}
                                            value={object.object_id}
                                        >
                                            {object.name ??
                                                `Объект ${object.object_id}`}
                                        </option>
                                    ),
                                )}
                            </select>
                        </label>

                        <label>
                            <span>Датчик</span>
                            <select
                                value={
                                    channelId ?? ""
                                }
                                disabled={
                                    objectId === null
                                }
                                onChange={(event) => {
                                    const value =
                                        event.target.value;

                                    setChannelId(
                                        value
                                            ? Number(value)
                                            : null,
                                    );
                                }}
                            >
                                <option value="">
                                    Весь объект
                                </option>
                                {sensors.map(
                                    (sensor) => (
                                        <option
                                            key={sensor.channel_id}
                                            value={sensor.channel_id}
                                        >
                                            {sensor.name ??
                                                `Канал ${sensor.channel_id}`}
                                        </option>
                                    ),
                                )}
                            </select>
                        </label>

                        <label>
                            <span>Приоритет</span>
                            <select
                                value={priority}
                                onChange={(event) =>
                                    setPriority(
                                        event.target.value as RequestPriority,
                                    )
                                }
                            >
                                {Object.entries(
                                    PRIORITY_LABELS,
                                ).map(([
                                    value,
                                    label,
                                ]) => (
                                    <option
                                        key={value}
                                        value={value}
                                    >
                                        {label}
                                    </option>
                                ))}
                            </select>
                        </label>

                        <label className="request-title-field">
                            <span>Тема</span>
                            <input
                                value={title}
                                maxLength={200}
                                placeholder="Например: Проверить датчик доступа"
                                onChange={(event) =>
                                    setTitle(
                                        event.target.value,
                                    )
                                }
                            />
                        </label>

                        <label className="request-description-field">
                            <span>Описание</span>
                            <textarea
                                value={description}
                                rows={3}
                                maxLength={4000}
                                placeholder="Что требуется проверить или выполнить"
                                onChange={(event) =>
                                    setDescription(
                                        event.target.value,
                                    )
                                }
                            />
                        </label>
                    </div>

                    <div className="request-form-actions">
                        <button
                            type="button"
                            className="requests-primary-button"
                            disabled={
                                !canWrite("requests") || saving ||
                                objectId === null ||
                                !title.trim()
                            }
                            onClick={() =>
                                void submitRequest()
                            }
                        >
                            {saving
                                ? "Создание..."
                                : "Создать заявку"}
                        </button>
                    </div>
                </section>
            )}

            <section className="requests-panel">
                <div className="requests-toolbar">
                    <div className="requests-search">
                        <Search size={16} />
                        <input
                            value={search}
                            placeholder="Поиск по заявкам..."
                            onChange={(event) =>
                                setSearch(
                                    event.target.value,
                                )
                            }
                        />
                    </div>
                    <span>
                        {filteredRequests.length} заявок
                    </span>
                </div>

                {error && (
                    <div className="requests-error">
                        {error}
                    </div>
                )}

                {loading ? (
                    <div className="requests-message">
                        Загрузка заявок...
                    </div>
                ) : filteredRequests.length === 0 ? (
                    <div className="requests-message">
                        Заявок пока нет
                    </div>
                ) : (
                    <div className="requests-table-wrap">
                        <table className="requests-table">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Заявка</th>
                                    <th>Объект / датчик</th>
                                    <th>Приоритет</th>
                                    <th>Статус</th>
                                    <th>Создана</th>
                                    <th />
                                </tr>
                            </thead>
                            <tbody>
                                {filteredRequests.map(
                                    (request) => (
                                        <tr key={request.id}>
                                            <td>
                                                #{request.id}
                                            </td>
                                            <td>
                                                <div className="request-table-main">
                                                    <strong>
                                                        {request.title}
                                                    </strong>
                                                    {request.description && (
                                                        <span>
                                                            {request.description}
                                                        </span>
                                                    )}
                                                </div>
                                            </td>
                                            <td>
                                                <div className="request-table-main">
                                                    <strong>
                                                        {request.object_name ??
                                                            `Объект ${request.object_id}`}
                                                    </strong>
                                                    <span>
                                                        {request.sensor_name ??
                                                            (request.channel_id !== null
                                                                ? `Канал ${request.channel_id}`
                                                                : "Заявка на объект")}
                                                    </span>
                                                </div>
                                            </td>
                                            <td>
                                                <span
                                                    className={
                                                        `request-priority ${request.priority}`
                                                    }
                                                >
                                                    {
                                                        PRIORITY_LABELS[
                                                            request.priority
                                                        ]
                                                    }
                                                </span>
                                            </td>
                                            <td>
                                                <select
                                                    className={
                                                        `request-status-select ${request.status}`
                                                    }
                                                    value={request.status}
                                                    disabled={!canWrite("requests")}
                                                    onChange={(event) =>
                                                        void changeStatus(
                                                            request,
                                                            event.target.value as RequestStatus,
                                                        )
                                                    }
                                                >
                                                    {Object.entries(
                                                        STATUS_LABELS,
                                                    ).map(([
                                                        value,
                                                        label,
                                                    ]) => (
                                                        <option
                                                            key={value}
                                                            value={value}
                                                        >
                                                            {label}
                                                        </option>
                                                    ))}
                                                </select>
                                            </td>
                                            <td>
                                                {formatDateTime(
                                                    request.created_at,
                                                )}
                                            </td>
                                            <td>
                                                <button
                                                    type="button"
                                                    className="request-map-button"
                                                    title="Открыть на карте"
                                                    onClick={() =>
                                                        openRequestOnMap(
                                                            request,
                                                        )
                                                    }
                                                >
                                                    <ExternalLink size={15} />
                                                </button>
                                            </td>
                                        </tr>
                                    ),
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}


export default RequestsPage;
