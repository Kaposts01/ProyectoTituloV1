"""UX-09: Cobros unificados (GET /api/v1/general/charges, /payments, /summary, /statuses) con datos sinteticos."""

import random
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.tch import TchTransaction
from app.services.export_queries import (
    ExportFilters,
    fetch_page,
    iter_rows,
    select_specs,
)
from app.services.rbac import seed_permissions

_TAG = "zu[0-9a-f]{8}"


def _sfx() -> str:
    return "zu" + "".join(random.choice("0123456789abcdef") for _ in range(8))


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=f"gen-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"gen-{suffix}", password_hash=hash_password("Pw-gen-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": f"gen-{suffix}", "password": "Pw-gen-12345"}).status_code == 200
    return client


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM write_runs WHERE request_payload->>'username' ~ ('^gen-' || :tag)",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^gen-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^gen-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^gen-' || :tag)",
            "DELETE FROM charges WHERE external_id ~ :tag",
            "DELETE FROM payments WHERE external_id ~ :tag",
            "DELETE FROM subscriptions WHERE external_id ~ :tag",
            "DELETE FROM clients WHERE external_id ~ :tag",
            "DELETE FROM tch_transacciones WHERE dedupe_key ~ :tag",
        ):
            db.execute(text(stmt), params)
        db.commit()
    finally:
        db.close()


def _seed(sfx: str, file_number: int) -> None:
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{sfx}", first_name="Ana", last_name="Prueba", social_id="11111111-1"),
            Subscription(source="virtualpos1", external_id=f"sub-{sfx}", client_external_id=f"cl-{sfx}", status="activa"),
            Charge(source="virtualpos1", external_id=f"c1-{sfx}", subscription_external_id=f"sub-{sfx}", status="pagado",
                   charge_date="2011-07-02", amount="1000", currency="CLP"),
            Charge(source="virtualpos1", external_id=f"c2-{sfx}", subscription_external_id=f"sub-{sfx}", status=" Rechazado ",
                   charge_date="2011-07-03", amount="1000", currency="CLP"),
            Charge(source="virtualpos2", external_id=f"c3-{sfx}", subscription_external_id=f"sub-{sfx}", status="cancelado",
                   charge_date="2011-07-04", amount="1000", currency="CLP"),
            Charge(source="toku", external_id=f"c4-{sfx}", subscription_external_id=f"tsub-{sfx}", status="UNPAID",
                   charge_date="2011-07-05", amount="500", currency="CLP"),
            TchTransaction(file_number=file_number, period="2011-07", amount="5000", charge_date="2011-07-06",
                           status="RECHAZADA", rejection_reason="Sin fondos", dedupe_key=f"{sfx}-1"),
            Payment(source="toku", external_id=f"p1-{sfx}", charge_external_id=f"c4-{sfx}", status="failed",
                    payment_date="2011-07-07", amount="500", currency="CLP"),
            Payment(source="toku", external_id=f"p2-{sfx}", charge_external_id=f"c4-{sfx}", status="paid",
                    payment_date="2011-07-08", amount="500", currency="CLP"),
            Payment(source="payku", external_id=f"p3-{sfx}", status="success", payment_date="2011-07-09", amount="800"),
        ])
        db.commit()
    finally:
        db.close()


CHARGE_VIEW = ["virtualpos.charges.view", "toku.invoices.view", "tch.transacciones.view"]
DATES = {"date_from": "2011-07-01", "date_to": "2011-07-31"}


def test_unified_charges_lists_channels_paginates_and_filters(monkeypatch) -> None:
    sfx = _sfx()
    file_number = random.randint(90_000_000, 99_999_999)
    _seed(sfx, file_number)
    client = _login(monkeypatch, sfx, CHARGE_VIEW)
    resp = client.get("/api/v1/general/charges", params=DATES)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5 and body["by_channel"] == {"virtualpos": 3, "toku": 1, "tch": 1}
    assert [row["channel"] for row in body["items"]] == ["virtualpos1", "virtualpos1", "virtualpos2", "toku", "tch"]
    vp = body["items"][0]
    assert vp["charge_id"] == f"c1-{sfx}" and vp["rut"] == "11111111-1" and vp["name"] == "Ana Prueba"
    page = client.get("/api/v1/general/charges", params={**DATES, "offset": 2, "limit": 2}).json()
    assert [row["channel"] for row in page["items"]] == ["virtualpos2", "toku"] and page["total"] == 5
    only_tch = client.get("/api/v1/general/charges", params={**DATES, "canal": "tch"}).json()
    assert only_tch["total"] == 1 and only_tch["items"][0]["rejection_reason"] == "Sin fondos"
    # resultado normalizado con charge_stats: «Rechazado» con espacios y RECHAZADA (TCH) son rechazos
    rejected = client.get("/api/v1/general/charges", params={**DATES, "outcome": "rejected"}).json()
    assert {row["charge_id"] for row in rejected["items"]} == {f"c2-{sfx}", only_tch["items"][0]["charge_id"]}
    excluded = client.get("/api/v1/general/charges", params={**DATES, "outcome": "excluded"}).json()
    assert [row["charge_id"] for row in excluded["items"]] == [f"c3-{sfx}"]
    other = client.get("/api/v1/general/charges", params={**DATES, "outcome": "other"}).json()
    assert [row["charge_id"] for row in other["items"]] == [f"c4-{sfx}"]
    by_status = client.get("/api/v1/general/charges", params={**DATES, "status": "pagado"}).json()
    assert [row["charge_id"] for row in by_status["items"]] == [f"c1-{sfx}"]
    statuses = client.get("/api/v1/general/charges/statuses", params=DATES).json()
    assert {s["status"]: s["count"] for s in statuses["statuses"]} == {"pagado": 1, " Rechazado ": 1, "cancelado": 1, "UNPAID": 1, "RECHAZADA": 1}
    assert client.get("/api/v1/general/charges", params={"outcome": "nope"}).status_code == 422
    assert client.get("/api/v1/general/charges", params={"filter_field": "rut"}).status_code == 422


def test_unified_charges_permissions_filter_on_server(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    only_toku = _login(monkeypatch, sfx + "a", ["toku.invoices.view"])
    body = only_toku.get("/api/v1/general/charges", params=DATES).json()
    assert body["canales"] == ["toku"] and {row["channel"] for row in body["items"]} == {"toku"}
    assert only_toku.get("/api/v1/general/charges", params={"canal": "tch"}).status_code == 403
    assert only_toku.get("/api/v1/general/payments").status_code == 403
    nothing = _login(monkeypatch, sfx + "b", ["dashboard.view"])
    assert nothing.get("/api/v1/general/charges").status_code == 403
    assert nothing.get("/api/v1/general/charges/summary").status_code == 403
    assert nothing.get("/api/v1/general/charges/statuses").status_code == 403


def test_unified_payments_and_rejection_summary_use_single_definition(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    client = _login(monkeypatch, sfx, [*CHARGE_VIEW, "toku.transactions.view", "payku.transactions.view"])
    payments = client.get("/api/v1/general/payments", params={**DATES, "query": sfx, "filter_field": "id"}).json()
    assert [(row["channel"], row["payment_id"]) for row in payments["items"]] == [
        ("toku", f"p1-{sfx}"), ("toku", f"p2-{sfx}"), ("payku", f"p3-{sfx}")]
    summary = client.get("/api/v1/general/charges/summary", params=DATES).json()
    by_channel = {item["channel"]: item for item in summary["channels"]}
    # VirtualPOS (cargos): 1 pagado, 1 rechazado; el cancelado queda fuera del universo
    assert (by_channel["virtualpos"]["paid"], by_channel["virtualpos"]["rejected"], by_channel["virtualpos"]["rate"]) == (1, 1, 50.0)
    assert by_channel["virtualpos"]["basis"] == "cargos"
    # Toku (transacciones): 1 fallida y 1 pagada; la deuda UNPAID no cuenta como rechazo
    assert (by_channel["toku"]["paid"], by_channel["toku"]["rejected"], by_channel["toku"]["basis"]) == (1, 1, "transacciones")
    assert (by_channel["tch"]["paid"], by_channel["tch"]["rejected"]) == (0, 1)
    assert (by_channel["payku"]["paid"], by_channel["payku"]["rejected"], by_channel["payku"]["rate"]) == (1, 0, 0.0)
    assert summary["total"] == {"paid": 3, "rejected": 3, "evaluable": 6, "rate": 50.0}
    only_vp1 = client.get("/api/v1/general/charges/summary", params={**DATES, "canal": "virtualpos1"}).json()
    assert [item["channel"] for item in only_vp1["channels"]] == ["virtualpos"]


def test_page_matches_export_view_window() -> None:
    """«Exportar esta vista» (iter_rows con paged) entrega las mismas filas que la pagina mostrada (fetch_page)."""
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    items, _ = select_specs("cobros", None, set(CHARGE_VIEW))
    filters = ExportFilters(date_from=date(2011, 7, 1), date_to=date(2011, 7, 31))
    db = SessionLocal()
    try:
        rows, _totals = fetch_page(db, items, filters, False, 1, 3)
    finally:
        db.close()
    exported = list(iter_rows(SessionLocal, items, filters, False, paged=(1, 3)))
    assert [r["charge_id"] for r in rows] == [r["charge_id"] for r in exported]


def test_export_accepts_outcome_filter(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    client = _login(monkeypatch, sfx, CHARGE_VIEW)
    count = client.get("/api/v1/export/cobros/count", params={**DATES, "outcome": "rejected"})
    assert count.status_code == 200 and count.json()["rows"] == 2
    assert client.get("/api/v1/export/suscripciones/count", params={"outcome": "rejected"}).status_code in (403, 422)
