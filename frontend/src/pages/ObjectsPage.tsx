import {
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    AlertTriangle,
    Building2,
    CircleHelp,
    MapPin,
    RefreshCw,
    Search,
    ShieldCheck,
} from "lucide-react";

import {
    useNavigate,
} from "react-router-dom";

import {
    getMapObjects,
} from "../api/map";

import type {
    MapObject,
    MapObjectStatus,
} from "../types/map";


type ObjectFilter =
    | "all"
    | MapObjectStatus;


const STATUS_LABELS: Record<
    MapObjectStatus,
    string
> = {
    normal: "Без тревог",
    alarm: "Тревога",
    unknown: "Нет данных",
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


function ObjectsPage() {
    const navigate = useNavigate();

    const [objects, setObjects] =
        useState<MapObject[]>([]);

    const [loading, setLoading] =
        useState(true);

    const [refreshing, setRefreshing] =
        useState(false);

    const [error, setError] =
        useState<string | null>(null);

    const [search, setSearch] =
        useState("");

    const [filter, setFilter] =
        useState<ObjectFilter>("all");


    async function loadObjects(
        background = false,
    ) {
        try {
            if (background) {
                setRefreshing(true);
            } else {
                setLoading(true);
            }

            setError(null);

            const data =
                await getMapObjects();

            setObjects(data);
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось получить объекты",
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }


    useEffect(() => {
        void loadObjects();

        const intervalId =
            window.setInterval(
                () => {
                    void loadObjects(true);
                },
                60_000,
            );

        return () => {
            window.clearInterval(
                intervalId,
            );
        };
    }, []);


    const statistics = useMemo(() => {
        return {
            total: objects.length,
            normal: objects.filter(
                (item) =>
                    item.status === "normal",
            ).length,
            alarm: objects.filter(
                (item) =>
                    item.status === "alarm",
            ).length,
            unknown: objects.filter(
                (item) =>
                    item.status === "unknown",
            ).length,
        };
    }, [objects]);


    const filteredObjects =
        useMemo(() => {
            const query =
                search
                    .trim()
                    .toLowerCase();

            const statusPriority: Record<
                MapObjectStatus,
                number
            > = {
                alarm: 0,
                unknown: 1,
                normal: 2,
            };

            return objects
                .filter((item) => {
                    if (
                        filter !== "all" &&
                        item.status !== filter
                    ) {
                        return false;
                    }

                    if (!query) {
                        return true;
                    }

                    return [
                        item.name,
                        item.object_type,
                        String(item.object_id),
                    ]
                        .filter(Boolean)
                        .some((value) =>
                            String(value)
                                .toLowerCase()
                                .includes(query),
                        );
                })
                .sort((left, right) => {
                    const statusDifference =
                        statusPriority[
                            left.status
                        ] -
                        statusPriority[
                            right.status
                        ];

                    if (
                        statusDifference !== 0
                    ) {
                        return statusDifference;
                    }

                    return (
                        left.name ?? ""
                    ).localeCompare(
                        right.name ?? "",
                        "ru",
                    );
                });
        }, [objects, search, filter]);


    function openObject(
        object: MapObject,
    ) {
        navigate(
            `/?objectId=${object.object_id}`,
        );
    }


    return (
        <div className="objects-page">
            <header className="objects-header">
                <div>
                    <span className="page-eyebrow">
                        Инфраструктура
                    </span>

                    <h1>Объекты</h1>

                    <p>
                        Объекты инженерной инфраструктуры
                        и состояние связанных датчиков.
                    </p>
                </div>

                <button
                    type="button"
                    className="objects-refresh-button"
                    disabled={
                        loading || refreshing
                    }
                    onClick={() =>
                        void loadObjects(true)
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
            </header>

            <section className="objects-stats">
                <button
                    type="button"
                    className={
                        filter === "all"
                            ? "object-stat-card active"
                            : "object-stat-card"
                    }
                    onClick={() =>
                        setFilter("all")
                    }
                >
                    <Building2 size={19} />
                    <div>
                        <span>Всего объектов</span>
                        <strong>
                            {loading
                                ? "…"
                                : statistics.total}
                        </strong>
                    </div>
                </button>

                <button
                    type="button"
                    className={
                        filter === "normal"
                            ? "object-stat-card normal active"
                            : "object-stat-card normal"
                    }
                    onClick={() =>
                        setFilter("normal")
                    }
                >
                    <ShieldCheck size={19} />
                    <div>
                        <span>Без тревог</span>
                        <strong>
                            {statistics.normal}
                        </strong>
                    </div>
                </button>

                <button
                    type="button"
                    className={
                        filter === "alarm"
                            ? "object-stat-card alarm active"
                            : "object-stat-card alarm"
                    }
                    onClick={() =>
                        setFilter("alarm")
                    }
                >
                    <AlertTriangle size={19} />
                    <div>
                        <span>С тревогой</span>
                        <strong>
                            {statistics.alarm}
                        </strong>
                    </div>
                </button>

                <button
                    type="button"
                    className={
                        filter === "unknown"
                            ? "object-stat-card unknown active"
                            : "object-stat-card unknown"
                    }
                    onClick={() =>
                        setFilter("unknown")
                    }
                >
                    <CircleHelp size={19} />
                    <div>
                        <span>Нет данных</span>
                        <strong>
                            {statistics.unknown}
                        </strong>
                    </div>
                </button>
            </section>

            <section className="objects-panel">
                <div className="objects-toolbar">
                    <div className="objects-search">
                        <Search size={16} />
                        <input
                            type="text"
                            value={search}
                            placeholder="Поиск по названию, типу или ID..."
                            onChange={(event) =>
                                setSearch(
                                    event.target.value,
                                )
                            }
                        />
                    </div>

                    <span className="objects-result-count">
                        {filteredObjects.length} объектов
                    </span>
                </div>

                {error ? (
                    <div className="objects-message error">
                        {error}
                    </div>
                ) : loading ? (
                    <div className="objects-message">
                        Загрузка объектов...
                    </div>
                ) : filteredObjects.length === 0 ? (
                    <div className="objects-message">
                        Объекты не найдены
                    </div>
                ) : (
                    <div className="objects-table-wrap">
                        <table className="objects-table">
                            <thead>
                                <tr>
                                    <th>Статус</th>
                                    <th>Объект</th>
                                    <th>Тип</th>
                                    <th>Датчики</th>
                                    <th>С данными</th>
                                    <th>Тревожных</th>
                                    <th>Последнее событие</th>
                                    <th />
                                </tr>
                            </thead>

                            <tbody>
                                {filteredObjects.map(
                                    (object) => (
                                        <tr
                                            key={object.object_id}
                                            className="object-table-row"
                                            tabIndex={0}
                                            onClick={() =>
                                                openObject(object)
                                            }
                                            onKeyDown={(event) => {
                                                if (
                                                    event.key === "Enter" ||
                                                    event.key === " "
                                                ) {
                                                    event.preventDefault();
                                                    openObject(object);
                                                }
                                            }}
                                        >
                                            <td>
                                                <span
                                                    className={
                                                        `object-list-status ${object.status}`
                                                    }
                                                >
                                                    <span />
                                                    {
                                                        STATUS_LABELS[
                                                            object.status
                                                        ]
                                                    }
                                                </span>
                                            </td>

                                            <td>
                                                <div className="object-table-main">
                                                    <strong>
                                                        {object.name ??
                                                            `Объект ${object.object_id}`}
                                                    </strong>
                                                    <span>
                                                        ID {object.object_id}
                                                    </span>
                                                </div>
                                            </td>

                                            <td>
                                                {object.object_type ??
                                                    "Не указан"}
                                            </td>

                                            <td>
                                                {object.sensor_count}
                                            </td>

                                            <td>
                                                <strong>
                                                    {
                                                        object.sensors_with_data
                                                    }
                                                </strong>
                                                <span className="object-coverage">
                                                    {" "}
                                                    из {object.sensor_count}
                                                </span>
                                            </td>

                                            <td>
                                                <span
                                                    className={
                                                        object.alarm_sensor_count > 0
                                                            ? "object-alarm-count active"
                                                            : "object-alarm-count"
                                                    }
                                                >
                                                    {
                                                        object.alarm_sensor_count
                                                    }
                                                </span>
                                            </td>

                                            <td>
                                                {formatDateTime(
                                                    object.last_event_time,
                                                )}
                                            </td>

                                            <td>
                                                <button
                                                    type="button"
                                                    className="object-map-button"
                                                    title="Показать на карте"
                                                    onClick={(event) => {
                                                        event.stopPropagation();
                                                        openObject(object);
                                                    }}
                                                >
                                                    <MapPin size={15} />
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


export default ObjectsPage;
