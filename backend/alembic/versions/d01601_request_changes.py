"""Request history and explicit draft workflow; existing requests keep their status."""
from alembic import op
import sqlalchemy as sa

revision = "d01601"
down_revision = "c92601"
branch_labels = depends_on = None

def upgrade():
    op.create_table("request_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.BigInteger(), sa.ForeignKey("preventive_requests.id"), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_request_changes_request_id", "request_changes", ["request_id"])

def downgrade():
    # No lossy conversion of drafts to active work on downgrade.
    op.drop_table("request_changes")
