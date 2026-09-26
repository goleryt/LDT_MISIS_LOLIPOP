import SensorIcon from "../components/SensorIcon";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
    ArrowRight, ArrowUpDown, Building2, Check, ChevronDown,
    ChevronLeft, ChevronRight, CircleAlert, CircleHelp, Clock3,
    Map, RefreshCw, Search, TriangleAlert,
} from "lucide-react";

import { getEvents } from "../api/events";
import type { JournalEvent } from "../types/events";

type AlarmFilter = "all" | "alarm" | "normal" | "unknown";
type SortBy = "time" | "object" | "sensor" | "event" | "status";
type TextFilter = "object" | "sensor" | "event";
type TextFilters = Record<TextFilter, string>;

const PAGE_SIZE = 50;
const EMPTY_FILTERS: TextFilters = { object: "", sensor: "", event: "" };
const FILTER_LABELS: Record<TextFilter, string> = {
    object: "Объект", sensor: "Датчик", event: "Событие",
};

function formatDateTime(value: string | null): string {
    if (!value) return "Нет времени";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const time = new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(date);
    const day = new Intl.DateTimeFormat("ru-RU", {
        day: "numeric", month: "long", year: "numeric",
    }).format(date);
    return `${time} ${day}`;
}

function eventValue(event: JournalEvent): string {
    return event.raw_value?.trim()
        || event.state_value?.trim()
        || (event.numeric_value !== null ? String(event.numeric_value) : null)
        || `Событие #${event.event_id}`;
}

function EventJournalPage() {
    const navigate = useNavigate();
    const requestSequence = useRef(0);
    const [events, setEvents] = useState<JournalEvent[]>([]);
    const [offset, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [timeFrom, setTimeFrom] = useState("");
    const [timeTo, setTimeTo] = useState("");
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [alarmFilter, setAlarmFilter] = useState<AlarmFilter>("all");
    const [sort, setSort] = useState<{ by: SortBy; desc: boolean }>({ by: "time", desc: true });
    const [openFilter, setOpenFilter] = useState<TextFilter | null>(null);
    const [filterInputs, setFilterInputs] = useState<TextFilters>(EMPTY_FILTERS);
    const [appliedFilters, setAppliedFilters] = useState<TextFilters>(EMPTY_FILTERS);
    const invalidRange = Boolean(timeFrom && timeTo && timeFrom > timeTo);

    const loadEvents = useCallback(async (nextOffset: number, background = false) => {
        const sequence = ++requestSequence.current;
        if (invalidRange) {
            setError(null);
            setEvents([]);
            setHasMore(false);
            setOffset(0);
            setLoading(false);
            setRefreshing(false);
            return;
        }
        if (background) setRefreshing(true);
        else setLoading(true);
        setError(null);
        try {
            const data = await getEvents({
                limit: PAGE_SIZE,
                offset: nextOffset,
                timeFrom: timeFrom || undefined,
                timeTo: timeTo || undefined,
                alarmState: alarmFilter,
                objectQuery: appliedFilters.object || undefined,
                sensorQuery: appliedFilters.sensor || undefined,
                eventQuery: appliedFilters.event || undefined,
                sortBy: sort.by,
                sortDesc: sort.desc,
            });
            if (sequence !== requestSequence.current) return;
            setEvents(data.events);
            setHasMore(data.has_more);
            setOffset(data.offset);
        } catch (cause) {
            if (sequence !== requestSequence.current) return;
            setEvents([]);
            setHasMore(false);
            setError(cause instanceof Error ? cause.message : "Не удалось получить журнал событий");
        } finally {
            if (sequence === requestSequence.current) {
                setLoading(false);
                setRefreshing(false);
            }
        }
    }, [alarmFilter, appliedFilters, invalidRange, sort, timeFrom, timeTo]);

    useEffect(() => { void loadEvents(0); }, [loadEvents]);
    useEffect(() => {
        if (!autoRefresh) return;
        const timer = window.setInterval(() => { void loadEvents(offset, true); }, 60_000);
        return () => window.clearInterval(timer);
    }, [autoRefresh, loadEvents, offset]);

    function changeSort(by: SortBy) {
        setSort((current) => ({
            by,
            desc: current.by === by ? !current.desc : by === "time",
        }));
    }

    function applyTextFilter(key: TextFilter) {
        setAppliedFilters((current) => ({ ...current, [key]: filterInputs[key].trim() }));
        setOpenFilter(null);
    }

    function clearTextFilter(key: TextFilter) {
        setFilterInputs((current) => ({ ...current, [key]: "" }));
        setAppliedFilters((current) => ({ ...current, [key]: "" }));
        setOpenFilter(null);
    }

    function openEventOnMap(event: JournalEvent) {
        if (event.object_id === null) return;
        navigate(`/?objectId=${event.object_id}&channelId=${event.channel_id}`);
    }

    function textFilterHeader(key: TextFilter) {
        return (
            <div className="journal-column-controls">
                <div className="journal-filter-anchor">
                    <button
                        type="button"
                        className={`journal-filter-trigger ${appliedFilters[key] ? "active" : ""}`}
                        aria-expanded={openFilter === key}
                        onClick={() => setOpenFilter((current) => current === key ? null : key)}
                    >
                        {FILTER_LABELS[key]} <ChevronDown size={16} />
                    </button>
                    {openFilter === key && (
                        <div className="journal-filter-popover">
                            <label htmlFor={`journal-${key}-filter`}>
                                Поиск: {FILTER_LABELS[key].toLowerCase()}
                            </label>
                            <div className="journal-filter-input">
                                <Search size={16} />
                                <input
                                    id={`journal-${key}-filter`}
                                    value={filterInputs[key]}
                                    onChange={(event) => setFilterInputs((current) => ({
                                        ...current, [key]: event.target.value,
                                    }))}
                                    onKeyDown={(event) => {
                                        if (event.key === "Enter") applyTextFilter(key);
                                        if (event.key === "Escape") setOpenFilter(null);
                                    }}
                                    placeholder="Название или ID"
                                />
                            </div>
                            <div className="journal-filter-actions">
                                <button type="button" onClick={() => clearTextFilter(key)}>Сбросить</button>
                                <button type="button" onClick={() => applyTextFilter(key)}>Применить</button>
                            </div>
                        </div>
                    )}
                </div>
                <button
                    type="button"
                    className={`journal-sort-button ${sort.by === key ? "active" : ""}`}
                    aria-label={`Сортировать: ${FILTER_LABELS[key].toLowerCase()}`}
                    onClick={() => changeSort(key)}
                >
                    <ArrowUpDown size={18} />
                </button>
            </div>
        );
    }

    const pageStart = events.length > 0 ? offset + 1 : 0;
    const pageEnd = offset + events.length;

    return (
        <div className="events-page journal-page">
            <h1 className="journal-visually-hidden">Журнал событий</h1>
            <header className="journal-topbar">
                <button
                    type="button"
                    className="journal-icon-button journal-refresh"
                    aria-label="Обновить журнал"
                    title="Обновить журнал"
                    disabled={loading || refreshing || invalidRange}
                    onClick={() => void loadEvents(offset, true)}
                >
                    <RefreshCw size={22} className={refreshing ? "spinning" : undefined} />
                </button>
                <div className="journal-period" role="group" aria-label="Период событий">
                    <Clock3 size={21} />
                    <input
                        type="datetime-local" step={1} value={timeFrom}
                        aria-label="Начало периода" title="Начало периода"
                        onChange={(event) => setTimeFrom(event.target.value)}
                    />
                    <ArrowRight size={20} />
                    <input
                        type="datetime-local" step={1} value={timeTo}
                        aria-label="Конец периода" title="Конец периода"
                        onChange={(event) => setTimeTo(event.target.value)}
                    />
                </div>
                <div className="journal-live-controls">
                    <CircleAlert
                        size={22}
                        className={invalidRange ? "journal-range-alert invalid" : "journal-range-alert"}
                        aria-label={invalidRange ? "Начало периода позже конца" : "Период можно оставить пустым"}
                    />
                    <label className="journal-auto-refresh">
                        <input type="checkbox" checked={autoRefresh}
                            onChange={(event) => setAutoRefresh(event.target.checked)} />
                        <span className="journal-switch" aria-hidden="true" />
                        Автообновление
                    </label>
                </div>
                <nav className="journal-top-nav" aria-label="Быстрый переход">
                    <Link to="/" aria-label="Открыть карту" title="Открыть карту">
                        <Map size={21} />
                    </Link>
                </nav>
            </header>

            {invalidRange && (
                <p className="journal-validation" role="alert">
                    Начало периода должно быть раньше конца.
                </p>
            )}

            <section className="journal-board" aria-label="События датчиков">
                <div className="events-table-wrap">
                    <table className="events-table journal-table">
                        <thead>
                            <tr>
                                <th aria-sort={sort.by === "time" ? (sort.desc ? "descending" : "ascending") : "none"}>
                                    <button type="button" className="journal-time-sort" onClick={() => changeSort("time")}>
                                        Время <ArrowUpDown size={19} />
                                    </button>
                                </th>
                                <th aria-sort={sort.by === "object" ? (sort.desc ? "descending" : "ascending") : "none"}>
                                    {textFilterHeader("object")}
                                </th>
                                <th aria-sort={sort.by === "sensor" ? (sort.desc ? "descending" : "ascending") : "none"}>
                                    {textFilterHeader("sensor")}
                                </th>
                                <th aria-sort={sort.by === "event" ? (sort.desc ? "descending" : "ascending") : "none"}>
                                    {textFilterHeader("event")}
                                </th>
                                <th aria-sort={sort.by === "status" ? (sort.desc ? "descending" : "ascending") : "none"}>
                                    <div className="journal-column-controls">
                                        <select
                                            className="journal-status-filter"
                                            aria-label="Фильтр по типу события"
                                            value={alarmFilter}
                                            onChange={(event) => setAlarmFilter(event.target.value as AlarmFilter)}
                                        >
                                            <option value="all">Тип события</option>
                                            <option value="normal">Норма</option>
                                            <option value="alarm">Тревога</option>
                                            <option value="unknown">Не определено</option>
                                        </select>
                                        <button
                                            type="button"
                                            className={`journal-sort-button ${sort.by === "status" ? "active" : ""}`}
                                            aria-label="Сортировать: тип события"
                                            onClick={() => changeSort("status")}
                                        >
                                            <ArrowUpDown size={18} />
                                        </button>
                                    </div>
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {error || loading || events.length === 0 ? (
                                <tr><td colSpan={5} className={`journal-empty ${error ? "error" : ""}`}>
                                    {error || (loading ? "Загрузка событий…" : "События не найдены")}
                                </td></tr>
                            ) : events.map((event) => (
                                <tr
                                    key={event.row_id}
                                    className={event.object_id !== null ? "event-row-clickable" : undefined}
                                    tabIndex={event.object_id !== null ? 0 : undefined}
                                    onClick={() => openEventOnMap(event)}
                                    onKeyDown={(keyboardEvent) => {
                                        if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
                                            keyboardEvent.preventDefault();
                                            openEventOnMap(event);
                                        }
                                    }}
                                >
                                    <td><span className="journal-cell-inline journal-time-cell">
                                        <Clock3 size={17} />
                                        <time dateTime={event.event_time ?? undefined}>
                                            {formatDateTime(event.event_time)}
                                        </time>
                                    </span></td>
                                    <td><span className="journal-cell-inline">
                                        <Building2 size={17} />
                                        <span>{event.object_name ?? (event.object_id !== null ? `Объект #${event.object_id}` : "Объект не определён")}</span>
                                    </span></td>
                                    <td><span className="journal-cell-inline">
                                        <SensorIcon sensorType={event.sensor_type} name={event.sensor_name} size={17} />
                                        <span className="journal-sensor-cell" title={event.sensor_type ?? undefined}>
                                            {event.sensor_name ?? `Канал #${event.channel_id}`}
                                        </span>
                                    </span></td>
                                    <td><span className="journal-cell-inline journal-event-cell" title={`ID события: ${event.event_id}`}>
                                        <span className="journal-event-glyph">#</span>
                                        <span>{eventValue(event)}</span>
                                    </span></td>
                                    <td><span className={`journal-kind ${event.alarm === true ? "alarm" : event.alarm === false ? "normal" : "unknown"}`}>
                                        {event.alarm === true ? <TriangleAlert size={19} /> : event.alarm === false ? <Check size={20} /> : <CircleHelp size={19} />}
                                        {event.alarm === true ? "Тревога" : event.alarm === false ? "Норма" : "Не определено"}
                                    </span></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <footer className="journal-footer">
                    <span>Записи {pageStart}–{pageEnd}</span>
                    <div>
                        <button type="button" disabled={offset === 0 || loading}
                            onClick={() => void loadEvents(Math.max(0, offset - PAGE_SIZE))}>
                            <ChevronLeft size={17} /> Назад
                        </button>
                        <button type="button" disabled={!hasMore || loading}
                            onClick={() => void loadEvents(offset + PAGE_SIZE)}>
                            Далее <ChevronRight size={17} />
                        </button>
                    </div>
                </footer>
            </section>
        </div>
    );
}

export default EventJournalPage;
