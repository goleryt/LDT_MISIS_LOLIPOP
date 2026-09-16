"""baseline existing schema

Revision ID: b174b31449db
Revises: 28853386caaa
Create Date: 2026-09-16 20:56:07.815025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b174b31449db'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_catalogue",
        sa.Column(
            "ид_канала_данных",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "тип_инж_системы",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "тип_датчика",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "тег_инженерной_системы",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "название_датчика",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "d_site",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "d_pk",
            sa.Integer(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "ид_канала_данных",
        ),
    )

    op.create_table(
        "object_catalogue",
        sa.Column(
            "ид_объект",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "иерархия_уровень",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "родитель",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "вид_объекта",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "диспетчерское_название_объекта",
            sa.String(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "ид_объект",
        ),
    )

    op.create_table(
        "events_journal",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "ид_события",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "ид_канала_данных",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "дата",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "время",
            sa.Time(),
            nullable=False,
        ),
        sa.Column(
            "тревожное",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "значение_датчика",
            sa.String(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id",
        ),
    )

    op.create_index(
        "ix_events_journal_ид_события",
        "events_journal",
        ["ид_события"],
        unique=False,
    )

    op.create_index(
        "ix_events_journal_ид_канала_данных",
        "events_journal",
        ["ид_канала_данных"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_events_journal_ид_канала_данных",
        table_name="events_journal",
    )

    op.drop_index(
        "ix_events_journal_ид_события",
        table_name="events_journal",
    )

    op.drop_table("events_journal")
    op.drop_table("object_catalogue")
    op.drop_table("channel_catalogue")