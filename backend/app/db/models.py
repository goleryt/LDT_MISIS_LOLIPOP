from __future__ import annotations

from datetime import date, time

from sqlalchemy import BigInteger, Boolean, Date, Integer, String, Time
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
    """журнал_событий / ext-journal-*.csv — оперативные (не исторические) события"""

    __tablename__ = "events_journal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ид_события: Mapped[int] = mapped_column(BigInteger, index=True)
    ид_канала_данных: Mapped[int] = mapped_column(BigInteger, index=True)
    дата: Mapped[date] = mapped_column(Date)
    время: Mapped[time] = mapped_column(Time)
    тревожное: Mapped[bool] = mapped_column(Boolean)
    значение_датчика: Mapped[str | None] = mapped_column(String, nullable=True)
