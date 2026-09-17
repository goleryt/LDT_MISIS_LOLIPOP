import csv
import re
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    ChannelCatalogue,
    EventsJournal,
    ObjectCatalogue,
)

from app.db.session import SessionLocal
from app.ingestion.validators import validate_required_columns

import hashlib
import json




CHANNEL_REQUIRED_COLUMNS = {
    "ид_канала_данных",
    "тип_инж_системы",
    "тип_датчика",
    "тег_инженерной_системы",
    "название_датчика",
}

OBJECT_REQUIRED_COLUMNS = {
    "ид_объект",
    "иерархия_уровень",
    "родитель",
    "вид_объекта",
    "диспетчерское_название_объекта",
}

EVENT_COLUMNS = (
    "ид_события",
    "ид_канала_данных",
    "дата",
    "время",
    "тревожное",
    "значение_датчика",
)

EVENT_REQUIRED_COLUMNS = set(EVENT_COLUMNS)

EVENT_BATCH_SIZE = 2000

CHANNEL_BATCH_SIZE = 1000


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    return value if value else None


def optional_int(
    value: str | None,
    *,
    field_name: str,
    row_number: int,
) -> int | None:
    normalized = empty_to_none(value)

    if normalized is None:
        return None

    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} at row "
            f"{row_number}: {normalized!r}"
        ) from exc


def parse_alarm(
    value: str | None,
    *,
    row_number: int,
) -> bool:
    if value is None:
        raise ValueError(
            f"Missing тревожное at row {row_number}"
        )

    normalized = value.strip().lower()

    if normalized in {"true", "t"}:
        return True

    if normalized in {"false", "f"}:
        return False

    raise ValueError(
        f"Invalid тревожное at row "
        f"{row_number}: {value!r}"
    )


def parse_sensor_value(
    value: str | None,
) -> tuple[float | None, str | None]:
    normalized = empty_to_none(value)

    if normalized is None:
        return None, None

    try:
        return (
            float(normalized.replace(",", ".")),
            None,
        )
    except ValueError:
        return None, normalized


def extract_site(tag: str | None) -> str | None:
    if not tag:
        return None

    first_part = tag.split("-", maxsplit=1)[0].strip()

    return first_part or None


def extract_picket(sensor_name: str | None) -> int | None:
    if not sensor_name:
        return None

    match = re.search(
        r"ПК\s*(\d+)",
        sensor_name,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    return int(match.group(1))


def _upsert_channel_batch(
    session: Session,
    rows: list[dict],
) -> None:
    if not rows:
        return

    statement = insert(ChannelCatalogue).values(rows)

    statement = statement.on_conflict_do_update(
        index_elements=[ChannelCatalogue.ид_канала_данных],
        set_={
            "тип_инж_системы":
                statement.excluded.тип_инж_системы,
            "тип_датчика":
                statement.excluded.тип_датчика,
            "тег_инженерной_системы":
                statement.excluded.тег_инженерной_системы,
            "название_датчика":
                statement.excluded.название_датчика,
            "d_site":
                statement.excluded.d_site,
            "d_pk":
                statement.excluded.d_pk,
        },
    )

    session.execute(statement)


def _upsert_object_batch(
    session: Session,
    rows: list[dict],
) -> None:
    if not rows:
        return

    statement = insert(ObjectCatalogue).values(rows)

    statement = statement.on_conflict_do_update(
        index_elements=[ObjectCatalogue.ид_объект],
        set_={
            "иерархия_уровень":
                statement.excluded.иерархия_уровень,
            "родитель":
                statement.excluded.родитель,
            "вид_объекта":
                statement.excluded.вид_объекта,
            "диспетчерское_название_объекта":
                statement.excluded.диспетчерское_название_объекта,
        },
    )

    session.execute(statement)


def load_channel_catalogue(
    file_path: str | Path,
) -> int:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {path}"
        )

    processed_rows = 0
    batch: list[dict] = []

    with SessionLocal() as session:
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as file:
                reader = csv.DictReader(file)

                if reader.fieldnames is None:
                    raise ValueError(
                        "CSV file does not contain a header"
                    )

                validate_required_columns(
                    reader.fieldnames,
                    CHANNEL_REQUIRED_COLUMNS,
                )

                for row_number, row in enumerate(
                    reader,
                    start=2,
                ):
                    raw_channel_id = (
                        row["ид_канала_данных"].strip()
                    )

                    if not raw_channel_id:
                        raise ValueError(
                            "Empty ид_канала_данных "
                            f"at row {row_number}"
                        )

                    try:
                        channel_id = int(raw_channel_id)
                    except ValueError as exc:
                        raise ValueError(
                            "Invalid ид_канала_данных "
                            f"at row {row_number}: "
                            f"{raw_channel_id!r}"
                        ) from exc

                    tag = empty_to_none(
                        row["тег_инженерной_системы"]
                    )

                    sensor_name = empty_to_none(
                        row["название_датчика"]
                    )

                    batch.append(
                        {
                            "ид_канала_данных":
                                channel_id,
                            "тип_инж_системы":
                                empty_to_none(
                                    row["тип_инж_системы"]
                                ),
                            "тип_датчика":
                                empty_to_none(
                                    row["тип_датчика"]
                                ),
                            "тег_инженерной_системы":
                                tag,
                            "название_датчика":
                                sensor_name,
                            "d_site":
                                extract_site(tag),
                            "d_pk":
                                extract_picket(
                                    sensor_name
                                ),
                        }
                    )

                    if len(batch) >= CHANNEL_BATCH_SIZE:
                        _upsert_channel_batch(
                            session,
                            batch,
                        )

                        processed_rows += len(batch)
                        batch.clear()

                if batch:
                    _upsert_channel_batch(
                        session,
                        batch,
                    )

                    processed_rows += len(batch)

            session.commit()

        except Exception:
            session.rollback()
            raise

    return processed_rows


def load_object_catalogue(
    file_path: str | Path,
) -> int:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {path}"
        )

    rows: list[dict] = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError(
                "CSV file does not contain a header"
            )

        validate_required_columns(
            reader.fieldnames,
            OBJECT_REQUIRED_COLUMNS,
        )

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            raw_object_id = row["ид_объект"].strip()

            if not raw_object_id:
                raise ValueError(
                    f"Empty ид_объект at row {row_number}"
                )

            try:
                object_id = int(raw_object_id)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid ид_объект at row "
                    f"{row_number}: {raw_object_id!r}"
                ) from exc

            rows.append(
                {
                    "ид_объект":
                        object_id,
                    "иерархия_уровень":
                        optional_int(
                            row["иерархия_уровень"],
                            field_name="иерархия_уровень",
                            row_number=row_number,
                        ),
                    "родитель":
                        optional_int(
                            row["родитель"],
                            field_name="родитель",
                            row_number=row_number,
                        ),
                    "вид_объекта":
                        empty_to_none(
                            row["вид_объекта"]
                        ),
                    "диспетчерское_название_объекта":
                        empty_to_none(
                            row[
                                "диспетчерское_название_объекта"
                            ]
                        ),
                }
            )

    if not rows:
        return 0

    with SessionLocal() as session:
        try:
            _upsert_object_batch(
                session,
                rows,
            )

            session.commit()

        except Exception:
            session.rollback()
            raise

    return len(rows)

def parse_event_date(
    value: str | None,
    *,
    row_number: int,
) -> date:
    if value is None:
        raise ValueError(
            f"Missing дата at row {row_number}"
        )

    normalized = value.strip()

    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid дата at row "
            f"{row_number}: {value!r}"
        ) from exc


def parse_event_time(
    value: str | None,
    *,
    row_number: int,
) -> time:
    if value is None:
        raise ValueError(
            f"Missing время at row {row_number}"
        )

    normalized = value.strip()

    try:
        return time.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid время at row "
            f"{row_number}: {value!r}"
        ) from exc

def parse_required_int(
    value: str | None,
    *,
    field_name: str,
    row_number: int,
) -> int:
    if value is None:
        raise ValueError(
            f"Missing {field_name} at row {row_number}"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"Empty {field_name} at row {row_number}"
        )

    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} at row "
            f"{row_number}: {value!r}"
        ) from exc


def is_repeated_event_header(row: dict[str, str | None]) -> bool:
    return (
        row.get("ид_события") == "ид_события"
        or row.get("дата") == "дата"
    )


def parse_event_row(
    row: dict[str, str | None],
    *,
    row_number: int,
) -> dict:
    event_id = parse_required_int(
        row["ид_события"],
        field_name="ид_события",
        row_number=row_number,
    )

    channel_id = parse_required_int(
        row["ид_канала_данных"],
        field_name="ид_канала_данных",
        row_number=row_number,
    )

    raw_date = row["дата"]

    if raw_date is None:
        raise ValueError(
            f"Missing дата at row {row_number}"
        )

    raw_time = row["время"]

    if raw_time is None:
        raise ValueError(
            f"Missing время at row {row_number}"
        )

    raw_alarm = row["тревожное"]

    if raw_alarm is None:
        raise ValueError(
            f"Missing тревожное at row {row_number}"
        )

    raw_date = raw_date.strip()
    raw_time = raw_time.strip()
    raw_alarm = raw_alarm.strip()

    event_date = parse_event_date(
        raw_date,
        row_number=row_number,
    )

    event_time = parse_event_time(
        raw_time,
        row_number=row_number,
    )

    alarm = parse_alarm(
        raw_alarm,
        row_number=row_number,
    )

    raw_sensor_value = empty_to_none(
        row["значение_датчика"]
    )

    value_numeric, value_state = (
        parse_sensor_value(raw_sensor_value)
    )

    return {
        "ид_события": event_id,
        "ид_канала_данных": channel_id,

        "дата": raw_date,
        "время": raw_time,
        "тревожное": raw_alarm,
        "значение_датчика": raw_sensor_value,

        "d_event_time": datetime.combine(
            event_date,
            event_time,
        ),
        "d_alarm": alarm,
        "d_value_numeric": value_numeric,
        "d_value_state": value_state,

        "d_row_hash": compute_row_hash(
            event_id=event_id,
            channel_id=channel_id,
            event_date=raw_date,
            event_time=raw_time,
            alarm=raw_alarm,
            sensor_value=raw_sensor_value,
        ),
    }

def audit_events_csv(
    file_path: str | Path,
) -> dict[str, int]:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {path}"
        )

    total_rows = 0
    valid_rows = 0
    alarm_rows = 0
    repeated_headers = 0
    exact_duplicates = 0

    seen_rows: set[tuple[str | None, ...]] = set()

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError(
                "CSV file does not contain a header"
            )

        validate_required_columns(
            reader.fieldnames,
            EVENT_REQUIRED_COLUMNS,
        )

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            total_rows += 1

            if is_repeated_event_header(row):
                repeated_headers += 1
                continue


            parsed = parse_event_row(
                row,
                row_number=row_number,
            )

            valid_rows += 1

            if parsed["d_alarm"]:
                alarm_rows += 1

    return {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "alarm_rows": alarm_rows,
        "repeated_headers": repeated_headers,
        "exact_duplicates": exact_duplicates,
    }


def _insert_event_batch(
    session: Session,
    rows: list[dict],
) -> int:
    if not rows:
        return 0

    statement = insert(
        EventsJournal
    ).values(rows)

    statement = statement.on_conflict_do_nothing(
        index_elements=[
            EventsJournal.d_row_hash,
        ],
    ).returning(
        EventsJournal.id
    )

    result = session.execute(statement)

    return len(result.fetchall())


def load_events_journal(
    file_path: str | Path,
) -> dict[str, int]:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {path}"
        )

    processed_rows = 0
    inserted_rows = 0
    repeated_headers = 0
    skipped_duplicates = 0

    batch: list[dict] = []

    with SessionLocal() as session:
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as file:
                reader = csv.DictReader(file)

                if reader.fieldnames is None:
                    raise ValueError(
                        "CSV file does not contain a header"
                    )

                validate_required_columns(
                    reader.fieldnames,
                    EVENT_REQUIRED_COLUMNS,
                )

                for row_number, row in enumerate(
                    reader,
                    start=2,
                ):
                    processed_rows += 1

                    if is_repeated_event_header(row):
                        repeated_headers += 1
                        continue

                    batch.append(
                        parse_event_row(
                            row,
                            row_number=row_number,
                        )
                    )

                    if len(batch) >= EVENT_BATCH_SIZE:
                        inserted = _insert_event_batch(
                            session,
                            batch,
                        )

                        session.commit()

                        inserted_rows += inserted
                        skipped_duplicates += (
                            len(batch) - inserted
                        )

                        batch.clear()

                if batch:
                    inserted = _insert_event_batch(
                        session,
                        batch,
                    )

                    session.commit()

                    inserted_rows += inserted
                    skipped_duplicates += (
                        len(batch) - inserted
                    )

        except Exception:
            session.rollback()
            raise

    return {
        "processed_rows": processed_rows,
        "inserted_rows": inserted_rows,
        "repeated_headers": repeated_headers,
        "skipped_duplicates": skipped_duplicates,
    }


def compute_row_hash(
    *,
    event_id: int,
    channel_id: int,
    event_date: str,
    event_time: str,
    alarm: str,
    sensor_value: str | None,
) -> str:
    normalized_sensor_value = None

    if sensor_value is not None:
        stripped_value = sensor_value.strip()

        if stripped_value:
            normalized_sensor_value = stripped_value

    values = [
        str(event_id),
        str(channel_id),
        event_date.strip(),
        event_time.strip(),
        alarm.strip(),
        normalized_sensor_value,
    ]

    payload = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()