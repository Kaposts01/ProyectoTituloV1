"""TCH-PAR-17: altas del dashboard TCH con respaldo cuando falta "Fecha Activacion" (corte de la fuente jul-2025).

Datos sinteticos, sin datos personales.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import tch
from app.db.session import engine
from app.models.tch import TchSubscription


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class _NoClose:  # la ruta cierra su sesion al terminar: aqui se comparte la de la prueba
        def __getattr__(self, name):
            return getattr(session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(tch, "_get_db", lambda: _NoClose())
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


def _sub(file_number: int, **dates) -> TchSubscription:
    return TchSubscription(file_number=file_number, status="VIGENTE", peso_equivalent="10000", **dates)


def _activations(summary: dict) -> dict[tuple[int, int], int]:
    return {(e["year"], e["month"]): e["count"] for e in summary["activaciones_mensuales"]}


def test_activations_fall_back_to_first_charge_then_bank_delivery(db_session) -> None:
    db_session.add_all([
        _sub(954001, activation_date="2025-03-10", first_charge_date="2025-04-05"),  # manda la activacion
        _sub(954002, first_charge_date="2025-09-05", bank_delivery_date="2025-08-20"),  # sin activacion: primer cobro
        _sub(954003, bank_delivery_date="2025-10-01"),  # solo entrega al banco
        _sub(954004, activation_date="", first_charge_date="no-es-fecha"),  # sin fecha valida: no es alta
    ])
    db_session.flush()

    summary = tch.tch_summary()

    altas = _activations(summary)
    assert altas[(2025, 3)] == 1 and (2025, 4) not in altas
    assert altas[(2025, 9)] == 1 and (2025, 8) not in altas
    assert altas[(2025, 10)] == 1
    assert sum(altas.values()) == 3

    fuente = summary["activaciones_fuente"]
    assert (fuente["fecha_activacion"], fuente["fecha_primer_cobro"], fuente["fecha_entrega_banco"], fuente["sin_fecha"]) == (1, 1, 1, 1)
    assert "julio de 2025" in fuente["nota"]


def test_active_subscriptions_series_includes_the_fallback_activations(db_session) -> None:
    db_session.add_all([_sub(954011, first_charge_date="2025-11-02"), _sub(954012, first_charge_date="2025-11-15")])
    db_session.flush()
    summary = tch.tch_summary()
    serie = {(e["year"], e["month"]): e["count"] for e in summary["active_subs_monthly"]}
    assert serie[(2025, 11)] == 2
