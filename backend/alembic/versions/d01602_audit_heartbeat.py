"""Audit attribution and worker heartbeat; historical records remain explicitly nullable."""
from alembic import op
import sqlalchemy as sa
revision = "d01602"
down_revision = "d01601"
branch_labels = depends_on = None
def upgrade():
    for name, length in (("role",30),("entity_type",50),("entity_id",120)):
        op.add_column("audit_entries", sa.Column(name, sa.String(length), nullable=True))
    op.create_table("worker_heartbeats",
        sa.Column("name",sa.String(50),primary_key=True),
        sa.Column("state",sa.String(30),nullable=False),
        sa.Column("last_seen",sa.DateTime(timezone=True),nullable=False),
        sa.Column("last_success",sa.DateTime(timezone=True)),
        sa.Column("error_code",sa.String(100)))
def downgrade():
    op.drop_table("worker_heartbeats")
    for name in ("entity_id","entity_type","role"):
        op.drop_column("audit_entries",name)
