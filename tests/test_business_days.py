"""REP-02: primer dia habil del mes con feriados de Chile (tabla 2026-2027)."""

import logging
from datetime import date

from app.core import business_days as bd


def test_month_starting_on_saturday_first_business_day_is_monday() -> None:
    # 1-ago-2026 es sabado
    assert date(2026, 8, 1).weekday() == 5
    assert bd.first_business_day(2026, 8) == date(2026, 8, 3)


def test_month_starting_on_sunday_first_business_day_is_monday() -> None:
    # 1-nov-2026 es domingo (y feriado)
    assert date(2026, 11, 1).weekday() == 6
    assert bd.first_business_day(2026, 11) == date(2026, 11, 2)


def test_month_starting_on_monday_is_its_own_first_business_day() -> None:
    assert date(2026, 6, 1).weekday() == 0
    assert bd.first_business_day(2026, 6) == date(2026, 6, 1)
    assert bd.is_first_business_day(date(2026, 6, 1))
    assert not bd.is_first_business_day(date(2026, 6, 2))


def test_holiday_on_the_first_pushes_the_day() -> None:
    # 1-ene-2026 jueves feriado -> viernes 2
    assert bd.first_business_day(2026, 1) == date(2026, 1, 2)
    # 1-may-2026 viernes feriado -> lunes 4
    assert bd.first_business_day(2026, 5) == date(2026, 5, 4)
    # 1-ene-2027 viernes feriado -> lunes 4
    assert bd.first_business_day(2027, 1) == date(2027, 1, 4)
    # 1-nov-2027 lunes feriado -> martes 2
    assert bd.first_business_day(2027, 11) == date(2027, 11, 2)


def test_holiday_table_covers_2026_and_2027() -> None:
    assert bd.has_holiday_table(2026) and bd.has_holiday_table(2027)
    assert bd.is_holiday(date(2026, 12, 25)) and bd.is_holiday(date(2027, 9, 17))
    assert not bd.is_business_day(date(2026, 4, 3))  # Viernes Santo
    assert bd.is_business_day(date(2026, 4, 6))


def test_year_without_table_uses_weekdays_and_warns_once(caplog) -> None:
    bd._warned_years.discard(2031)
    with caplog.at_level(logging.WARNING, logger="app.core.business_days"):
        assert bd.is_business_day(date(2031, 1, 1)) is True  # miercoles, sin tabla
        assert bd.is_business_day(date(2031, 1, 4)) is False  # sabado
        assert bd.is_business_day(date(2031, 1, 6)) is True
    assert sum("2031" in r.getMessage() for r in caplog.records) == 1
