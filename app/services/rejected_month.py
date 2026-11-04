"""Calculo compartido de 'cobros rechazados del mes actual' (mes calendario en hora Chile)."""
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

CHILE_TZ = ZoneInfo("America/Santiago")

REJECTED_TX_STATUSES = {
    "rechazado", "rechazada", "rejected", "failed", "failure", "declined", "error",
}


def now_chile() -> datetime:
    """Ahora en America/Santiago (punto unico para monkeypatch en tests)."""
    return datetime.now(tz=CHILE_TZ)


def rejected_current_month(
    rows: Iterable[dict[str, Any]], statuses: set[str] | None = None
) -> dict[str, Any]:
    """Suma cobros rechazados del mes actual (Chile) desde filas {year, month, status, count, amount}."""
    today = now_chile().date()
    count = 0
    amount = 0.0
    for row in rows:
        if (row.get("year"), row.get("month")) != (today.year, today.month):
            continue
        if statuses is not None and str(row.get("status", "")).lower() not in statuses:
            continue
        count += int(row.get("count") or 0)
        amount += float(row.get("amount") or 0)
    return {"count": count, "amount": round(amount, 2)}
