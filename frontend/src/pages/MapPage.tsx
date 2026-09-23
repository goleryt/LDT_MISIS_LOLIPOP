import {
    useEffect,
    useMemo,
    useState,
    useRef,
} from "react";

import {
    useNavigate,
    useSearchParams,
} from "react-router-dom";


import {
    AlertTriangle,
    MapPin,
    ShieldCheck,
    X,
    Activity,
    Search,
} from "lucide-react";

import { getMapObjects } from "../api/map";

import type {
    MapObject,
    MapObjectStatus,
} from "../types/map";

import SchematicMap from "../components/SchematicMap";
import "../styles/moscow-map.css";

import {
    getObjectSensors,
} from "../api/objects";

import type {
    ObjectSensor,
    SensorStatus,
} from "../types/objects";

import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip as ChartTooltip,
    XAxis,
    YAxis,
} from "recharts";

import {
    getSensorHistory,
} from "../api/sensors";

import type {
    SensorHistoryResponse,
} from "../types/sensors";



const STATUS_LABELS: Record<
    MapObjectStatus,
    string
> = {
    normal: "Нет тревог",
    alarm: "Тревога",
    unknown: "Нет данных",
};


type SummaryFilter =
    | "all"
    | "normal"
    | "alarm"
    | "unknown";

const SENSOR_PAGE_SIZE = 100;

function channelCountLabel(count: number): string {
    const form = new Intl.PluralRules("ru-RU").select(count);
    const noun = form === "one"
        ? "канал"
        : form === "few"
            ? "канала"
            : "каналов";
    return `${count} ${noun}`;
}


function sensorEventTime(
    sensor: ObjectSensor,
): number {
    if (!sensor.last_event_time) {
        return 0;
    }

    const time = Date.parse(
        sensor.last_event_time,
    );

    return Number.isNaN(time)
        ? 0
        : time;
}


function sortSensorsForDisplay(
    sensors: ObjectSensor[],
): ObjectSensor[] {
    return [...sensors].sort(
        (left, right) => {
            const leftAlarm =
                left.status === "alarm"
                    ? 1
                    : 0;

            const rightAlarm =
                right.status === "alarm"
                    ? 1
                    : 0;

            if (leftAlarm !== rightAlarm) {
                return rightAlarm - leftAlarm;
            }

            /*
             * Когда появится ML-контракт:
             * здесь между alarm и временем
             * добавим сортировку risk_score DESC.
             */

            const timeDifference =
                sensorEventTime(right) -
                sensorEventTime(left);

            if (timeDifference !== 0) {
                return timeDifference;
            }

            return (
                left.channel_id -
                right.channel_id
            );
        },
    );
}



function MapPage() {
    const navigate = useNavigate();
    const [searchParams] =
        useSearchParams();

    const [objects, setObjects] =
        useState<MapObject[]>([]);

    const [selectedObject, setSelectedObject] =
        useState<MapObject | null>(null);

    const [loading, setLoading] =
        useState(true);

    const [error, setError] =
        useState<string | null>(null);

    const [sensors, setSensors] =
        useState<ObjectSensor[]>([]);

    const [sensorsLoading, setSensorsLoading] =
        useState(false);

    const [sensorsError, setSensorsError] =
        useState<string | null>(null);

    const [sensorSearch, setSensorSearch] =
        useState("");

    const [visibleSensorCount, setVisibleSensorCount] =
        useState(SENSOR_PAGE_SIZE);

    const [selectedSensor, setSelectedSensor] =
        useState<ObjectSensor | null>(null);

    const [activeSummaryFilter, setActiveSummaryFilter] =
        useState<SummaryFilter | null>(
            null,
        );

    const preferredSensorStatusRef =
        useRef<SensorStatus | null>(
            null,
        );

    const preferredSensorChannelIdRef =
        useRef<number | null>(
            null,
        );

    const handledMapNavigationRef =
        useRef<string | null>(
            null,
        );

    const [sensorHistory, setSensorHistory] =
        useState<SensorHistoryResponse | null>(
            null,
        );

    const [historyLoading, setHistoryLoading] =
        useState(false);

    const [historyError, setHistoryError] =
        useState<string | null>(null);


    function selectMapObject(
        object: MapObject,
        preferredSensorStatus:
            SensorStatus | null = null,
        preferredSensorChannelId:
            number | null = null,
    ) {
        preferredSensorStatusRef.current =
            preferredSensorStatus;

        preferredSensorChannelIdRef.current =
            preferredSensorChannelId;

        setSelectedSensor(null);
        setSensorSearch("");
        setVisibleSensorCount(SENSOR_PAGE_SIZE);
        setSelectedObject(object);
    }

    async function loadObjects() {
        try {
            setError(null);

            const data = await getMapObjects();

            setObjects(data);

            setSelectedObject((current) => {
                if (!current) {
                    return null;
                }

                return (
                    data.find(
                        (item) =>
                            item.object_id === current.object_id,
                    ) ?? null
                );
            });
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
        void loadObjects();

        const intervalId = window.setInterval(
            () => {
                void loadObjects();
            },
            60_000,
        );
        
        return () => {
            window.clearInterval(intervalId);
        };
    }, []);

    useEffect(() => {
        if (!selectedObject) {
            setSensors([]);
            setSelectedSensor(null);
            setSensorSearch("");
            setVisibleSensorCount(SENSOR_PAGE_SIZE);
            return;
        }

        const objectId =
            selectedObject.object_id;

        async function loadSensors() {
            try {
                setSensorsLoading(true);
                setSensorsError(null);
                setSelectedSensor(null);

                const data =
                    await getObjectSensors(
                        objectId,
                    );

                const sortedSensors =
                    sortSensorsForDisplay(
                        data.sensors,
                    );

                setSensors(sortedSensors);
                setVisibleSensorCount(SENSOR_PAGE_SIZE);

                const preferredChannelId =
                    preferredSensorChannelIdRef.current;

                const preferredStatus =
                    preferredSensorStatusRef.current;


                if (
                    preferredChannelId !== null
                ) {
                    const preferredSensor =
                        sortedSensors.find(
                            (sensor) =>
                                sensor.channel_id ===
                                preferredChannelId,
                        ) ?? null;

                    setSelectedSensor(
                        preferredSensor,
                    );
                    if (preferredSensor) {
                        setVisibleSensorCount(Math.max(
                            SENSOR_PAGE_SIZE,
                            sortedSensors.indexOf(preferredSensor) + 1,
                        ));
                    }
                } else if (preferredStatus) {
                    const preferredSensor =
                        sortedSensors.find(
                            (sensor) =>
                                sensor.status ===
                                preferredStatus,
                        ) ?? null;

                    setSelectedSensor(
                        preferredSensor,
                    );
                }


                preferredSensorChannelIdRef.current =
                    null;

                preferredSensorStatusRef.current =
                    null;
            } catch (error) {
                setSensorsError(
                    error instanceof Error
                        ? error.message
                        : "Не удалось получить датчики",
                );
            } finally {
                setSensorsLoading(false);
            }
        }

        void loadSensors();
    }, [selectedObject?.object_id]);


    useEffect(() => {
        if (!selectedSensor) {
            setSensorHistory(null);
            setHistoryError(null);
            return;
        }

        const channelId =
            selectedSensor.channel_id;

        async function loadHistory() {
            try {
                setHistoryLoading(true);
                setHistoryError(null);

                const data =
                    await getSensorHistory(
                        channelId,
                        200,
                    );

                setSensorHistory(data);
            } catch (error) {
                setHistoryError(
                    error instanceof Error
                        ? error.message
                        : "Не удалось получить историю",
                );

                setSensorHistory(null);
            } finally {
                setHistoryLoading(false);
            }
        }

        void loadHistory();
    }, [selectedSensor?.channel_id]);

    useEffect(() => {
        const objectIdRaw =
            searchParams.get(
                "objectId",
            );

        const channelIdRaw =
            searchParams.get(
                "channelId",
            );

        if (
            !objectIdRaw ||
            objects.length === 0
        ) {
            return;
        }

        const objectId =
            Number(objectIdRaw);

        const channelId =
            channelIdRaw
                ? Number(channelIdRaw)
                : null;

        if (
            !Number.isInteger(objectId) ||
            objectId <= 0
        ) {
            return;
        }

        if (
            channelId !== null &&
            (
                !Number.isInteger(channelId) ||
                channelId <= 0
            )
        ) {
            return;
        }

        const navigationKey =
            `${objectId}:${channelId ?? "-"}`;

        if (
            handledMapNavigationRef.current ===
            navigationKey
        ) {
            return;
        }

        const object =
            objects.find(
                (item) =>
                    item.object_id ===
                    objectId,
            );

        if (!object) {
            return;
        }

        handledMapNavigationRef.current =
            navigationKey;

        selectMapObject(
            object,
            null,
            channelId,
        );
    }, [
        objects,
        searchParams,
    ]);

    const statistics = useMemo(() => {
        return {
            total: objects.length,

            normal: objects.filter(
                (item) => item.status === "normal",
            ).length,

            alarm: objects.filter(
                (item) => item.status === "alarm",
            ).length,

            unknown: objects.filter(
                (item) => item.status === "unknown",
            ).length,
        };
    }, [objects]);

    const hasSyntheticGeometry = objects.some(
        (item) => item.geometry_is_synthetic,
    );
    const hasSyntheticRecords = objects.some(
        (item) => item.data_is_synthetic,
    );

    const summaryObjects = useMemo(() => {
        if (!activeSummaryFilter) {
            return [];
        }

        const filtered =
            activeSummaryFilter === "all"
                ? objects
                : objects.filter(
                    (item) =>
                        item.status ===
                        activeSummaryFilter,
                );

        const statusPriority = {
            alarm: 0,
            unknown: 1,
            normal: 2,
        };

        return [...filtered].sort(
            (left, right) => {
                const statusDifference =
                    statusPriority[left.status] -
                    statusPriority[right.status];

                if (statusDifference !== 0) {
                    return statusDifference;
                }

                return (
                    left.name ?? ""
                ).localeCompare(
                    right.name ?? "",
                    "ru",
                );
            },
        );
    }, [
        objects,
        activeSummaryFilter,
    ]);

    const filteredSensors = useMemo(() => {
        const query = sensorSearch
            .trim()
            .toLowerCase();

        if (!query) {
            return sensors;
        }
       
        return sensors.filter((sensor) => {
            return [
                sensor.name,
                sensor.sensor_type,
                sensor.system_type,
                sensor.tag,
                String(sensor.channel_id),
                sensor.picket !== null
                    ? String(sensor.picket)
                    : null,
            ]
                .filter(Boolean)
                .some((value) =>
                    String(value)
                        .toLowerCase()
                        .includes(query),
                );
        });
    }, [sensors, sensorSearch]);

    const visibleSensors = filteredSensors.slice(0, visibleSensorCount);

    const sensorStatistics = useMemo(() => {
        return {
            normal: sensors.filter(
                (sensor) =>
                    sensor.status === "normal",
            ).length,

            alarm: sensors.filter(
                (sensor) =>
                    sensor.status === "alarm",
            ).length,

            unknown: sensors.filter(
                (sensor) =>
                    sensor.status === "unknown",
            ).length,
        };
    }, [sensors]);

    const numericHistory = useMemo(() => {
        if (!sensorHistory) {
            return [];
        }

        return sensorHistory.events
            .filter(
                (event) =>
                    event.numeric_value !== null &&
                    event.event_time !== null,
            )
            .map((event) => ({
                time: event.event_time!,
                value: event.numeric_value!,
                alarm: event.alarm === true,
            }));
    }, [sensorHistory]);

    return (
        <div className={selectedObject ? "map-page has-object-drawer" : "map-page"}>
            <SchematicMap
                objects={objects}
                selectedObject={selectedObject}
                onSelectObject={selectMapObject}
            />

            <div className="map-place-card" aria-label="Схема Москвы">
                <span className="map-place-eyebrow">Обзор инфраструктуры</span>
                <strong>Москва</strong>
                <span>Авторская интерактивная схема города</span>
            </div>

            <div className="map-summary">
                <button
                    type="button"
                    className={
                        activeSummaryFilter === "all"
                            ? "summary-card active"
                            : "summary-card"
                    }
                    onClick={() =>
                        setActiveSummaryFilter(
                            (current) =>
                                current === "all"
                                    ? null
                                    : "all",
                        )
                    }
                >
                    <MapPin size={18} />

                    <div>
                        <span>Объекты</span>

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
                        activeSummaryFilter === "normal"
                            ? "summary-card normal active"
                            : "summary-card normal"
                    }
                    onClick={() =>
                        setActiveSummaryFilter(
                            (current) =>
                                current === "normal"
                                    ? null
                                    : "normal",
                        )
                    }
                >
                    <ShieldCheck size={18} />

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
                        activeSummaryFilter === "alarm"
                            ? "summary-card alarm active"
                            : "summary-card alarm"
                    }
                    onClick={() =>
                        setActiveSummaryFilter(
                            (current) =>
                                current === "alarm"
                                    ? null
                                    : "alarm",
                        )
                    }
                >
                    <AlertTriangle size={18} />

                    <div>
                        <span>Тревога</span>

                        <strong>
                            {statistics.alarm}
                        </strong>
                    </div>
                </button>

                <button
                    type="button"
                    className={
                        activeSummaryFilter === "unknown"
                            ? "summary-card unknown active"
                            : "summary-card unknown"
                    }
                    onClick={() =>
                        setActiveSummaryFilter(
                            (current) =>
                                current === "unknown"
                                    ? null
                                    : "unknown",
                        )
                    }
                >
                    <div className="summary-dot" />

                    <div>
                        <span>Нет данных</span>

                        <strong>
                            {statistics.unknown}
                        </strong>
                    </div>
                </button>
            </div>

            {hasSyntheticGeometry && (
                <div className="map-data-badge" title={hasSyntheticRecords
                    ? "Демонстрационные объекты, каналы и события вымышлены; точки не являются адресами"
                    : "Точки устойчиво вычислены из ID объектов; их положение не соответствует реальному адресу"}>
                    <MapPin size={13} />
                    {hasSyntheticRecords
                        ? "Демо-данные · условные точки и события"
                        : "Условное размещение · не адреса объектов"}
                </div>
            )}
            {activeSummaryFilter && (
                <div className="summary-list-panel">
                    <div className="summary-list-header">
                        <div>
                            <strong>
                                {activeSummaryFilter ===
                                    "all" &&
                                    "Все объекты"}

                                {activeSummaryFilter ===
                                    "normal" &&
                                    "Объекты без тревог"}

                                {activeSummaryFilter ===
                                    "alarm" &&
                                    "Объекты с тревогами"}

                                {activeSummaryFilter ===
                                    "unknown" &&
                                    "Объекты без данных"}
                            </strong>

                            <span>
                                {summaryObjects.length} объектов
                            </span>
                        </div>

                        <button
                            type="button"
                            onClick={() =>
                                setActiveSummaryFilter(null)
                            }
                        >
                            <X size={17} />
                        </button>
                    </div>

                    <div className="summary-object-list">
                        {summaryObjects.map(
                            (item) => (
                                <button
                                    type="button"
                                    key={item.object_id}
                                    className="summary-object-row"
                                    onClick={() => {
                                        let preferredStatus:
                                            SensorStatus | null =
                                            null;

                                        if (
                                            item.status ===
                                            "alarm"
                                        ) {
                                            preferredStatus =
                                                "alarm";
                                        }

                                        if (
                                            item.status ===
                                            "unknown"
                                        ) {
                                            preferredStatus =
                                                "unknown";
                                        }

                                        selectMapObject(
                                            item,
                                            preferredStatus,
                                        );

                                        setActiveSummaryFilter(
                                            null,
                                        );
                                    }}
                                >
                                    <span
                                        className={
                                            `summary-object-status ${item.status}`
                                        }
                                    />

                                    <div>
                                        <strong>
                                            {item.name ??
                                                `Объект ${item.object_id}`}
                                        </strong>

                                        <span>
                                            {
                                                item.sensors_with_data
                                            }{" "}
                                            из{" "}
                                            {channelCountLabel(item.sensor_count)}
                                        </span>
                                    </div>

                                    {item.status ===
                                        "alarm" && (
                                            <b>
                                                {
                                                    item.alarm_sensor_count
                                                } трев.
                                            </b>
                                        )}
                                </button>
                            ),
                        )}
                    </div>
                </div>
            )}
             
            <div className="map-legend">
                <div className="legend-title">
                    Состояние объектов
                </div>

                <div className="legend-item">
                    <span className="legend-dot normal" />
                    Нет тревог по доступным данным
                </div>

                <div className="legend-item">
                    <span className="legend-dot alarm" />
                    Есть активная тревога
                </div>

                <div className="legend-item">
                    <span className="legend-dot unknown" />
                    Нет событий
                </div>

                {hasSyntheticGeometry && (
                    <div className="legend-note">
                        Точки вычислены из ID объектов. Их положение не показывает реальные адреса или зоны риска.
                    </div>
                )}
            </div>

            {error && (
                <div className="map-error">
                    {error}
                </div>
            )}

            {selectedObject && (
                <aside className="object-drawer">
                    <div className="drawer-header">
                        <div>
                            <span className="drawer-eyebrow">
                                Объект #{selectedObject.object_id}
                            </span>

                            <h2>
                                {selectedObject.name ??
                                    `Объект ${selectedObject.object_id}`}
                            </h2>
                        </div>

                        <button
                            type="button"
                            className="drawer-close"
                            onClick={() =>
                                setSelectedObject(null)
                            }
                            aria-label="Закрыть"
                        >
                            <X size={20} />
                        </button>
                    </div>

                    {selectedObject.geometry_is_synthetic && (
                        <p className="drawer-location-note">
                            {selectedObject.data_is_synthetic
                                ? "Демо-данные: объект, каналы и события вымышлены. Точка на карте условная и не показывает реальное местоположение."
                                : "Точка на карте условная: она вычислена из ID объекта и не показывает его реальное местоположение."}
                        </p>
                    )}

                    <div
                        className={
                            `object-status object-status-${selectedObject.status}`
                        }
                    >
                        <span className="object-status-dot" />

                        {
                            STATUS_LABELS[
                            selectedObject.status
                            ]
                        }
                    </div>

                    <div className="object-info-grid">
                        <div>
                            <span>Тип объекта</span>

                            <strong>
                                {selectedObject.object_type ??
                                    "Не указан"}
                            </strong>
                        </div>

                        <div>
                            <span>Каналов датчиков</span>

                            <strong>
                                {selectedObject.sensor_count}
                            </strong>
                        </div>

                        <div>
                            <span>Есть данные</span>

                            <strong>
                                {
                                    selectedObject
                                        .sensors_with_data
                                }{" "}
                                из{" "}
                                {
                                    selectedObject
                                        .sensor_count
                                }
                            </strong>
                        </div>

                        <div>
                            <span>Тревожных</span>

                            <strong>
                                {
                                    selectedObject
                                        .alarm_sensor_count
                                }
                            </strong>
                        </div>
                    </div>

                    <div className="drawer-section">
                        <h3>Последнее событие</h3>

                        <p>
                            {selectedObject.last_event_time
                                ? new Date(
                                    selectedObject.last_event_time,
                                ).toLocaleString("ru-RU")
                                : "Нет данных"}
                        </p>
                    </div>

                    <div className="drawer-section sensors-section">
                        <div className="sensors-heading">
                            <div>
                                <h3>Каналы объекта</h3>

                                <span>
                                    {channelCountLabel(sensors.length)} · связь по ID объекта
                                </span>
                            </div>

                            <div className="sensor-counts">
                                <span className="sensor-count normal">
                                    {sensorStatistics.normal}
                                </span>

                                <span className="sensor-count alarm">
                                    {sensorStatistics.alarm}
                                </span>

                                <span className="sensor-count unknown">
                                    {sensorStatistics.unknown}
                                </span>
                            </div>
                        </div>

                        <div className="sensor-search">
                            <Search size={16} />

                            <input
                                type="text"
                                value={sensorSearch}
                                placeholder="Поиск датчика, типа, ПК..."
                                onChange={(event) => {
                                    setSensorSearch(event.target.value);
                                    setVisibleSensorCount(SENSOR_PAGE_SIZE);
                                }}
                            />
                        </div>

                        {sensorsLoading ? (
                            <div className="sensors-empty">
                                Загрузка датчиков...
                            </div>
                        ) : sensorsError ? (
                            <div className="sensors-error">
                                {sensorsError}
                            </div>
                        ) : filteredSensors.length === 0 ? (
                            <div className="sensors-empty">
                                Датчики не найдены
                            </div>
                        ) : (
                            <div className="sensor-list">
                                {visibleSensors.map((sensor) => (
                                    <button
                                        type="button"
                                        key={sensor.channel_id}
                                        className={
                                            selectedSensor?.channel_id ===
                                                sensor.channel_id
                                                ? "sensor-row selected"
                                                : "sensor-row"
                                        }
                                        onClick={() =>
                                            setSelectedSensor(sensor)
                                        }
                                    >
                                        <span
                                            className={
                                                `sensor-status-dot ${sensor.status}`
                                            }
                                        />

                                        <div className="sensor-row-main">
                                            <strong>
                                                {sensor.name ??
                                                    `Канал ${sensor.channel_id}`}
                                            </strong>

                                            <span>
                                                {sensor.sensor_type ??
                                                    "Тип не указан"}
                                            </span>
                                        </div>

                                        <div className="sensor-row-meta">
                                            {sensor.picket !== null && (
                                                <span>
                                                    ПК {sensor.picket}
                                                </span>
                                            )}

                                            <small>
                                                #{sensor.channel_id}
                                            </small>
                                        </div>
                                    </button>
                                ))}
                                {visibleSensors.length < filteredSensors.length && (
                                    <button
                                        type="button"
                                        className="sensor-list-more"
                                        onClick={() => setVisibleSensorCount((current) => current + SENSOR_PAGE_SIZE)}
                                    >
                                        Показать ещё · {visibleSensors.length} из {filteredSensors.length}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                </aside>
            )}
            {selectedSensor && (
                <aside className="sensor-detail-panel">
                    <div className="sensor-detail-header">
                        <div>
                            <span className="drawer-eyebrow">
                                Датчик #{selectedSensor.channel_id}
                            </span>

                            <h3>
                                {selectedSensor.name ??
                                    `Канал ${selectedSensor.channel_id}`}
                            </h3>
                        </div>

                        <button
                            type="button"
                            className="sensor-detail-close"
                            onClick={() =>
                                setSelectedSensor(null)
                            }
                        >
                            <X size={17} />
                        </button>
                    </div>

                    <div
                        className={
                            `sensor-detail-status ${selectedSensor.status}`
                        }
                    >
                        <span />

                        {selectedSensor.status === "normal" &&
                            "Нет тревоги"}

                        {selectedSensor.status === "alarm" &&
                            "Тревога"}

                        {selectedSensor.status === "unknown" &&
                            "Нет данных"}
                    </div>

                    <div className="sensor-detail-grid">
                        <div>
                            <span>Тип датчика</span>

                            <strong>
                                {selectedSensor.sensor_type ??
                                    "Не указан"}
                            </strong>
                        </div>

                        <div>
                            <span>Система</span>

                            <strong>
                                {selectedSensor.system_type ??
                                    "Не указана"}
                            </strong>
                        </div>

                        <div>
                            <span>Пикет</span>

                            <strong>
                                {selectedSensor.picket ??
                                    "—"}
                            </strong>
                        </div>

                        <div>
                            <span>Site</span>

                            <strong>
                                {selectedSensor.site ??
                                    "—"}
                            </strong>
                        </div>
                    </div>

                    <div className="sensor-value-card">
                        <div className="sensor-value-icon">
                            <Activity size={20} />
                        </div>

                        <div>
                            <span>
                                Последнее значение
                            </span>

                            <strong>
                                {selectedSensor.latest_value_raw ??
                                    "Нет данных"}
                            </strong>
                        </div>
                    </div>

                    <div className="sensor-detail-row">
                        <span>Последнее событие</span>

                        <strong>
                            {selectedSensor.last_event_time
                                ? new Date(
                                    selectedSensor.last_event_time,
                                ).toLocaleString("ru-RU")
                                : "Нет данных"}
                        </strong>
                    </div>

                    <div className="sensor-detail-row">
                        <span>Тег</span>

                        <strong>
                            {selectedSensor.tag ?? "—"}
                        </strong>
                    </div>

                    {selectedObject && (
                        <button
                            type="button"
                            className="sensor-request-button"
                            disabled={selectedObject.data_is_synthetic}
                            onClick={() =>
                                navigate(
                                    `/requests?objectId=${selectedObject.object_id}&channelId=${selectedSensor.channel_id}`,
                                )
                            }
                        >
                            {selectedObject.data_is_synthetic
                                ? "Заявки недоступны в демо"
                                : "Создать профилактическую заявку"}
                        </button>
                    )}
                    <div className="sensor-history-section">
                        <div className="sensor-history-heading">
                            <div>
                                <span className="drawer-eyebrow">
                                    История
                                </span>

                                <h3>
                                    Последние события
                                </h3>
                            </div>

                            {sensorHistory && (
                                <span className="history-count">
                                    {sensorHistory.returned_events}
                                </span>
                            )}
                        </div>

                        {historyLoading ? (
                            <div className="history-placeholder">
                                Загрузка истории...
                            </div>
                        ) : historyError ? (
                            <div className="history-placeholder error">
                                {historyError}
                            </div>
                        ) : !sensorHistory ||
                            sensorHistory.events.length === 0 ? (
                            <div className="history-placeholder">
                                История отсутствует
                            </div>
                        ) : numericHistory.length >= 2 ? (
                            <div className="sensor-chart">
                                <ResponsiveContainer
                                    width="100%"
                                    height={190}
                                >
                                    <LineChart
                                        data={numericHistory}
                                    >
                                        <CartesianGrid
                                            strokeDasharray="3 3"
                                            vertical={false}
                                        />

                                        <XAxis
                                            dataKey="time"
                                            tickFormatter={(value) =>
                                                String(value)
                                                    .slice(11, 16)
                                            }
                                            tick={{
                                                fontSize: 9,
                                            }}
                                        />

                                        <YAxis
                                            width={38}
                                            tick={{
                                                fontSize: 9,
                                            }}
                                        />

                                        <ChartTooltip
                                            labelFormatter={(value) =>
                                                String(value)
                                                    .replace("T", " ")
                                            }
                                        />

                                        <Line
                                            type="monotone"
                                            dataKey="value"
                                            stroke="#2563eb"
                                            strokeWidth={2}
                                            dot={false}
                                            isAnimationActive={false}
                                        />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        ) : (
                            <div className="sensor-timeline">
                                {[...sensorHistory.events]
                                    .reverse()
                                    .slice(0, 20)
                                    .map((event) => (
                                        <div
                                            className="timeline-event"
                                            key={event.id}
                                        >
                                            <span
                                                className={
                                                    event.alarm
                                                        ? "timeline-dot alarm"
                                                        : "timeline-dot normal"
                                                }
                                            />

                                            <div className="timeline-event-content">
                                                <strong>
                                                    {event.raw_value ??
                                                        event.state_value ??
                                                        "Нет значения"}
                                                </strong>

                                                <span>
                                                    {event.event_time
                                                        ? event.event_time
                                                            .replace("T", " ")
                                                        : "Время неизвестно"}
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                            </div>
                        )}
                    </div>
                </aside>
            )}
        </div>
    );
}

export default MapPage;
