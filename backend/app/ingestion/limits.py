"""Database-wide, non-queued import admission and per-import processing budget."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
from sqlalchemy import text
from app.core.config import get_settings
from app.db.session import engine

IMPORT_NAMESPACE = 1279546441
DEADLINE = ContextVar('import_processing_deadline',default=None)


class ImportBusy(ValueError):
    def __init__(self, *, same_file=False):
        self.status = 409 if same_file else 429
        self.code = 'IMPORT_ALREADY_PROCESSING' if same_file else 'IMPORT_CAPACITY_BUSY'
        super().__init__('Этот файл уже обрабатывается. Повторите загрузку позже.' if same_file
            else 'Сервис импорта занят. Файл не принят в обработку; повторите загрузку позже.')


class ImportDeadlineExceeded(ValueError):
    pass


def check_import_budget():
    deadline=DEADLINE.get()
    if deadline is not None and time.monotonic()>=deadline:
        raise ImportDeadlineExceeded('Превышено время обработки. Данные файла не сохранены; разделите файл и повторите загрузку.')


def apply_import_budget(session):
    check_import_budget()
    deadline=DEADLINE.get()
    if deadline is not None:
        remaining=max(1,min(60000,int((deadline-time.monotonic())*1000)))
        session.execute(text("SELECT set_config('statement_timeout',:value,true)"),{'value':str(remaining)})


@contextmanager
def processing_budget():
    token=DEADLINE.set(time.monotonic()+get_settings().import_timeout_seconds)
    try:yield
    finally:DEADLINE.reset(token)


@contextmanager
def import_admission(file_key):
    """One pooled connection owns both locks. Never wait while retaining a slot.

    Two-integer advisory keys are separate from existing bigint file locks.
    Session locks release automatically on process/connection loss. All workers
    sharing this DB must use the same configured slot count.
    """
    with engine.connect() as lock:
        file_locked=False;slot=None
        try:
            file_locked=lock.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':file_key})
            if not file_locked:raise ImportBusy(same_file=True)
            for candidate in range(get_settings().import_max_concurrent):
                if lock.scalar(text('SELECT pg_try_advisory_lock(:namespace,:slot)'),
                    {'namespace':IMPORT_NAMESPACE,'slot':candidate}):
                    slot=candidate;break
            # End the SELECT transaction; lock ownership stays session-scoped.
            lock.commit()
            if slot is None:raise ImportBusy()
            yield
        finally:
            if slot is not None:
                lock.execute(text('SELECT pg_advisory_unlock(:namespace,:slot)'),
                    {'namespace':IMPORT_NAMESPACE,'slot':slot})
            if file_locked:lock.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':file_key})
            lock.commit()
