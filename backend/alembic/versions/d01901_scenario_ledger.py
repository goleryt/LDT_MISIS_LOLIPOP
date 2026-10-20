"""Isolated scenario ledger; existing gas tables and data are unchanged."""
from alembic import op
import sqlalchemy as sa
revision = 'd01901'
down_revision = 'd01602'
branch_labels = depends_on = None


def upgrade():
    op.create_table('scenario_runs',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('as_of_date',sa.Date(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('snapshot_version',sa.String(120),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('versions',sa.JSON(),nullable=False),
        sa.Column('state',sa.String(30),nullable=False),
        sa.Column('error_code',sa.String(100)),sa.Column('output',sa.JSON()),
        sa.Column('started_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('finished_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('fingerprint'),sa.UniqueConstraint('as_of_date','revision'))
    op.create_index('ix_scenario_runs_as_of_date','scenario_runs',['as_of_date'])
    op.create_table('scenario_forecasts',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('run_id',sa.BigInteger(),sa.ForeignKey('scenario_runs.id'),nullable=False),
        sa.Column('forecast_ref',sa.String(300),nullable=False),
        sa.Column('worker',sa.String(30),nullable=False),
        sa.Column('object_id',sa.BigInteger(),sa.ForeignKey('object_catalogue.ид_объект')),
        sa.Column('channel_id',sa.BigInteger(),sa.ForeignKey('channel_catalogue.ид_канала_данных')),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('attention',sa.Boolean(),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('decisions',sa.JSON(),nullable=False),
        sa.Column('request_id',sa.BigInteger(),sa.ForeignKey('preventive_requests.id')),
        sa.UniqueConstraint('run_id','forecast_ref'))
    op.create_index('ix_scenario_forecasts_run_id','scenario_forecasts',['run_id'])
    op.create_index('ix_scenario_forecasts_worker','scenario_forecasts',['worker'])


def downgrade():
    # Only exercise rollback in disposable QA. Never downgrade the demo database.
    op.drop_table('scenario_forecasts')
    op.drop_table('scenario_runs')
