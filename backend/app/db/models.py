from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class ChannelDailyFeatures(Base):
    """Причинная дневная панель признаков по каналам.

    Строится батчем из events_journal и channel_catalogue; служит входом для
    failure_state_presence proxy-модели (BACKEND_API_INTERFACE_RU.md, раздел 6).
    (ид_канала_данных, as_of_date) уникальны.
    """

    __tablename__ = "channel_daily_features"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    ид_канала_данных: Mapped[int] = mapped_column(BigInteger, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)

    d_observed_days_so_far: Mapped[int] = mapped_column(Integer)
    d_current_failure_state: Mapped[bool] = mapped_column(Boolean)

    d_event_count_24h: Mapped[int] = mapped_column(Integer)
    d_alarm_count_24h: Mapped[int] = mapped_column(Integer)
    d_alarm_share_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_failure_state_event_count_24h: Mapped[int] = mapped_column(Integer)
    d_value_numeric_mean_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value_numeric_min_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value_numeric_max_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value_numeric_std_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value_numeric_last: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_state_n_unique_24h: Mapped[int] = mapped_column(Integer)

    d_gap_days_since_previous: Mapped[int | None] = mapped_column(Integer, nullable=True)
    d_event_count_previous_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    d_alarm_count_previous_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    d_alarm_share_previous_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_value_numeric_previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    d_days_since_failure_state_event: Mapped[int | None] = mapped_column(Integer, nullable=True)

    d_weekday: Mapped[int] = mapped_column(Integer)
    d_month: Mapped[int] = mapped_column(Integer)
    d_catalogue_match: Mapped[bool] = mapped_column(Boolean)
    тип_инж_системы: Mapped[str | None] = mapped_column(String, nullable=True)
    тип_датчика: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "ид_канала_данных",
            "as_of_date",
            name="uq_channel_daily_features_channel_date",
        ),
    )
