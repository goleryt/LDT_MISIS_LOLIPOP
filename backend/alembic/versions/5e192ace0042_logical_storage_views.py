"""Logical operational, archive and analytical read models; no source rows are deleted."""
from alembic import op
revision = "5e192ace0042"
down_revision = "28199ee15ad1"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE SCHEMA operational")
    op.execute("CREATE SCHEMA archive")
    op.execute("CREATE SCHEMA analytics")
    op.execute("""CREATE VIEW operational.events AS SELECT * FROM public.events_journal
                  WHERE d_event_time >= CURRENT_TIMESTAMP - INTERVAL '90 days' OR d_event_time IS NULL""")
    op.execute("""CREATE VIEW archive.events AS SELECT * FROM public.events_journal
                  WHERE d_event_time < CURRENT_TIMESTAMP - INTERVAL '90 days'""")
    op.execute("""CREATE VIEW analytics.daily_observations AS
                  SELECT date_trunc('day', d_event_time) AS day, count(*) AS observations,
                         count(*) FILTER (WHERE d_alarm IS TRUE) AS alarm_observations
                  FROM public.events_journal GROUP BY 1""")
    op.execute("""CREATE VIEW analytics.repair_history AS
                  SELECT object_id, status, count(*) AS requests, max(completed_at) AS last_completed_at
                  FROM public.preventive_requests GROUP BY object_id, status""")

def downgrade():
    op.execute("DROP VIEW analytics.repair_history")
    op.execute("DROP VIEW analytics.daily_observations")
    op.execute("DROP VIEW archive.events")
    op.execute("DROP VIEW operational.events")
    op.execute("DROP SCHEMA analytics")
    op.execute("DROP SCHEMA archive")
    op.execute("DROP SCHEMA operational")
