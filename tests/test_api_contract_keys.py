"""Contrato de claves JSON (D33): las respuestas de la API conservan EXACTAMENTE sus claves (en español) tras
renombrar identificadores internos. Datos sinteticos; sin datos personales. Referencia en `tests/golden/`."""

from datetime import date

import pytest
from contract_keys import assert_keys
from sqlalchemy import delete

from app.api.v1.routes import recovery, reports, staging, tch
from app.models.crm import Charge, Client, Subscription
from app.models.tch import TchCliente, TchRecaudacionMensual, TchTransaccion
from tests.test_dashboard_general import (  # noqa: F401  (fixtures)
    _now,
    auth,
    data,
    db_session,
)

pytestmark = pytest.mark.usefixtures("_now")


@pytest.fixture
def seeded(db_session, data, monkeypatch):  # noqa: F811
    """Datos de `data` + clientes/transacciones TCH + un cliente y una suscripcion VirtualPOS cancelada."""

    class _NoClose:  # las rutas TCH cierran su sesion al terminar: aqui se comparte la de la prueba
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(tch, "_get_db", lambda: _NoClose())
    db_session.execute(delete(TchRecaudacionMensual).where(TchRecaudacionMensual.periodo.notin_(["2026-10", "2026-09"])))
    db_session.add_all([
        TchCliente(rut="T1", nombre="Ana", apellido="Prueba", email="a@example.org", telefono="1", comuna="X", ciudad="Y"),
        TchCliente(rut="T2", nombre="Beto", apellido="Prueba"),
        TchTransaccion(numero_ficha=1, estado="ACEPTADA", periodo="2026-10", monto="30000", fecha_cargo="2026-10-05",
                       numero_cuota="1", total_cuotas="12", entidad_recaudadora="B", tipo_transaccion="cargo", origen="cargo",
                       dedupe_key="k-1"),
        TchTransaccion(numero_ficha=3, estado="RECHAZADA", periodo="2026-10", monto="20000", fecha_cargo="2026-10-06",
                       razon_rechazo="Fondos insuficientes", codigo_respuesta="51", origen="cargo", dedupe_key="k-2"),
        TchTransaccion(numero_ficha=3, estado="ACEPTADA", periodo="2026-09", monto="20000", fecha_cargo="2026-09-06",
                       origen="cargo", dedupe_key="k-3"),
        Client(source="virtualpos1", external_id="cl1", social_id="S1", first_name="Ana", last_name="Prueba",
               email="x@example.org", raw_payload={}),
        Subscription(source="virtualpos1", external_id="v10", status="CANCELADA", suscription_date="2026-01-01",
                     canceled_at="2026-10-10", amount="9000", client_external_id="cl1", client_social_id="S1", raw_payload={}),
    ])
    db_session.flush()
    return db_session


def test_dashboard_general_keys(auth, data) -> None:  # noqa: F811
    client, _ = auth()
    resp = client.get("/api/v1/dashboard/general", params={"month": "2026-10"})
    assert resp.status_code == 200, resp.text
    assert_keys("dashboard_general", resp.json())


def test_tch_routes_keys(seeded) -> None:
    assert_keys("tch_summary", tch.tch_summary())
    assert_keys("tch_clientes", tch.list_clientes(page=1, limit=50))
    assert_keys("tch_cliente_detalle", tch.get_cliente("T1"))
    assert_keys("tch_suscripciones", tch.list_suscripciones(page=1, limit=50))
    assert_keys("tch_suscripcion_detalle", tch.get_suscripcion(1))
    assert_keys("tch_transacciones", tch.list_transacciones(page=1, limit=50))
    first = seeded.query(TchTransaccion).filter(TchTransaccion.dedupe_key == "k-2").one()
    assert_keys("tch_transaccion_detalle", tch.get_transaccion(first.id))


def test_staging_dashboard_keys(seeded) -> None:
    assert_keys("staging_general_dashboard", staging.general_dashboard(db=seeded))
    assert_keys("staging_channel_tch", staging.centralized_channel_dashboard("tch", db=seeded))
    assert_keys("staging_channel_virtualpos", staging.centralized_channel_dashboard("virtualpos", db=seeded))
    assert_keys("staging_general_clients",
                staging.general_clients(db=seeded, query=None, filter_field="all", offset=0, limit=50))
    assert_keys("staging_general_subscriptions",
                staging.general_subscriptions(db=seeded, query=None, filter_field="all", offset=0, limit=50))
    assert_keys("staging_general_client_detail", staging.general_client_detail("T1", db=seeded))


def test_recovery_json_keys(seeded) -> None:
    seeded.add(Charge(source="virtualpos1", external_id="rj1", status="rechazado", charge_date="2026-10-05", amount="5000",
                      subscription_external_id="v10", raw_payload={"rejected_object": {"code": "-8", "message": "x"}}))
    seeded.flush()
    no_filters = recovery.RecoveryFilters()
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    assert_keys("recovery_rejected", recovery._page(recovery._rejected_rows(seeded, start, end, "retry", no_filters), 0, 50))
    assert_keys("recovery_cancelled", recovery._page(recovery._cancelled_rows(seeded, start, end, no_filters), 0, 50))
    assert_keys("recovery_group", recovery._page(recovery._group_rows(seeded, "inactiva", start, end, no_filters), 0, 50))


def test_reports_json_keys(seeded) -> None:
    start, end = date(2026, 10, 1), date(2026, 10, 15)
    assert_keys("reports_auto_period", reports._auto_period_data(seeded, start, end))
    assert_keys("reports_virtualpos_data", reports._virtualpos_report_data(seeded, start, end))
    for scope in ("general", "toku", "payku", "tch"):
        assert_keys(f"reports_snapshot_{scope}", reports._snapshot(seeded, scope))
        assert_keys(f"reports_series_{scope}", reports._series(seeded, scope, start, end))
