from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChannelCatalogue(Base):
    """справочник_каналов_датчиков.csv"""

    __tablename__ = "channel_catalogue"

    ид_канала_данных: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    тип_инж_системы: Mapped[str | None] = mapped_column(String, nullable=True)
    тип_датчика: Mapped[str | None] = mapped_column(String, nullable=True)
    тег_инженерной_системы: Mapped[str | None] = mapped_column(String, nullable=True)
    название_датчика: Mapped[str | None] = mapped_column(String, nullable=True)
    ид_объект: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    d_site: Mapped[str | None] = mapped_column(String, nullable=True)
    d_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ObjectCatalogue(Base):
    """справочник_объектов_диспетчер.csv"""

    __tablename__ = "object_catalogue"

    ид_объект: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    иерархия_уровень: Mapped[int | None] = mapped_column(Integer, nullable=True)
    родитель: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    вид_объекта: Mapped[str | None] = mapped_column(String, nullable=True)
    диспетчерское_название_объекта: Mapped[str | None] = mapped_column(String, nullable=True)


class EventsJournal(Base):
    """Журнал событий."""

    __tablename__ = "events_journal"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    # Исходные поля.
    ид_события: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )
    ид_канала_данных: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )
    дата: Mapped[str] = mapped_column(String)
    время: Mapped[str] = mapped_column(String)
    тревожное: Mapped[str] = mapped_column(String)
    значение_датчика: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    # Производные поля.
    d_event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    d_alarm: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    d_value_numeric: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    d_value_state: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    # Технический ключ идемпотентности.
    d_row_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )


class DataImport(Base):
    """Реестр загрузок исходных файлов."""

    __tablename__ = "data_imports"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    file_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    file_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    import_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    processed_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    inserted_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    skipped_rows: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )