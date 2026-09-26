import SensorIcon from "../components/SensorIcon";
import {
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    AlertTriangle,
    Building2,
    Clock3,
    RefreshCw,
    RadioTower,
} from "lucide-react";

import {
    getActiveAlarms,
} from "../api/alarms";

import type {
    ActiveAlarm,
} from "../types/alarms";

import {
    useNavigate,
} from "react-router-dom";


function formatDateTime(
    value: string | null,
): string {
    if (!value) {
        return "Нет данных";
    }

    return new Date(
        value,
    ).toLocaleString("ru-RU");
}


function getAlarmValue(
    alarm: ActiveAlarm,
): string {
    if (alarm.raw_value) {
        return alarm.raw_value;
    }

    if (alarm.state_value) {
        return alarm.state_value;
    }

    if (alarm.numeric_value !== null) {
        return String(alarm.numeric_value);
    }

    return "Нет значения";
}


function AlarmsPage() {
    const navigate = useNavigate();

    const [alarms, setAlarms] =
        useState<ActiveAlarm[]>([]);

    const [loading, setLoading] =
        useState(true);

    const [refreshing, setRefreshing] =
        useState(false);

    const [error, setError] =
        useState<string | null>(null);

    function openAlarmOnMap(
        alarm: ActiveAlarm,
    ) {
        if (alarm.object_id === null) {
            return;
        }

        navigate(
            `/?objectId=${alarm.object_id}&channelId=${alarm.channel_id}`,
        );
    }

    async function loadAlarms(
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
                await getActiveAlarms();

            setAlarms(data.alarms);
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось получить тревоги",
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }


    useEffect(() => {
        void loadAlarms();

        const intervalId =
            window.setInterval(
                () => {
                    void loadAlarms(true);
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
        const objectIds =
            new Set(
                alarms
                    .map(
                        (alarm) =>
                            alarm.object_id,
                    )
                    .filter(
                        (
                            objectId,
                        ): objectId is number =>
                            objectId !== null,
                    ),
            );

        const latestAlarm =
            alarms.length > 0
                ? alarms[0]
                : null;

        return {
            alarmCount:
                alarms.length,

            objectCount:
                objectIds.size,

            latestTime:
                latestAlarm?.event_time ??
                null,
        };
    }, [alarms]);


    return (
        <div className="alarms-page">
            <header className="alarms-header">
                <div>
                    <span className="page-eyebrow">
                        Мониторинг
                    </span>

                    <h1>
                        Активные тревоги
                    </h1>

                    <p>
                        Датчики, у которых последнее
                        зарегистрированное событие
                        имеет тревожный статус.
                    </p>
                </div>

                <button
                    type="button"
                    className="alarms-refresh-button"
                    disabled={
                        loading ||
                        refreshing
                    }
                    onClick={() =>
                        void loadAlarms(true)
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


            <section className="alarms-stats">
                <div className="alarm-stat-card danger">
                    <div className="alarm-stat-icon">
                        <AlertTriangle
                            size={19}
                        />
                    </div>

                    <div>
                        <span>
                            Активных тревог
                        </span>

                        <strong>
                            {loading
                                ? "…"
                                : statistics.alarmCount}
                        </strong>
                    </div>
                </div>


                <div className="alarm-stat-card">
                    <div className="alarm-stat-icon">
                        <Building2
                            size={19}
                        />
                    </div>

                    <div>
                        <span>
                            Объектов с тревогой
                        </span>

                        <strong>
                            {loading
                                ? "…"
                                : statistics.objectCount}
                        </strong>
                    </div>
                </div>


                <div className="alarm-stat-card">
                    <div className="alarm-stat-icon">
                        <Clock3
                            size={19}
                        />
                    </div>

                    <div>
                        <span>
                            Последняя тревога
                        </span>

                        <strong className="alarm-stat-time">
                            {loading
                                ? "…"
                                : formatDateTime(
                                    statistics.latestTime,
                                )}
                        </strong>
                    </div>
                </div>
            </section>


            <section className="alarms-panel">
                <div className="alarms-panel-header">
                    <div>
                        <h2>
                            Тревожные датчики
                        </h2>

                        <span>
                            Автообновление раз в
                            60 секунд
                        </span>
                    </div>

                    {!loading && (
                        <div className="alarms-live">
                            <span />

                            Данные актуальны
                        </div>
                    )}
                </div>


                {error ? (
                    <div className="alarms-error">
                        <AlertTriangle
                            size={18}
                        />

                        <div>
                            <strong>
                                Не удалось загрузить
                                тревоги
                            </strong>

                            <span>
                                {error}
                            </span>
                        </div>
                    </div>
                ) : loading ? (
                    <div className="alarms-empty">
                        Загрузка тревог...
                    </div>
                ) : alarms.length === 0 ? (
                    <div className="alarms-empty">
                        <div className="alarms-empty-icon">
                            <RadioTower
                                size={24}
                            />
                        </div>

                        <strong>
                            Активных тревог нет
                        </strong>

                        <span>
                            Последние события всех
                            доступных датчиков сейчас
                            не имеют тревожного статуса.
                        </span>
                    </div>
                ) : (
                    <div className="alarms-table-wrap">
                        <table className="alarms-table">
                            <thead>
                                <tr>
                                    <th>Статус</th>
                                    <th>Объект</th>
                                    <th>Датчик</th>
                                    <th>Тип</th>
                                    <th>Значение</th>
                                    <th>Время</th>
                                </tr>
                            </thead>

                            <tbody>
                                {alarms.map(
                                    (alarm) => (
                                        <tr
                                            key={alarm.channel_id}
                                            className={
                                                alarm.object_id !== null
                                                    ? "alarm-row-clickable"
                                                    : undefined
                                            }
                                            role={
                                                alarm.object_id !== null
                                                    ? "button"
                                                    : undefined
                                            }
                                            tabIndex={
                                                alarm.object_id !== null
                                                    ? 0
                                                    : undefined
                                            }
                                            onClick={() =>
                                                openAlarmOnMap(alarm)
                                            }
                                            onKeyDown={(event) => {
                                                if (
                                                    alarm.object_id === null
                                                ) {
                                                    return;
                                                }

                                                if (
                                                    event.key === "Enter" ||
                                                    event.key === " "
                                                ) {
                                                    event.preventDefault();

                                                    openAlarmOnMap(alarm);
                                                }
                                            }}
                                        >
                                            <td>
                                                <span className="alarm-status-badge">
                                                    <span />

                                                    Тревога
                                                </span>
                                            </td>

                                            <td>
                                                <div className="alarm-table-main">
                                                    <strong>
                                                        {alarm.object_name ??
                                                            (
                                                                alarm.object_id !==
                                                                    null
                                                                    ? `Объект ${alarm.object_id}`
                                                                    : "Не указан"
                                                            )}
                                                    </strong>

                                                    {alarm.object_id !==
                                                        null && (
                                                            <span>
                                                                ID{" "}
                                                                {
                                                                    alarm.object_id
                                                                }
                                                            </span>
                                                        )}
                                                </div>
                                            </td>

                                            <td>
                                                <div className="alarm-table-main">
                                                    <strong>
                                                        {alarm.sensor_name ??
                                                            `Канал ${alarm.channel_id}`}
                                                    </strong>

                                                    <span>
                                                        Канал{" "}
                                                        {
                                                            alarm.channel_id
                                                        }
                                                    </span>
                                                </div>
                                            </td>

                                            <td>
                                                <div className="alarm-sensor-cell">
                                                    <SensorIcon
                                                        sensorType={alarm.sensor_type}
                                                        systemType={alarm.system_type}
                                                        size={22}
                                                    />

                                                    <div className="alarm-table-main">
                                                        <strong>
                                                            {alarm.sensor_type ??
                                                                "Не указан"}
                                                        </strong>

                                                        <span>
                                                            {alarm.system_type ??
                                                                "Система не указана"}
                                                        </span>
                                                    </div>
                                                </div>
                                            </td>

                                            <td>
                                                <span className="alarm-value">
                                                    {getAlarmValue(
                                                        alarm,
                                                    )}
                                                </span>
                                            </td>

                                            <td>
                                                <span className="alarm-time">
                                                    {formatDateTime(
                                                        alarm.event_time,
                                                    )}
                                                </span>
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


export default AlarmsPage;
