import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.ingestion.import_registry import import_events_file


from sqlalchemy import select

from app.db.models import DataImport
from app.db.session import SessionLocal

router = APIRouter(
    prefix="/imports",
    tags=["imports"],
)



def serialize_import(
    data_import: DataImport,
) -> dict[str, object]:
    return {
        "id": data_import.id,
        "file_name": data_import.file_name,
        "file_sha256": data_import.file_sha256,
        "import_type": data_import.import_type,
        "status": data_import.status,
        "processed_rows": data_import.processed_rows,
        "inserted_rows": data_import.inserted_rows,
        "skipped_rows": data_import.skipped_rows,
        "file_size_bytes": data_import.file_size_bytes,
        "error_message": data_import.error_message,
        "started_at": data_import.started_at,
        "completed_at": data_import.completed_at,
    }


@router.post("/events")
def upload_events_file(
    file: UploadFile = File(...),
) -> dict[str, object]:
    file_name = file.filename

    if not file_name:
        raise HTTPException(
            status_code=400,
            detail="File name is required",
        )

    suffix = Path(file_name).suffix.lower()

    if suffix != ".csv":
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are supported",
        )

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".csv",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

            shutil.copyfileobj(
                file.file,
                temp_file,
                length=1024 * 1024,
            )

        result = import_events_file(
            temp_path,
            original_file_name=file_name,
        )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    finally:
        file.file.close()

        if (
            temp_path is not None
            and temp_path.exists()
        ):
            temp_path.unlink()



@router.get("")
def get_imports() -> list[dict[str, object]]:
    with SessionLocal() as session:
        imports = session.scalars(
            select(DataImport)
            .order_by(DataImport.id.desc())
            .limit(100)
        ).all()

        return [
            serialize_import(data_import)
            for data_import in imports
        ]


@router.get("/{import_id}")
def get_import(
    import_id: int,
) -> dict[str, object]:
    with SessionLocal() as session:
        data_import = session.get(
            DataImport,
            import_id,
        )

        if data_import is None:
            raise HTTPException(
                status_code=404,
                detail="Import not found",
            )

        return serialize_import(data_import)