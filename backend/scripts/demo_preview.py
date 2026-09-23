"""Small in-memory API for reviewing the map without a database.

Every object, channel, event, and coordinate served here is invented.
Run with ``python -m scripts.demo_preview --port 8001`` from ``backend``.
Never use this server as evidence of model quality or physical location.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


OBJECT_IDS = range(101, 113)
ALARM_OBJECT_IDS = {101, 105, 110}
NO_EVENT_OBJECT_IDS = {103, 108}
SENSOR_KINDS = (
    ("Контроль доступа", "Контактный", None),
    ("Температура", "Температурный", "°C"),
    ("Контроль питания", "Состояние", None),
    ("Дым", "Дымовой", None),
)


def synthetic_point(object_id: int) -> tuple[float, float]:
    """Mirror the production map's stable, explicitly fictitious placement."""
    digest = hashlib.sha256(str(object_id).encode("utf-8")).digest()
    longitude = 37.35 + int.from_bytes(digest[:8], "big") / ((1 << 64) - 1) * 0.5
    latitude = 55.55 + int.from_bytes(digest[8:16], "big") / ((1 << 64) - 1) * 0.4
    return round(longitude, 6), round(latitude, 6)


def make_demo_data() -> tuple[list[dict], dict[int, list[dict]], dict[int, list[dict]], list[dict]]:
    objects: list[dict] = []
    sensors_by_object: dict[int, list[dict]] = {}
    history_by_channel: dict[int, list[dict]] = {}
    journal: list[dict] = []

    for object_id in OBJECT_IDS:
        object_name = f"Демо-объект {object_id}"
        sensors: list[dict] = []

        for sensor_index, (label, sensor_type, _unit) in enumerate(SENSOR_KINDS):
            channel_id = object_id * 10 + sensor_index + 1
            sensor_name = f"{label} · канал {channel_id}"
            has_events = object_id not in NO_EVENT_OBJECT_IDS and sensor_index != 3
            events: list[dict] = []

            if has_events:
                for day_index, day in enumerate((20, 21, 22)):
                    alarm = object_id in ALARM_OBJECT_IDS and sensor_index in (0, 2) and day_index == 2
                    numeric = round(19.8 + (object_id % 4) * 0.6 + day_index * 0.3, 1) if sensor_index == 1 else None
                    state = None if numeric is not None else ("Открыто" if alarm else "Норма")
                    event = {
                        "id": channel_id * 10 + day_index,
                        "event_id": channel_id * 10 + day_index,
                        "event_time": f"2026-09-{day:02d}T{10 + sensor_index:02d}:00:00",
                        "alarm": alarm,
                        "raw_value": str(numeric) if numeric is not None else state,
                        "numeric_value": numeric,
                        "state_value": state,
                    }
                    events.append(event)
                    journal.append({
                        "row_id": event["id"],
                        "event_id": event["event_id"],
                        "channel_id": channel_id,
                        "object_id": object_id,
                        "object_name": object_name,
                        "sensor_name": sensor_name,
                        "sensor_type": sensor_type,
                        "system_type": "Демонстрационная система",
                        **{key: event[key] for key in (
                            "event_time", "alarm", "raw_value", "numeric_value", "state_value"
                        )},
                    })

            history_by_channel[channel_id] = events
            latest = events[-1] if events else None
            sensors.append({
                "channel_id": channel_id,
                "name": sensor_name,
                "sensor_type": sensor_type,
                "system_type": "Демонстрационная система",
                "tag": f"DEMO-{object_id}-{sensor_index + 1}",
                "site": None,
                "picket": None,
                "status": "alarm" if latest and latest["alarm"] else "normal" if latest else "unknown",
                "has_data": latest is not None,
                "alarm": latest["alarm"] if latest else None,
                "last_event_time": latest["event_time"] if latest else None,
                "latest_value_raw": latest["raw_value"] if latest else None,
                "latest_value_numeric": latest["numeric_value"] if latest else None,
                "latest_value_state": latest["state_value"] if latest else None,
            })

        sensors_by_object[object_id] = sensors
        alarm_count = sum(sensor["status"] == "alarm" for sensor in sensors)
        with_data = sum(sensor["has_data"] for sensor in sensors)
        last_event_time = max(
            (sensor["last_event_time"] for sensor in sensors if sensor["last_event_time"]),
            default=None,
        )
        objects.append({
            "object_id": object_id,
            "name": object_name,
            "object_type": "Демонстрационная запись",
            "status": "alarm" if alarm_count else "normal" if with_data else "unknown",
            "sensor_count": len(sensors),
            "sensors_with_data": with_data,
            "alarm_sensor_count": alarm_count,
            "last_event_time": last_event_time,
            "geometry": {"type": "Point", "coordinates": synthetic_point(object_id)},
            "geometry_is_synthetic": True,
            "data_is_synthetic": True,
        })

    return objects, sensors_by_object, history_by_channel, journal


OBJECTS, SENSORS_BY_OBJECT, HISTORY_BY_CHANNEL, JOURNAL = make_demo_data()
OBJECT_BY_ID = {item["object_id"]: item for item in OBJECTS}
SENSOR_BY_CHANNEL = {
    sensor["channel_id"]: (object_id, sensor)
    for object_id, sensors in SENSORS_BY_OBJECT.items()
    for sensor in sensors
}


def filtered_events(query: dict[str, list[str]]) -> dict:
    rows = list(JOURNAL)
    for field, parameter in (
        ("object_name", "object_query"),
        ("sensor_name", "sensor_query"),
        ("raw_value", "event_query"),
    ):
        value = query.get(parameter, [""])[0].lower()
        if value:
            rows = [row for row in rows if value in str(row[field]).lower()]

    state = query.get("alarm_state", ["all"])[0]
    if state in {"alarm", "normal", "unknown"}:
        wanted = {"alarm": True, "normal": False, "unknown": None}[state]
        rows = [row for row in rows if row["alarm"] is wanted]

    start = query.get("time_from", [""])[0]
    end = query.get("time_to", [""])[0]
    if start:
        rows = [row for row in rows if row["event_time"] >= start]
    if end:
        rows = [row for row in rows if row["event_time"] <= end]

    sort_field = {
        "time": "event_time",
        "object": "object_name",
        "sensor": "sensor_name",
        "event": "event_id",
        "status": "alarm",
    }.get(query.get("sort_by", ["time"])[0], "event_time")
    rows.sort(
        key=lambda row: (row[sort_field] is None, str(row[sort_field])),
        reverse=query.get("sort_desc", ["true"])[0] == "true",
    )
    offset = max(0, int(query.get("offset", ["0"])[0]))
    limit = min(200, max(1, int(query.get("limit", ["50"])[0])))
    page = rows[offset:offset + limit]
    return {
        "limit": limit,
        "offset": offset,
        "returned": len(page),
        "has_more": len(rows) > offset + limit,
        "events": page,
    }


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            payload = {"status": "demo", "data_is_synthetic": True}
        elif parsed.path == "/api/v1/map/objects":
            payload = OBJECTS
        elif parsed.path == "/api/v1/events":
            payload = filtered_events(query)
        elif len(parts) == 5 and parts[:3] == ["api", "v1", "objects"] and parts[4] == "sensors":
            object_id = int(parts[3])
            item = OBJECT_BY_ID.get(object_id)
            if item is None:
                self.send_error(404)
                return
            payload = {
                "object_id": object_id,
                "name": item["name"],
                "object_type": item["object_type"],
                "sensor_count": item["sensor_count"],
                "sensors": SENSORS_BY_OBJECT[object_id],
            }
        elif len(parts) == 5 and parts[:3] == ["api", "v1", "sensors"] and parts[4] == "history":
            channel_id = int(parts[3])
            linked = SENSOR_BY_CHANNEL.get(channel_id)
            if linked is None:
                self.send_error(404)
                return
            object_id, sensor = linked
            limit = min(200, max(1, int(query.get("limit", ["200"])[0])))
            events = HISTORY_BY_CHANNEL[channel_id][-limit:]
            payload = {
                "channel_id": channel_id,
                "name": sensor["name"],
                "sensor_type": sensor["sensor_type"],
                "system_type": sensor["system_type"],
                "object_id": object_id,
                "returned_events": len(events),
                "numeric_event_count": sum(event["numeric_value"] is not None for event in events),
                "alarm_event_count": sum(event["alarm"] is True for event in events),
                "events": events,
            }
        else:
            self.send_error(404)
            return

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Demo-Data", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"Synthetic demo API: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
