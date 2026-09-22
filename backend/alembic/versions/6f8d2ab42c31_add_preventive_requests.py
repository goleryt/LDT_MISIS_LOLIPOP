"""add preventive requests

Revision ID: 6f8d2ab42c31
Revises: 393827181fa5
Create Date: 2026-09-22 22:55:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f8d2ab42c31"
down_revision: Union[
    str,
    Sequence[str],
    None,
] = "393827181fa5"
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
    op.create_table(
        "preventive_requests",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "object_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "title",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "priority",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_preventive_requests_object_id"),
        "preventive_requests",
        ["object_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_preventive_requests_channel_id"),
        "preventive_requests",
        ["channel_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_preventive_requests_channel_id"),
        table_name="preventive_requests",
    )

    op.drop_index(
        op.f("ix_preventive_requests_object_id"),
        table_name="preventive_requests",
    )

    op.drop_table(
        "preventive_requests"
    )
