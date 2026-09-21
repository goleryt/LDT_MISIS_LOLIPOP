"""canonicalize events journal

Revision ID: b8f3e33c10fb
Revises: b174b31449db
Create Date: 2026-09-17 22:51:50.281127

"""

import hashlib
import json
from datetime import date, datetime, time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f3e33c10fb"
down_revision: Union[str, Sequence[str], None] = "b174b31449db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKFILL_BATCH_SIZE = 2000


def _parse_alarm(value: str) -> bool:
    normalized = value.strip().lower()

    if normalized in {"true", "t"}:
        return True

    if normalized in {"false", "f"}:
        return False

    raise ValueError(
        f"Unsupported alarm value during migration: {value!r}"
    )


def _parse_sensor_value(
    value: str | None,
) -> tuple[float | None, str | None]:
    if value is None:
        return None, None

    normalized = value.strip()

    if not normalized:
        return None, None

    try:
        return (
            float(normalized.replace(",", ".")),
            None,
        )
    except ValueError:
        return None, normalized


def _compute_row_hash(
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


def upgrade() -> None:
    """Convert source fields to raw text and backfill derived fields."""

    # 1. Исходные дата / время / тревожное переводим в text.
    op.alter_column(
        "events_journal",
        "дата",
        existing_type=sa.Date(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using='"дата"::text',
    )

    op.alter_column(
        "events_journal",
        "время",
        existing_type=sa.Time(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using='"время"::text',
    )

    op.alter_column(
        "events_journal",
        "тревожное",
        existing_type=sa.Boolean(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using=(
            """CASE """
            """WHEN "тревожное" THEN 'true' """
            """ELSE 'false' END"""
        ),
    )

    # 2. Новые поля сначала nullable.
    op.add_column(
        "events_journal",
        sa.Column(
            "d_event_time",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )

    op.add_column(
        "events_journal",
        sa.Column(
            "d_alarm",
            sa.Boolean(),
            nullable=True,
        ),
    )

    op.add_column(
        "events_journal",
        sa.Column(
            "d_value_numeric",
            sa.Float(),
            nullable=True,
        ),
    )

    op.add_column(
        "events_journal",
        sa.Column(
            "d_value_state",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "events_journal",
        sa.Column(
            "d_row_hash",
            sa.String(length=64),
            nullable=True,
        ),
    )

    # 3. Backfill уже существующих событий.
    bind = op.get_bind()

    bulk_update_statement = sa.text(
        """
        WITH batch_data AS (
            SELECT *
            FROM jsonb_to_recordset(
                CAST(:payload AS jsonb)
            ) AS x(
                id bigint,
                d_event_time timestamp,
                d_alarm boolean,
                d_value_numeric double precision,
                d_value_state text,
                d_row_hash varchar(64)
            )
        )
        UPDATE events_journal AS event
        SET
            d_event_time = batch.d_event_time,
            d_alarm = batch.d_alarm,
            d_value_numeric = batch.d_value_numeric,
            d_value_state = batch.d_value_state,
            d_row_hash = batch.d_row_hash
        FROM batch_data AS batch
        WHERE event.id = batch.id
        """
    )

    last_id = 0

    while True:
        rows = bind.execute(
            sa.text(
                """
                SELECT
                    id,
                    "ид_события",
                    "ид_канала_данных",
                    "дата",
                    "время",
                    "тревожное",
                    "значение_датчика"
                FROM events_journal
                WHERE id > :last_id
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            {
                "last_id": last_id,
                "batch_size": BACKFILL_BATCH_SIZE,
            },
        ).fetchall()

        if not rows:
            break

        updates: list[dict] = []

        for row in rows:
            data = row._mapping

            event_date_raw = data["дата"]
            event_time_raw = data["время"]
            alarm_raw = data["тревожное"]
            sensor_value = data["значение_датчика"]

            event_date = date.fromisoformat(
                event_date_raw.strip()
            )

            event_time = time.fromisoformat(
                event_time_raw.strip()
            )

            alarm = _parse_alarm(
                alarm_raw
            )

            value_numeric, value_state = (
                _parse_sensor_value(
                    sensor_value
                )
            )

            row_hash = _compute_row_hash(
                event_id=data["ид_события"],
                channel_id=data["ид_канала_данных"],
                event_date=event_date_raw,
                event_time=event_time_raw,
                alarm=alarm_raw,
                sensor_value=sensor_value,
            )

            updates.append(
                {
                    "id": data["id"],
                    "d_event_time":
                        datetime.combine(
                            event_date,
                            event_time,
                        ).isoformat(),
                    "d_alarm": alarm,
                    "d_value_numeric":
                        value_numeric,
                    "d_value_state":
                        value_state,
                    "d_row_hash":
                        row_hash,
                }
            )

        payload = json.dumps(
            updates,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        bind.execute(
            bulk_update_statement,
            {
                "payload": payload,
            },
        )

        last_id = rows[-1]._mapping["id"]

    # 4. Перед ограничениями убеждаемся,
    # что backfill действительно завершился.
    missing_hashes = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM events_journal
            WHERE d_row_hash IS NULL
            """
        )
    ).scalar_one()

    if missing_hashes != 0:
        raise RuntimeError(
            "Events journal backfill failed: "
            f"{missing_hashes} rows have no d_row_hash"
        )

    duplicate_hash = bind.execute(
        sa.text(
            """
            SELECT d_row_hash
            FROM events_journal
            GROUP BY d_row_hash
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).scalar_one_or_none()

    if duplicate_hash is not None:
        raise RuntimeError(
            "Events journal backfill produced "
            f"duplicate hash: {duplicate_hash}"
        )

    # 5. после успешного backfill включаем финальные ограничения.
    op.alter_column(
        "events_journal",
        "d_row_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_events_journal_d_row_hash",
        "events_journal",
        ["d_row_hash"],
    )


def downgrade() -> None:
    """Restore the schema used before canonical event storage."""

    op.drop_constraint(
        "uq_events_journal_d_row_hash",
        "events_journal",
        type_="unique",
    )

    op.drop_column(
        "events_journal",
        "d_row_hash",
    )
    op.drop_column(
        "events_journal",
        "d_value_state",
    )
    op.drop_column(
        "events_journal",
        "d_value_numeric",
    )
    op.drop_column(
        "events_journal",
        "d_alarm",
    )
    op.drop_column(
        "events_journal",
        "d_event_time",
    )

    op.alter_column(
        "events_journal",
        "тревожное",
        existing_type=sa.String(),
        type_=sa.Boolean(),
        existing_nullable=False,
        postgresql_using='"тревожное"::boolean',
    )

    op.alter_column(
        "events_journal",
        "время",
        existing_type=sa.String(),
        type_=sa.Time(),
        existing_nullable=False,
        postgresql_using='"время"::time',
    )

    op.alter_column(
        "events_journal",
        "дата",
        existing_type=sa.String(),
        type_=sa.Date(),
        existing_nullable=False,
        postgresql_using='"дата"::date',
    )