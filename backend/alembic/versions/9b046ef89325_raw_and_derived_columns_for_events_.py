"""raw and derived columns for events journal

Revision ID: 9b046ef89325
Revises: b174b31449db
Create Date: 2026-09-17 20:40:43.102976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b046ef89325'
down_revision: Union[str, Sequence[str], None] = 'b174b31449db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # convert typed source columns back to raw text so the exact source
    # values are preserved (see CLAUDE.md: never overwrite source columns)
    op.alter_column(
        "events_journal",
        "дата",
        type_=sa.String(),
        postgresql_using='"дата"::text',
    )
    op.alter_column(
        "events_journal",
        "время",
        type_=sa.String(),
        postgresql_using='"время"::text',
    )
    op.alter_column(
        "events_journal",
        "тревожное",
        type_=sa.String(),
        postgresql_using="""CASE WHEN "тревожное" THEN 'true' ELSE 'false' END""",
    )

    op.add_column(
        "events_journal",
        sa.Column("d_event_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events_journal",
        sa.Column("d_alarm", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "events_journal",
        sa.Column("d_value_numeric", sa.Float(), nullable=True),
    )
    op.add_column(
        "events_journal",
        sa.Column("d_value_state", sa.String(), nullable=True),
    )
    op.add_column(
        "events_journal",
        sa.Column("d_row_hash", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_events_journal_d_row_hash",
        "events_journal",
        ["d_row_hash"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_events_journal_d_row_hash",
        "events_journal",
        type_="unique",
    )
    op.drop_column("events_journal", "d_row_hash")
    op.drop_column("events_journal", "d_value_state")
    op.drop_column("events_journal", "d_value_numeric")
    op.drop_column("events_journal", "d_alarm")
    op.drop_column("events_journal", "d_event_time")

    op.alter_column(
        "events_journal",
        "тревожное",
        type_=sa.Boolean(),
        postgresql_using='"тревожное"::boolean',
    )
    op.alter_column(
        "events_journal",
        "время",
        type_=sa.Time(),
        postgresql_using='"время"::time',
    )
    op.alter_column(
        "events_journal",
        "дата",
        type_=sa.Date(),
        postgresql_using='"дата"::date',
    )
