from sqlalchemy import func, select

from app.db.models import EventsJournal
from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal() as session:
        statement = (
            select(
                EventsJournal.ид_канала_данных,
                func.count(
                    EventsJournal.id
                ).label("event_count"),
            )
            .where(
                EventsJournal.d_value_numeric
                .is_not(None)
            )
            .group_by(
                EventsJournal.ид_канала_данных
            )
            .order_by(
                func.count(
                    EventsJournal.id
                ).desc()
            )
            .limit(20)
        )

        rows = session.execute(
            statement
        ).all()

        if not rows:
            print(
                "Числовые значения "
                "в текущем журнале не найдены."
            )
            return

        print(
            "Каналы с числовыми "
            "значениями:"
        )

        for channel_id, event_count in rows:
            print(
                f"{channel_id}: "
                f"{event_count} событий"
            )


if __name__ == "__main__":
    main()