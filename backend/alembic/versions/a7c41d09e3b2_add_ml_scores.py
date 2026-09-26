"""Store the daily ML batch output (ml_scores)."""
import sqlalchemy as sa
from alembic import op

revision = "a7c41d09e3b2"
down_revision = "5e192ace0042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ml_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("bundle", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(200)),
        sa.Column("target_code", sa.String(100)),
        sa.Column("object_id", sa.BigInteger()),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("incident_type", sa.String(50)),
        sa.Column("score", sa.Float()),
        sa.Column("score_kind", sa.String(50)),
        sa.Column("evidence_level", sa.String(10)),
        sa.Column("decision_status", sa.String(40)),
        sa.Column("reason_codes", sa.JSON()),
        sa.Column("window_start", sa.Date()),
        sa.Column("window_end_exclusive", sa.Date()),
        sa.Column("maintenance_context", sa.String(40)),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rank", sa.Integer()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ml_scores_as_of_date", "ml_scores", ["as_of_date"])
    op.create_index("ix_ml_scores_object_id", "ml_scores", ["object_id"])
    op.create_index("ix_ml_scores_channel_id", "ml_scores", ["channel_id"])


def downgrade():
    op.drop_table("ml_scores")
