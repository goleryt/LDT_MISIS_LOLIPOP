import csv
import re
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import ChannelCatalogue
from app.db.session import SessionLocal
from app.ingestion.validators import validate_required_columns


CHANNEL_REQUIRED_COLUMNS = {
    "ид_канала_данных",
    "тип_инж_системы",
    "тип_датчика",
    "тег_инженерной_системы",
    "название_датчика",
}

CHANNEL_BATCH_SIZE = 1000


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    return value if value else None


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