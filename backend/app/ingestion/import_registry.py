import hashlib
from pathlib import Path

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.ingestion.csv_loader import load_events_journal
from app.db.models import DataImport
from app.db.session import SessionLocal


FILE_HASH_CHUNK_SIZE = 1024 * 1024

IMPORT_STATUS_PROCESSING = "processing"
IMPORT_STATUS_COMPLETED = "completed"
IMPORT_STATUS_FAILED = "failed"
IMPORT_TYPE_EVENTS_JOURNAL = "events_journal"


@dataclass(frozen=True)
class ImportRegistration:
    import_id: int
    file_sha256: str
    should_import: bool
    previous_status: str | None


def calculate_file_sha256(
    file_path: str | Path,
) -> str:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(
                FILE_HASH_CHUNK_SIZE
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def begin_file_import(
    file_path: str | Path,
    *,
    import_type: str,
    original_file_name: str | None = None,
) -> ImportRegistration:
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    file_sha256 = hashlib.sha256((import_type + ":" + calculate_file_sha256(path)).encode()).hexdigest()
    file_size_bytes = path.stat().st_size
    file_name = original_file_name or path.name

    with SessionLocal() as session:
        existing = session.scalar(
            select(DataImport).where(
                DataImport.file_sha256 == file_sha256
            )
        )

        if existing is not None:
            previous_status = existing.status

            if existing.status == IMPORT_STATUS_COMPLETED:
                return ImportRegistration(
                    import_id=existing.id,
                    file_sha256=file_sha256,
                    should_import=False,
                    previous_status=previous_status,
                )

            existing.file_name = file_name
            existing.import_type = import_type
            existing.status = IMPORT_STATUS_PROCESSING
            existing.processed_rows = 0
            existing.inserted_rows = 0
            existing.skipped_rows = 0
            existing.file_size_bytes = file_size_bytes
            existing.error_message = None
            existing.started_at = datetime.now(
                timezone.utc
            )
            existing.completed_at = None

            session.commit()

            return ImportRegistration(
                import_id=existing.id,
                file_sha256=file_sha256,
                should_import=True,
                previous_status=previous_status,
            )

        data_import = DataImport(
            file_name=file_name,
            file_sha256=file_sha256,
            import_type=import_type,
            status=IMPORT_STATUS_PROCESSING,
            processed_rows=0,
            inserted_rows=0,
            skipped_rows=0,
            file_size_bytes=file_size_bytes,
        )

        session.add(data_import)
        session.commit()
        session.refresh(data_import)

        return ImportRegistration(
            import_id=data_import.id,
            file_sha256=file_sha256,
            should_import=True,
            previous_status=None,
        )


def complete_file_import(
    import_id: int,
    *,
    processed_rows: int,
    inserted_rows: int,
    skipped_rows: int,
) -> None:
    with SessionLocal() as session:
        data_import = session.get(
            DataImport,
            import_id,
        )

        if data_import is None:
            raise ValueError(
                f"Import not found: {import_id}"
            )

        data_import.status = IMPORT_STATUS_COMPLETED
        data_import.processed_rows = processed_rows
        data_import.inserted_rows = inserted_rows
        data_import.skipped_rows = skipped_rows
        data_import.error_message = None
        data_import.completed_at = datetime.now(
            timezone.utc
        )

        session.commit()


def fail_file_import(
    import_id: int,
    *,
    error_message: str,
) -> None:
    with SessionLocal() as session:
        data_import = session.get(
            DataImport,
            import_id,
        )

        if data_import is None:
            raise ValueError(
                f"Import not found: {import_id}"
            )

        data_import.status = IMPORT_STATUS_FAILED
        data_import.error_message = error_message
        data_import.completed_at = datetime.now(
            timezone.utc
        )

        session.commit()


def _import_file(
    file_path: str | Path,
    *,
    original_file_name: str | None = None,
    import_type: str = "events_journal",
) -> dict[str, object]:
    registration = begin_file_import(
        file_path,
        import_type=import_type,
        original_file_name=original_file_name,
    )

    if not registration.should_import:
        return {
            "import_id": registration.import_id,
            "file_sha256": registration.file_sha256,
            "status": IMPORT_STATUS_COMPLETED,
            "already_imported": True,
        }

    try:
        import tempfile
        from app.ingestion.csv_loader import (CHANNEL_REQUIRED_COLUMNS, OBJECT_REQUIRED_COLUMNS,
                                             EVENT_REQUIRED_COLUMNS, load_channel_catalogue, load_object_catalogue)
        from app.ingestion.formats import normalize_to_csv
        columns = {"events_journal": EVENT_REQUIRED_COLUMNS, "channels": CHANNEL_REQUIRED_COLUMNS,
                   "objects": OBJECT_REQUIRED_COLUMNS}[import_type]
        with tempfile.TemporaryDirectory() as directory:
            normalized = Path(directory) / "normalized.csv"
            normalize_to_csv(Path(file_path), normalized, columns)
            if import_type == "events_journal":
                stats = load_events_journal(normalized)
            else:
                count = (load_channel_catalogue if import_type == "channels" else load_object_catalogue)(normalized)
                stats = {"processed_rows": count, "inserted_rows": count, "repeated_headers": 0, "skipped_duplicates": 0}

        skipped_rows = (
            stats["repeated_headers"]
            + stats["skipped_duplicates"]
        )

        complete_file_import(
            registration.import_id,
            processed_rows=stats["processed_rows"],
            inserted_rows=stats["inserted_rows"],
            skipped_rows=skipped_rows,
        )

    except Exception as exc:
        fail_file_import(
            registration.import_id,
            error_message=(
                "Invalid input file" if isinstance(exc, ValueError) else "Import failed; inspect server logs"
            ),
        )
        raise

    return {
        "import_id": registration.import_id,
        "file_sha256": registration.file_sha256,
        "status": IMPORT_STATUS_COMPLETED,
        "already_imported": False,
        **stats,
    }
def import_events_file(file_path, *, original_file_name=None, import_type="events_journal"):
    from sqlalchemy import text
    from app.db.session import engine
    # Session-scoped advisory lock covers registration and all separately committed registry operations.
    key = int.from_bytes(hashlib.sha256((import_type + calculate_file_sha256(file_path)).encode()).digest()[:8], "big", signed=True)
    with engine.connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        if not acquired:
            raise ValueError("This file is already being imported; retry later")
        try:
            return _import_file(file_path, original_file_name=original_file_name, import_type=import_type)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
