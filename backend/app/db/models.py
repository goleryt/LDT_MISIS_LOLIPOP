from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
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
