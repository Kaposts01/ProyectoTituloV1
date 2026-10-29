"""UX-07: `GET /api/v1/dashboard/general` con datos sinteticos de los 4 canales (sin datos personales).

Ahora fijo = 2026-10-15 (Chile). Las cifras esperadas se derivan a mano en los comentarios de cada bloque.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from billing_requests_support import client_for, make_role, make_user
from sqlalchemy.orm import Session

from app.db.session import engine
from app.main import app
from app.models.crm import Charge, PaymentMethod, Subscription
from app.models.payku_channel import PaykuTransaction
from app.models.tch import TchMonthlyCollection, TchSubscription
from app.services import rejected_month

FAKE_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("America/Santiago"))
ALL_VIEW = {
    "dashboard.view", "virtualpos.dashboard.view", "toku.dashboard.view", "payku.dashboard.view", "tch.dashboard.view",
}


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(rejected_month, "now_chile", lambda: FAKE_NOW)


@pytest.fixture
def auth(monkeypatch, db_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    def make(codes=ALL_VIEW):
        user = make_user(db_session, make_role(db_session, f"dg-{len(codes)}", set(codes)))
        return client_for(db_session, user)

    return make


def sub(source, ext, status, signup, cancellation=None, amount="1000", client=None, social=None):
    return Subscription(
        source=source, external_id=ext, status=status, suscription_date=signup, canceled_at=cancellation,
        amount=amount, client_external_id=client, client_social_id=social, raw_payload={},
    )


def charge(source, ext, status, day, amount):
    return Charge(source=source, external_id=ext, status=status, charge_date=day, amount=amount, raw_payload={})


def tch_sub(file_number, status, act, elim=None, eq="1000", rut=None):
    return TchSubscription(
        file_number=file_number, status=status, activation_date=act, deletion_date=elim,
        peso_equivalent=eq, client_rut=rut,
    )


@pytest.fixture
def data(db_session):
    db_session.add_all([
        # VirtualPOS (cuentas 1 y 2): altas/bajas
        sub("virtualpos1", "v1", "ACTIVA", "2026-01-10", amount="10000", social="S1"),
        sub("virtualpos1", "v2", "ACTIVA", "2026-09-05", amount="5000", social="S2"),
        sub("virtualpos1", "v3", "ACTIVA", "2026-10-03", amount="6000", social="S3"),
        sub("virtualpos1", "v4", "CANCELADA", "2026-02-01", "2026-10-07"),
        sub("virtualpos1", "v5", "CANCELADA", "2026-03-01", "2026-09-20"),
        sub("virtualpos1", "v6", "SUSCRIPCION_FALLIDA", "2026-10-04"),  # nunca fue alta
        sub("virtualpos2", "w1", "ACTIVA", "2026-10-09", amount="4000", social="S1"),
        # Toku
        sub("toku", "t1", "ACTIVE", "2026-06-01", amount="8000", client="c1"),
        sub("toku", "t2", "CANCELLED", "2026-05-01", "2026-10-12"),
        # Payku
        sub("payku", "p1", "active", "2026-08-15", amount="9999", social="S9"),
        sub("payku", "p2", "cancel", "2026-07-01", "2026-10-02"),
        # Cobros VirtualPOS
        charge("virtualpos1", "c0", "pagado", "2026-01-15", "1000"),
        charge("virtualpos1", "c1", "pagado", "2026-10-02", "10000"),
        charge("virtualpos1", "c2", "pagado", "2026-10-10", "5000"),
        charge("virtualpos2", "c3", "rechazado", "2026-10-05", "3000"),
        charge("virtualpos1", "c4", "pendiente", "2026-10-12", "4000"),   # pendiente vencido
        charge("virtualpos1", "c5", "pendiente", "2026-10-25", "6000"),   # programado dentro del mes
        charge("virtualpos1", "c6", "rechazado", "2026-10-28", "7000"),   # FUTURO: fuera de rechazo
        charge("virtualpos1", "c7", "cancelado", "2026-10-03", "8888"),   # excluido
        charge("virtualpos1", "c8", "pagado", "2026-09-10", "12000"),
        charge("virtualpos1", "c9", "pagado", "2026-09-15", "8000"),
        charge("virtualpos1", "c10", "rechazado", "2026-09-20", "1000"),
        charge("virtualpos1", "c11", "pendiente", "2026-12-01", "9000"),  # fuera de ventana
        # Toku / Payku
        charge("toku", "k1", "PAID", "2026-10-08", "20000"),
        charge("toku", "k2", "rejected", "2026-10-09", "2000"),
        charge("toku", "k3", "PAID", "2026-09-03", "15000"),
        charge("payku", "y1", "success", "2026-10-11", "7000"),
        PaymentMethod(source="toku", external_id="pm1", status="chargeable", raw_payload={"subscription_ids": ["t1"]}),
        PaykuTransaction(external_id="tx1", subscription_id="p1", amount="7000", status="success",
                         created_at_api="2026-10-11T10:00:00"),
        # TCH
        tch_sub(1, "VIGENTE", "2026-04-01", eq="30000", rut="T1"),
        tch_sub(2, "ELIMINADA", "2026-04-02", "2026-10-05"),
        tch_sub(3, "VIGENTE", "2026-10-10", eq="20000", rut="T2"),
        TchMonthlyCollection(period="2026-10", accepted_count=10, accepted_amount="50000",
                              rejected_count=5, rejected_amount="25000", source_file="x"),
        TchMonthlyCollection(period="2026-09", accepted_count=8, accepted_amount="40000",
                              rejected_count=2, rejected_amount="10000", source_file="x"),
    ])
    db_session.flush()


def get(client, **params):
    r = client.get("/api/v1/dashboard/general", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_month_with_signups_cancellations_all_channels(auth, data) -> None:
    client, _ = auth()
    body = get(client, month="2026-10")
    k = body["kpis"]
    assert body["month"] == "2026-10" and body["channels"] == ["virtualpos", "toku", "payku", "tch"]
    # Socios al cierre: Oct VP 4 + Toku 1 + Payku 1 + TCH 2 = 8; Sep VP 3 + 2 + 2 + 2 = 9
    assert (k["socios_totales"]["valor"], k["socios_totales"]["valor_mes_anterior"]) == (8, 9)
    assert k["socios_totales"]["delta_vs_mes_anterior"] == -1
    assert k["socios_totales"]["socios_totales_nota"] == "suma por canal, no deduplicada"
    # Altas Oct: v3, w1, TCH #3 = 3. Bajas Oct: v4, t2, p2, TCH #2 = 4 (v6 fallida no cuenta)
    assert (k["activaciones"]["valor"], k["bajas"]["valor"], k["crecimiento_neto"]["valor"]) == (3, 4, -1)
    assert (k["activaciones"]["valor_mes_anterior"], k["bajas"]["valor_mes_anterior"]) == (1, 1)
    # Churn unificado: 4 bajas / 9 socios al inicio = 44,4 %; Sep: 1 / 9 = 11,1 %
    assert (k["churn"]["valor"], k["churn"]["valor_mes_anterior"]) == (44.4, 11.1)
    assert k["churn"]["delta_vs_mes_anterior"] == 33.3
    assert "bajas del mes" in k["churn"]["churn_definicion"] and k["churn"]["churn_window_label"]
    for name in ("socios_totales", "activaciones", "bajas", "churn", "ingreso_total", "mrr", "arpu"):
        assert k[name]["meta"] is None and k[name]["estado_meta"] == "sin_meta"


def test_revenue_collectability_and_future_charges_excluded(auth, data) -> None:
    client, _ = auth()
    k = get(client, month="2026-10")["kpis"]
    # Ingreso Oct: VP 15000 + Toku 20000 + Payku 7000 + TCH 50000 = 92000; Sep: 20000 + 15000 + 40000 = 75000
    assert (k["ingreso_total"]["valor"], k["ingreso_total"]["valor_mes_anterior"]) == (92000, 75000)
    assert {c: v["valor"] for c, v in k["ingreso_por_canal"].items()} == {
        "virtualpos": 15000, "toku": 20000, "payku": 7000, "tch": 50000,
    }
    assert k["ingreso_por_canal"]["payku"]["valor_mes_anterior"] is None  # Payku sin cobros en septiembre
    # Acumulado del año: 1000 (ene) + 75000 + 92000
    assert (k["acumulado_anio"]["valor"], k["acumulado_anio"]["valor_mes_anterior"]) == (168000, 76000)
    # Cobrabilidad Oct: 14 pagados / (14 + 7 rechazados); el rechazado futuro c6 y el cancelado c7 no cuentan
    assert k["cobrabilidad"]["valor"] == 66.7 and k["cobrabilidad"]["valor_mes_anterior"] == 78.6
    # No cobrado Oct: 3000 + 2000 + 25000 (sin los 7000 futuros); por cobrar: 4000 vencido + 6000 programado
    assert k["no_cobrado"]["valor"] == 30000 and k["no_cobrado"]["valor_mes_anterior"] == 11000
    assert k["por_cobrar"]["valor"] == 10000 and k["por_cobrar"]["valor_mes_anterior"] == 0


def test_mrr_and_arpu_use_current_definitions_only_for_current_month(auth, data) -> None:
    client, _ = auth()
    k = get(client, month="2026-10")["kpis"]
    # VP activas 10000+5000+6000+4000 = 25000 (clientes S1,S2,S3 = 3); Toku t1 8000 (1); Payku ultima
    # transaccion exitosa 7000 (1); TCH VIGENTE 30000+20000 (2). Total 90000 / 7 clientes = 12857
    assert k["mrr"]["valor"] == 90000
    assert k["mrr"]["por_canal"] == {"virtualpos": 25000, "toku": 8000, "payku": 7000, "tch": 50000}
    assert k["arpu"]["valor"] == 12857
    past = get(client, month="2026-09")["kpis"]
    assert past["mrr"]["valor"] is None and past["arpu"]["valor"] is None  # foto actual: sin historia


def test_channel_without_permission_does_not_appear(auth, data) -> None:
    client, _ = auth({"dashboard.view", "virtualpos.dashboard.view", "toku.dashboard.view"})
    body = get(client, month="2026-10", channels="virtualpos,toku,payku,tch")
    assert body["channels"] == ["virtualpos", "toku"]
    k = body["kpis"]
    assert set(k["ingreso_por_canal"]) == {"virtualpos", "toku"}
    assert k["socios_totales"]["valor"] == 5  # VP 4 + Toku 1
    assert k["ingreso_total"]["valor"] == 35000
    assert set(body["series"]["ingreso_por_canal"][-1]["canales"]) == {"virtualpos", "toku"}
    assert set(k["mrr"]["por_canal"]) == {"virtualpos", "toku"}
    # Sin ningun permiso de canal: nada que mostrar, todo null
    client2, _ = auth({"dashboard.view"})
    empty = get(client2, month="2026-10")
    assert empty["channels"] == [] and empty["kpis"]["socios_totales"]["valor"] is None


def test_requires_dashboard_view_and_validates_params(auth, data) -> None:
    client, _ = auth({"virtualpos.dashboard.view"})
    assert client.get("/api/v1/dashboard/general").status_code == 403
    client, _ = auth()
    r = client.get("/api/v1/dashboard/general", params={"month": "2026-13"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_month"
    r = client.get("/api/v1/dashboard/general", params={"channels": "virtualpos,nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_channel"
    only = get(client, month="2026-10", channels="tch")
    assert only["channels"] == ["tch"] and only["kpis"]["socios_totales"]["valor"] == 2
    assert only["kpis"]["por_cobrar"]["valor"] is None  # TCH no tiene cobros programados


def test_month_without_data_is_all_null(auth, data) -> None:
    client, _ = auth()
    for month in ("2020-03", "2026-12"):  # antes de toda la historia / mes futuro
        body = get(client, month=month)
        flat = [v for key, v in body["kpis"].items() if key != "ingreso_por_canal"]
        flat += list(body["kpis"]["ingreso_por_canal"].values())
        assert all(item["valor"] is None for item in flat), month
        assert all(item["delta_vs_mes_anterior"] is None for item in flat)
        # La serie de 12 meses solo es toda null si ninguno de sus meses tiene datos (2020); en 2026-12 solo los
        # meses futuros (nov. y dic. de 2026 > hoy) son null.
        tail = body["series"]["ingreso_por_canal"][-2:] if month == "2026-12" else body["series"]["ingreso_por_canal"]
        assert all(p["total"] is None for p in tail)
        for name in ("activaciones", "bajas", "socios_totales"):
            points = body["series"][name][-2:] if month == "2026-12" else body["series"][name]
            assert all(p["valor"] is None for p in points)


def test_empty_database_returns_nulls_not_zeros(auth, db_session) -> None:
    client, _ = auth()
    k = get(client)["kpis"]  # mes actual, sin ningun dato
    assert all(v["valor"] is None for key, v in k.items() if key != "ingreso_por_canal")


def test_twelve_month_series(auth, data) -> None:
    client, _ = auth()
    s = get(client, month="2026-10")["series"]
    assert s["months"][0] == "2025-11" and s["months"][-1] == "2026-10" and len(s["months"]) == 12
    socios = {p["month"]: p["valor"] for p in s["socios_totales"]}
    assert socios["2025-12"] is None            # antes de la primera alta
    assert socios["2026-01"] == 1               # v1
    assert socios["2026-08"] == 9 and socios["2026-09"] == 9 and socios["2026-10"] == 8
    acts = {p["month"]: p["valor"] for p in s["activaciones"]}
    cancellations = {p["month"]: p["valor"] for p in s["bajas"]}
    assert acts["2025-12"] is None and acts["2026-01"] == 1 and acts["2026-10"] == 3
    assert cancellations["2026-01"] == 0 and cancellations["2026-09"] == 1 and cancellations["2026-10"] == 4
    ing = {p["month"]: p for p in s["ingreso_por_canal"]}
    assert ing["2026-10"]["total"] == 92000 and ing["2026-10"]["canales"]["tch"] == 50000
    assert ing["2026-01"]["total"] == 1000 and ing["2026-01"]["canales"] == {
        "virtualpos": 1000, "toku": None, "payku": None, "tch": None}
    assert ing["2026-02"]["total"] is None


def test_quality_data_counts_undated_records(auth, data, db_session) -> None:
    db_session.add_all([
        sub("toku", "t9", "ACTIVE", None),           # alta sin fecha
        sub("payku", "p9", "cancel", "2026-01-01"),  # baja sin fecha de baja
    ])
    db_session.flush()
    client, _ = auth()
    q = get(client, month="2026-10")["calidad_datos"]
    assert q == {"altas_sin_fecha": 1, "bajas_sin_fecha": 1}
