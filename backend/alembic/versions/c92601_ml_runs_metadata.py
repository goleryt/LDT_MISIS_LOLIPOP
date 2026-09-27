"""Immutable ML run revisions and prediction provenance."""
from alembic import op
import sqlalchemy as sa
revision = "c92601"
down_revision = "a7c41d09e3b2"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("predictions", sa.Column("ml_metadata", sa.JSON(), nullable=True))
    op.create_table("ml_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("fingerprint", sa.String(64)), sa.Column("output_hash", sa.String(64)),
        sa.Column("summary", sa.JSON()), sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("as_of_date", "revision"))
    op.create_index("ix_ml_runs_as_of_date", "ml_runs", ["as_of_date"])
    op.execute("INSERT INTO ml_runs (as_of_date, revision, state) SELECT DISTINCT as_of_date, 1, 'completed' FROM ml_scores")
def downgrade():
    op.drop_table("ml_runs")
    op.drop_column("predictions", "ml_metadata")
