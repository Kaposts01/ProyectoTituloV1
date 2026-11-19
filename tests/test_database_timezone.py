from datetime import datetime, timezone

from sqlalchemy import text

from app.db.session import engine


def test_database_sessions_read_timestamp_dates_in_utc():
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW timezone")) == "UTC"
        value = connection.scalar(text("SELECT TIMESTAMPTZ '2026-01-15 00:00:00+00'"))
        assert value == datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert value.hour == 0
        assert value.date().isoformat() == "2026-01-15"
