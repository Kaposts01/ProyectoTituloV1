"""UX-08: Suscripciones unificadas (GET /api/v1/general/subscriptions y /statuses) con datos sinteticos."""

import random

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.crm import Charge, Client, Subscription
from app.models.tch import TchClient, TchSubscription
from tests.test_general_charges import (  # noqa: F401  (fixture autouse de limpieza)
    _cleanup,
    _login,
    _sfx,
)


def _seed(sfx: str, file_number: int, rut: str) -> None:
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{sfx}", first_name="Eva", last_name="Prueba", social_id="77777777-7"),
            Subscription(source="virtualpos1", external_id=f"s1-{sfx}", client_external_id=f"cl-{sfx}", status="activa",
                         suscription_date="2026-01-05", amount="3000", currency="CLP"),
            Subscription(source="virtualpos1", external_id=f"s2-{sfx}", status="cancelada", suscription_date="2025-01-05"),
            Subscription(source="virtualpos1", external_id=f"s3-{sfx}", status="SUSCRIPCION_FALLIDA"),
            Subscription(source="toku", external_id=f"s4-{sfx}", status="active", suscription_date="2026-02-01"),
            Subscription(source="payku", external_id=f"s5-{sfx}", status="REGISTER"),
            Charge(source="virtualpos1", external_id=f"ch-{sfx}", subscription_external_id=f"s1-{sfx}", status="pagado",
                   charge_date="2026-03-03"),
            TchClient(rut=rut, name=f"Fer{sfx}", last_name="Prueba"),
            TchSubscription(file_number=file_number, client_rut=rut, status="VIGENTE", activation_date="2026-01-01",
                            amount="5000", peso_equivalent="5000"),
        ])
        db.commit()
    finally:
        db.close()


def _cleanup_tch(rut: str) -> None:
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM tch_suscripciones WHERE cliente_rut = :rut"), {"rut": rut})
        db.execute(text("DELETE FROM tch_clientes WHERE rut = :rut"), {"rut": rut})
        db.commit()
    finally:
        db.close()


ALL_SUBS = ["virtualpos.subscriptions.view", "toku.subscriptions.view", "payku.subscriptions.view", "tch.suscripciones.view"]


def test_unified_subscriptions_four_channels_filters_and_pii(monkeypatch) -> None:
    sfx = _sfx()
    file_number = random.randint(60_000_000, 69_999_999)
    rut = f"55{random.randint(100000, 999999)}-5"
    _seed(sfx, file_number, rut)
    try:
        client = _login(monkeypatch, sfx, ALL_SUBS)
        body = client.get("/api/v1/general/subscriptions", params={"query": sfx, "filter_field": "id"}).json()
        ids = [row["subscription_id"] for row in body["items"]]
        assert ids == [f"s1-{sfx}", f"s2-{sfx}", f"s4-{sfx}"]  # fallida (VP) y REGISTER (Payku) excluidas
        s1 = body["items"][0]
        assert s1["rut"] == "77777777-7" and s1["name"] == "Eva Prueba" and s1["last_charge"] == "2026-03-03"
        assert s1["secondary_status"] in {"cobrable", "incobrable"}
        assert body["by_channel"] == {"virtualpos": 2, "toku": 1, "payku": 0, "tch": 0}
        tch_params = {"canal": "tch", "query": str(file_number), "filter_field": "id"}
        tch = client.get("/api/v1/general/subscriptions", params=tch_params).json()
        assert tch["total"] == 1 and tch["items"][0]["rut"] == rut and tch["items"][0]["status"] == "VIGENTE"
        cancelled_params = {"query": sfx, "filter_field": "id", "status": "cancelada"}
        cancelled = client.get("/api/v1/general/subscriptions", params=cancelled_params).json()
        assert [row["subscription_id"] for row in cancelled["items"]] == [f"s2-{sfx}"]
        page_params = {"query": sfx, "filter_field": "id", "offset": 1, "limit": 1}
        page = client.get("/api/v1/general/subscriptions", params=page_params).json()
        assert [row["subscription_id"] for row in page["items"]] == [f"s2-{sfx}"] and page["total"] == 3
        statuses = client.get("/api/v1/general/subscriptions/statuses", params={"canal": "toku"}).json()
        assert "active" in {s["status"] for s in statuses["statuses"]}
    finally:
        _cleanup_tch(rut)


def test_unified_subscriptions_permission_per_channel(monkeypatch) -> None:
    sfx = _sfx()
    file_number = random.randint(60_000_000, 69_999_999)
    rut = f"55{random.randint(100000, 999999)}-5"
    _seed(sfx, file_number, rut)
    try:
        only_toku = _login(monkeypatch, sfx + "a", ["toku.subscriptions.view"])
        body = only_toku.get("/api/v1/general/subscriptions", params={"query": sfx, "filter_field": "id"}).json()
        assert body["canales"] == ["toku"] and [row["subscription_id"] for row in body["items"]] == [f"s4-{sfx}"]
        assert only_toku.get("/api/v1/general/subscriptions", params={"canal": "virtualpos"}).status_code == 403
        dashboard_only = _login(monkeypatch, sfx + "b", ["dashboard.view"])
        assert dashboard_only.get("/api/v1/general/subscriptions").status_code == 403
        assert dashboard_only.get("/api/v1/general/subscriptions/statuses").status_code == 403
    finally:
        _cleanup_tch(rut)
