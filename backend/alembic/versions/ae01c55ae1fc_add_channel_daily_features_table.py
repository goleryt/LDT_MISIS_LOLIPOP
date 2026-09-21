"""add channel daily features table

Revision ID: ae01c55ae1fc
Revises: 393827181fa5
Create Date: 2026-09-21 21:11:44.050101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae01c55ae1fc'
down_revision: Union[str, Sequence[str], None] = '393827181fa5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "channel_daily_features",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ид_канала_данных", sa.BigInteger(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("d_observed_days_so_far", sa.Integer(), nullable=False),
        sa.Column("d_current_failure_state", sa.Boolean(), nullable=False),
        sa.Column("d_event_count_24h", sa.Integer(), nullable=False),
        sa.Column("d_alarm_count_24h", sa.Integer(), nullable=False),
        sa.Column("d_alarm_share_24h", sa.Float(), nullable=True),
        sa.Column("d_failure_state_event_count_24h", sa.Integer(), nullable=False),
        sa.Column("d_value_numeric_mean_24h", sa.Float(), nullable=True),
        sa.Column("d_value_numeric_min_24h", sa.Float(), nullable=True),
        sa.Column("d_value_numeric_max_24h", sa.Float(), nullable=True),
        sa.Column("d_value_numeric_std_24h", sa.Float(), nullable=True),
        sa.Column("d_value_numeric_last", sa.Float(), nullable=True),
        sa.Column("d_state_n_unique_24h", sa.Integer(), nullable=False),
        sa.Column("d_gap_days_since_previous", sa.Integer(), nullable=True),
        sa.Column("d_event_count_previous_24h", sa.Integer(), nullable=True),
        sa.Column("d_alarm_count_previous_24h", sa.Integer(), nullable=True),
        sa.Column("d_alarm_share_previous_24h", sa.Float(), nullable=True),
        sa.Column("d_value_numeric_previous", sa.Float(), nullable=True),
        sa.Column("d_days_since_failure_state_event", sa.Integer(), nullable=True),
        sa.Column("d_weekday", sa.Integer(), nullable=False),
        sa.Column("d_month", sa.Integer(), nullable=False),
        sa.Column("d_catalogue_match", sa.Boolean(), nullable=False),
        sa.Column("тип_инж_системы", sa.String(), nullable=True),
        sa.Column("тип_датчика", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ид_канала_данных",
            "as_of_date",
            name="uq_channel_daily_features_channel_date",
        ),
    )
    op.create_index(
        op.f("ix_channel_daily_features_ид_канала_данных"),
        "channel_daily_features",
        ["ид_канала_данных"],
        unique=False,
    )
    op.create_index(
        op.f("ix_channel_daily_features_as_of_date"),
        "channel_daily_features",
        ["as_of_date"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_channel_daily_features_as_of_date"),
        table_name="channel_daily_features",
    )
    op.drop_index(
        op.f("ix_channel_daily_features_ид_канала_данных"),
        table_name="channel_daily_features",
    )
    op.drop_table("channel_daily_features")
