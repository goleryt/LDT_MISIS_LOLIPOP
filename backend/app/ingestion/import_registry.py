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

    file_sha256 = calculate_file_sha256(path)
    file_size_bytes = path.stat().st_size
    file_name = original_file_name or file_name

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
            file_name=path.name,
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


def import_events_file(
    file_path: str | Path,
    *,
    original_file_name: str | None = None,
) -> dict[str, object]:
    registration = begin_file_import(
        file_path,
        import_type=IMPORT_TYPE_EVENTS_JOURNAL,
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
        stats = load_events_journal(
            file_path
        )

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
                f"{type(exc).__name__}: {exc}"
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