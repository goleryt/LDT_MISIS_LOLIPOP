"""add event query indexes

Revision ID: 7bb10cf49ac2
Revises: 6f8d2ab42c31
Create Date: 2026-09-22 23:15:00

"""

from typing import Sequence, Union

from alembic import op


revision: str = "7bb10cf49ac2"
down_revision: Union[
    str,
    Sequence[str],
    None,
] = "6f8d2ab42c31"
branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None
depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.create_index(
        op.f(
            "ix_events_journal_d_event_time"
        ),
        "events_journal",
        ["d_event_time"],
        unique=False,
    )

    op.create_index(
        "ix_events_journal_channel_time_id",
        "events_journal",
        [
            "ид_канала_данных",
            "d_event_time",
            "id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_events_journal_channel_time_id",
        table_name="events_journal",
    )

    op.drop_index(
        op.f(
            "ix_events_journal_d_event_time"
        ),
        table_name="events_journal",
    )
