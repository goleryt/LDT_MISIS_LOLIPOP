import {
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    ChevronLeft,
    ChevronRight,
    Filter,
    RefreshCw,
    Search,
} from "lucide-react";

import {
    useNavigate,
} from "react-router-dom";

import {
    getEvents,
} from "../api/events";

import type {
    JournalEvent,
} from "../types/events";


type AlarmFilter =
    | "all"
    | "alarm"
    | "normal";


const PAGE_SIZE = 100;


function formatDateTime(
    value: string | null,
): string {
    if (!value) {
        return "Нет данных";
    }

    return new Date(value)
        .toLocaleString("ru-RU");
}


function eventValue(
    event: JournalEvent,
): string {
    if (event.raw_value) {
        return event.raw_value;
    }

    if (event.state_value) {
        return event.state_value;
    }

    if (event.numeric_value !== null) {
        return String(event.numeric_value);
    }

    return "Нет значения";
}


function EventJournalPage() {
    const navigate = useNavigate();

    const [events, setEvents] =
        useState<JournalEvent[]>([]);

    const [offset, setOffset] =
        useState(0);

    const [hasMore, setHasMore] =
        useState(false);

    const [alarmFilter, setAlarmFilter] =
        useState<AlarmFilter>("all");

    const [search, setSearch] =
        useState("");

    const [loading, setLoading] =
        useState(true);

    const [refreshing, setRefreshing] =
        useState(false);

    const [error, setError] =
        useState<string | null>(null);


    async function loadEvents(
        nextOffset = offset,
        background = false,
    ) {
        try {
            if (background) {
                setRefreshing(true);
            } else {
                setLoading(true);
            }

            setError(null);

            const alarm =
                alarmFilter === "all"
                    ? null
                    : alarmFilter === "alarm";

            const data = await getEvents({
                limit: PAGE_SIZE,
                offset: nextOffset,
                alarm,
            });

            setEvents(data.events);
            setHasMore(data.has_more);
            setOffset(data.offset);
        } catch (error) {
            setError(
                error instanceof Error
                    ? error.message
                    : "Не удалось получить журнал событий",
            );
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }


    useEffect(() => {
        void loadEvents(0);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [alarmFilter]);


    const filteredEvents = useMemo(() => {
        const query =
            search
                .trim()
                .toLowerCase();

        if (!query) {
            return events;
        }

        return events.filter((event) => {
            return [
                event.object_name,
                event.sensor_name,
                event.sensor_type,
                event.system_type,
                event.raw_value,
                event.state_value,
                String(event.event_id),
                String(event.channel_id),
                event.object_id !== null
                    ? String(event.object_id)
                    : null,
            ]
                .filter(Boolean)
                .some((value) =>
                    String(value)
                        .toLowerCase()
                        .includes(query),
                );
        });
    }, [events, search]);


    function openEventOnMap(
        event: JournalEvent,
    ) {
        if (event.object_id === null) {
            return;
        }

        navigate(
            `/?objectId=${event.object_id}&channelId=${event.channel_id}`,
        );
    }


    return (
        <div className="events-page">
            <header className="events-header">
                <div>
                    <span className="page-eyebrow">
                        Мониторинг
                    </span>
                    <h1>Журнал событий</h1>
                    <p>
                        Последние события датчиков с переходом
                        к объекту и конкретному каналу на карте.
                    </p>
                </div>

                <button
                    type="button"
                    className="events-refresh-button"
                    disabled={loading || refreshing}
                    onClick={() =>
                        void loadEvents(
                            offset,
                            true,
                        )
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

            <section className="events-panel">
                <div className="events-toolbar">
                    <div className="events-search">
                        <Search size={16} />
                        <input
                            value={search}
                            placeholder="Поиск в текущей странице журнала..."
                            onChange={(event) =>
                                setSearch(
                                    event.target.value,
                                )
                            }
                        />
                    </div>

                    <div className="events-filter">
                        <Filter size={14} />
                        <select
                            value={alarmFilter}
                            onChange={(event) => {
                                setOffset(0);
                                setAlarmFilter(
                                    event.target.value as AlarmFilter,
                                );
                            }}
                        >
                            <option value="all">
                                Все события
                            </option>
                            <option value="alarm">
                                Только тревожные
                            </option>
                            <option value="normal">
                                Без тревоги
                            </option>
                        </select>
                    </div>
                </div>

                {error ? (
                    <div className="events-message error">
                        {error}
                    </div>
                ) : loading ? (
                    <div className="events-message">
                        Загрузка событий...
                    </div>
                ) : filteredEvents.length === 0 ? (
                    <div className="events-message">
                        События не найдены
                    </div>
                ) : (
                    <div className="events-table-wrap">
                        <table className="events-table">
                            <thead>
                                <tr>
                                    <th>Время</th>
                                    <th>Статус</th>
                                    <th>Объект</th>
                                    <th>Датчик</th>
                                    <th>Тип</th>
                                    <th>Значение</th>
                                    <th>ID события</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredEvents.map(
                                    (event) => (
                                        <tr
                                            key={event.row_id}
                                            className={
                                                event.object_id !== null
                                                    ? "event-row-clickable"
                                                    : undefined
                                            }
                                            tabIndex={
                                                event.object_id !== null
                                                    ? 0
                                                    : undefined
                                            }
                                            onClick={() =>
                                                openEventOnMap(event)
                                            }
                                            onKeyDown={(keyboardEvent) => {
                                                if (
                                                    keyboardEvent.key === "Enter" ||
                                                    keyboardEvent.key === " "
                                                ) {
                                                    keyboardEvent.preventDefault();
                                                    openEventOnMap(event);
                                                }
                                            }}
                                        >
                                            <td className="event-time-cell">
                                                {formatDateTime(
                                                    event.event_time,
                                                )}
                                            </td>
                                            <td>
                                                <span
                                                    className={
                                                        event.alarm
                                                            ? "event-status alarm"
                                                            : event.alarm === false
                                                                ? "event-status normal"
                                                                : "event-status unknown"
                                                    }
                                                >
                                                    {event.alarm
                                                        ? "Тревога"
                                                        : event.alarm === false
                                                            ? "Норма"
                                                            : "Не определено"}
                                                </span>
                                            </td>
                                            <td>
                                                <div className="event-main-cell">
                                                    <strong>
                                                        {event.object_name ??
                                                            "Объект не определён"}
                                                    </strong>
                                                    {event.object_id !== null && (
                                                        <span>
                                                            ID {event.object_id}
                                                        </span>
                                                    )}
                                                </div>
                                            </td>
                                            <td>
                                                <div className="event-main-cell">
                                                    <strong>
                                                        {event.sensor_name ??
                                                            `Канал ${event.channel_id}`}
                                                    </strong>
                                                    <span>
                                                        Канал {event.channel_id}
                                                    </span>
                                                </div>
                                            </td>
                                            <td>
                                                {event.sensor_type ??
                                                    "Не указан"}
                                            </td>
                                            <td>
                                                <span className="event-value">
                                                    {eventValue(event)}
                                                </span>
                                            </td>
                                            <td>
                                                {event.event_id}
                                            </td>
                                        </tr>
                                    ),
                                )}
                            </tbody>
                        </table>
                    </div>
                )}

                <div className="events-pagination">
                    <span>
                        Записи {offset + 1}–{offset + events.length}
                    </span>

                    <div>
                        <button
                            type="button"
                            disabled={offset === 0 || loading}
                            onClick={() =>
                                void loadEvents(
                                    Math.max(
                                        0,
                                        offset - PAGE_SIZE,
                                    ),
                                )
                            }
                        >
                            <ChevronLeft size={15} />
                            Назад
                        </button>

                        <button
                            type="button"
                            disabled={!hasMore || loading}
                            onClick={() =>
                                void loadEvents(
                                    offset + PAGE_SIZE,
                                )
                            }
                        >
                            Далее
                            <ChevronRight size={15} />
                        </button>
                    </div>
                </div>
            </section>
        </div>
    );
}


export default EventJournalPage;
