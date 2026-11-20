"""Dias habiles de Chile (REP-02): para el reporte mensual, que sale el primer dia habil del mes.

Un dia habil es de lunes a viernes y no feriado. Los feriados legales son una tabla por anio, que hay que ACTUALIZAR cada
anio (diciembre, con el decreto del calendario). Si el anio no esta en la tabla, se usa solo lunes a viernes y se deja un
aviso en el log (una vez por anio), para que un feriado olvidado no pase en silencio.

Los feriados de 2027 salen de las reglas de traslado de las leyes 19.668, 20.215 y 20.299; el del 21 de junio (Dia de los
Pueblos Indigenas, solsticio) y el del 17 de septiembre conviene confirmarlos con el decreto oficial.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Solo feriados que caen de lunes a viernes importan para el calculo, pero se listan todos los legales (sabados y domingos
# incluidos) para que la tabla se pueda cotejar linea a linea con el calendario oficial.
CHILE_HOLIDAYS: dict[int, frozenset[date]] = {
    2026: frozenset({
        date(2026, 1, 1),    # Anio Nuevo
        date(2026, 4, 3),    # Viernes Santo
        date(2026, 4, 4),    # Sabado Santo
        date(2026, 5, 1),    # Dia del Trabajo
        date(2026, 5, 21),   # Glorias Navales
        date(2026, 6, 21),   # Dia de los Pueblos Indigenas (domingo)
        date(2026, 6, 29),   # San Pedro y San Pablo
        date(2026, 7, 16),   # Virgen del Carmen
        date(2026, 8, 15),   # Asuncion de la Virgen (sabado)
        date(2026, 9, 18),   # Independencia
        date(2026, 9, 19),   # Glorias del Ejercito (sabado)
        date(2026, 10, 12),  # Encuentro de Dos Mundos
        date(2026, 10, 31),  # Iglesias Evangelicas (sabado)
        date(2026, 11, 1),   # Todos los Santos (domingo)
        date(2026, 12, 8),   # Inmaculada Concepcion
        date(2026, 12, 25),  # Navidad
    }),
    2027: frozenset({
        date(2027, 1, 1),    # Anio Nuevo
        date(2027, 3, 26),   # Viernes Santo
        date(2027, 3, 27),   # Sabado Santo
        date(2027, 5, 1),    # Dia del Trabajo (sabado)
        date(2027, 5, 21),   # Glorias Navales
        date(2027, 6, 21),   # Dia de los Pueblos Indigenas (confirmar con el decreto)
        date(2027, 6, 28),   # San Pedro y San Pablo (trasladado del martes 29)
        date(2027, 7, 16),   # Virgen del Carmen
        date(2027, 8, 15),   # Asuncion de la Virgen (domingo)
        date(2027, 9, 17),   # Feriado puente de Fiestas Patrias (confirmar con el decreto)
        date(2027, 9, 18),   # Independencia (sabado)
        date(2027, 9, 19),   # Glorias del Ejercito (domingo)
        date(2027, 10, 11),  # Encuentro de Dos Mundos (trasladado del martes 12)
        date(2027, 10, 31),  # Iglesias Evangelicas (domingo)
        date(2027, 11, 1),   # Todos los Santos
        date(2027, 12, 8),   # Inmaculada Concepcion
        date(2027, 12, 25),  # Navidad (sabado)
    }),
}

_warned_years: set[int] = set()


def has_holiday_table(year: int) -> bool:
    return year in CHILE_HOLIDAYS


def is_holiday(day: date) -> bool:
    return day in CHILE_HOLIDAYS.get(day.year, frozenset())


def is_business_day(day: date) -> bool:
    """Lunes a viernes y no feriado. Sin tabla para el anio: solo lunes a viernes, con aviso en el log."""
    if day.weekday() >= 5:
        return False
    if day.year not in CHILE_HOLIDAYS:
        if day.year not in _warned_years:
            _warned_years.add(day.year)
            logger.warning(
                "Sin tabla de feriados para %d en app/core/business_days.py: se usa lunes a viernes. Actualizarla.", day.year
            )
        return True
    return day not in CHILE_HOLIDAYS[day.year]


def first_business_day(year: int, month: int) -> date:
    day = date(year, month, 1)
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def is_first_business_day(day: date) -> bool:
    return day == first_business_day(day.year, day.month)
