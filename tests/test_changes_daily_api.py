"""SYNC-D-04: GET /api/v1/changes/daily (hora de Chile, sin baseline, RBAC)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.security import ACCESS_COOKIE, create_access_token
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent
from app.services.rbac import PERMISSIONS, executive_permission_codes, seed_permissions
from app.services.status_history import chile_day_bounds

DAY = "2026-10-28"
IN_DAY = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)  # 12:00 en Chile (UTC-3, horario de verano)
NEXT_DAY_CHILE = datetime(2026, 10, 29, 4, 0, tzinfo=UTC)  # 01:00 del 29 en Chile


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


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


def _client(db: Session, codes: set[str]) -> TestClient:
    seed_permissions(db)
    perms = {p.code: p for p in db.query(Permission)}
    role = Role(name=f"r-{uuid.uuid4().hex[:8]}")
    role.permissions = [perms[c] for c in sorted(codes)]
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=True, roles=[role])
    db.add_all([role, user])
    db.flush()
    token, _csrf = create_access_token(user)
    app.dependency_overrides[crm_get_db] = lambda: db
    app.dependency_overrides[security_get_db] = lambda: db
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(ACCESS_COOKIE, token)
    return client


def _ev(db: Session, kind: str, *, entity="charge", source="toku", ext="x1", frm=None, to=None, at=IN_DAY,
        baseline=False, field="status", amount=None, sub=None) -> None:
    db.add(StatusChangeEvent(
        entity_type=entity, source=source, external_id=ext, subscription_external_id=sub, event_kind=kind, field=field,
        from_value=frm, to_value=to, amount=amount, detected_at=at, is_baseline=baseline,
        dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex,
    ))


def _seed(db: Session) -> None:
    for i in range(3):
        _ev(db, "status_changed", ext=f"c{i}", frm="UNPAID", to="PAID")
    _ev(db, "status_changed", ext="c9", frm="UNPAID", to="FAILED")
    _ev(db, "status_changed", source="tch", ext="t1", frm="RECHAZADA", to="ACEPTADA")
    _ev(db, "created", entity="subscription", source="virtualpos1", ext="s1", to="ACTIVA")
    _ev(db, "created", entity="subscription", source="virtualpos1", ext="s2", to="ACTIVA")
    _ev(db, "created", entity="charge", source="payku", ext="p1", to="pending")
    _ev(db, "status_changed", entity="subscription", source="virtualpos1", ext="s3", frm="ACTIVA", to="CANCELADA")
    _ev(db, "status_changed", entity="subscription", source="virtualpos1", ext="s4", frm="CANCELADA", to="ACTIVA")  # reactivacion
    _ev(db, "status_changed", entity="subscription", source="payku", ext="s5", frm="active", to="cancel")
    _ev(db, "removed", entity="subscription", source="toku", ext="s6", field="record", frm="ACTIVE")
    _ev(db, "amount_changed", ext="a1", frm="5000", to="7000", field="amount", amount=Decimal("7000"))
    _ev(db, "amount_changed", ext="a2", frm="5000", to="4000", field="amount", amount=Decimal("4000"))
    _ev(db, "amount_changed", ext="a3", frm="no-num", to="100", field="amount")
    _ev(db, "reason_changed", source="tch", ext="r1", to="Fondos insuficientes", field="rejection_reason")
    db.add(RejectionReasonCatalog(source="tch", code="51", reason="Fondos insuficientes", occurrences=4))
    # Ruido que no debe contarse: baseline, otro dia, dia siguiente en Chile aunque sea el mismo dia UTC.
    _ev(db, "created", entity="subscription", source="virtualpos1", ext="b1", to="ACTIVA", baseline=True)
    _ev(db, "status_changed", ext="old", frm="A", to="B", at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC))
    _ev(db, "status_changed", ext="late", frm="A", to="B", at=NEXT_DAY_CHILE)
    db.flush()


def test_limits_of_the_day_in_chile_time() -> None:
    from datetime import date

    start, end = chile_day_bounds(date(2026, 10, 28))
    assert start == datetime(2026, 10, 28, 3, 0, tzinfo=UTC) and end == datetime(2026, 10, 29, 3, 0, tzinfo=UTC)
    start, end = chile_day_bounds(date(2026, 4, 5))  # cambio de horario: el dia dura 25 h... o 24 h segun el ano
    assert (end - start).total_seconds() in (23 * 3600, 24 * 3600, 25 * 3600)


def test_summary_daily_complete(db_session: Session) -> None:
    _seed(db_session)
    body = _client(db_session, {"dashboard.view"}).get(f"/api/v1/changes/daily?date={DAY}").json()

    assert body["date"] == DAY and body["timezone"] == "America/Santiago"
    assert body["totals"]["by_kind"] == {
        "amount_changed": 3, "created": 3, "reason_changed": 1, "removed": 1, "status_changed": 8}
    assert body["totals"]["events"] == 16

    t = {(x["entity_type"], x["source"], x["from"], x["to"]): x["count"] for x in body["transitions"]["items"]}
    assert t[("charge", "toku", "UNPAID", "PAID")] == 3
    assert t[("charge", "toku", "UNPAID", "FAILED")] == 1 and t[("charge", "tch", "RECHAZADA", "ACEPTADA")] == 1
    assert body["transitions"]["items"][0]["count"] == 3  # ordenado por frecuencia
    assert body["transitions"]["total"] == len(t) == 6

    assert {(c["entity_type"], c["source"]): c["count"] for c in body["created"]} == {
        ("charge", "payku"): 1, ("subscription", "virtualpos1"): 2}
    assert body["subscriptions"]["altas"] == [{"entity_type": "subscription", "source": "virtualpos1", "count": 2}]
    cancellations = {b["source"]: b for b in body["subscriptions"]["bajas"]}
    assert cancellations["virtualpos1"]["count"] == 1 and cancellations["virtualpos1"]["by_state"] == [{"state": "CANCELADA", "count": 1}]
    assert cancellations["payku"]["count"] == 1 and cancellations["toku"]["by_state"] == [{"state": "removed", "count": 1}]

    summary = {(a["entity_type"], a["source"]): a for a in body["amount_changes"]["summary"]}
    a = summary[("charge", "toku")]
    assert (a["count"], a["increases"], a["decreases"], a["net_delta"]) == (3, 1, 1, 1000)  # a3 no tiene delta
    assert body["amount_changes"]["top"][0]["external_id"] == "a1" and body["amount_changes"]["top"][0]["delta"] == 2000

    reasons = body["new_reasons"]["items"]
    assert [(r["source"], r["reason"], r["code"], r["occurrences"]) for r in reasons] == [
        ("tch", "Fondos insuficientes", "51", 4)]


def test_excluye_baseline_and_other_days(db_session: Session) -> None:
    _seed(db_session)
    body = _client(db_session, {"dashboard.view"}).get(f"/api/v1/changes/daily?date={DAY}").json()
    ids = {"b1", "old", "late"}
    flat = str(body)
    assert not any(f"'{i}'" in flat for i in ids)
    nxt = _client(db_session, {"dashboard.view"}).get("/api/v1/changes/daily?date=2026-10-29").json()
    assert nxt["totals"]["events"] == 1  # solo el de la 01:00 de Chile


def test_filtros_y_paginacion(db_session: Session) -> None:
    _seed(db_session)
    client = _client(db_session, {"dashboard.view"})
    body = client.get(f"/api/v1/changes/daily?date={DAY}&source=tch").json()
    assert body["totals"]["events"] == 2 and body["filters"]["source"] == "tch"
    body = client.get(f"/api/v1/changes/daily?date={DAY}&entity_type=subscription").json()
    assert {c["entity_type"] for c in body["created"]} == {"subscription"}
    page = client.get(f"/api/v1/changes/daily?date={DAY}&limit=2&offset=0").json()["transitions"]
    rest = client.get(f"/api/v1/changes/daily?date={DAY}&limit=2&offset=2").json()["transitions"]
    assert len(page["items"]) == 2 and page["total"] == rest["total"] and len(rest["items"]) == 2
    assert page["items"] != rest["items"]


@pytest.mark.parametrize("query", ["date=2026-13-40", "date=ayer", f"date={DAY}&source=zzz",
                                   f"date={DAY}&entity_type=plan", f"date={DAY}&limit=0", f"date={DAY}&limit=501",
                                   f"date={DAY}&offset=-1"])
def test_parametros_invalidos_422(db_session: Session, query: str) -> None:
    assert _client(db_session, {"dashboard.view"}).get(f"/api/v1/changes/daily?{query}").status_code == 422


def test_without_date_uses_yesterday_and_day_empty(db_session: Session) -> None:
    body = _client(db_session, {"dashboard.view"}).get("/api/v1/changes/daily").json()
    assert body["totals"] == {"events": 0, "by_kind": {}} and body["transitions"]["items"] == []


def test_rbac(db_session: Session) -> None:
    anon = TestClient(app, base_url="https://testserver")
    assert anon.get(f"/api/v1/changes/daily?date={DAY}").status_code in (401, 403)
    assert _client(db_session, {"sync_runs.view"}).get(f"/api/v1/changes/daily?date={DAY}").status_code == 403
    assert _client(db_session, {"dashboard.view"}).get(f"/api/v1/changes/daily?date={DAY}").status_code == 200
    assert _client(db_session, executive_permission_codes()).get(f"/api/v1/changes/daily?date={DAY}").status_code == 200
    assert "dashboard.view" in PERMISSIONS


def test_the_response_no_has_fields_personal(db_session: Session) -> None:
    _seed(db_session)
    text_body = _client(db_session, {"dashboard.view"}).get(f"/api/v1/changes/daily?date={DAY}").text.lower()
    for forbidden in ("rut", "email", "first_name", "social_id", "phone", "raw_payload"):
        assert forbidden not in text_body
