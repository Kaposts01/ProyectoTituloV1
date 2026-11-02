# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""BILL-09 / GB-JB-20: allowlist del piloto de la Opcion A (BILLING_PILOT_ALLOWLIST). Sin red (FakeVP).

Solo las suscripciones de la allowlist admiten solicitudes, aprobaciones, reaperturas y aplicacion; el chequeo de
renovacion solo revisa esas. Allowlist vacia = todo bloqueado. Estos tests piden `real_pilot_allowlist` (tests/conftest.py)
para ver el comportamiento real: el resto de la suite la abre.
"""

import asyncio
from datetime import timedelta

import pytest
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    CALLS,
    NOW,
    SUB,
    client_for,
    db_session,
    env,
    make_user,
    names,
    roles_kit,
    seed_sub,
)
from sqlalchemy import select

from app.core.config import settings
from app.models.billing import BillingChangeRequest, BillingRenewalTask, VpCalendarMark
from app.models.crm import Subscription
from app.models.sync_run import SyncRun
from app.services import billing_renewal as rn
from app.services import billing_requests as br

BASE = "/api/v1/billing"
BODY = {"request_type": "change_amount", "platform": "virtualpos1", "subscription_external_id": SUB,
        "new_amount": 12000, "horizon_start_month": "2026-11"}


def params(sub=SUB) -> br.RequestParams:
    return br.RequestParams(request_type="change_amount", platform="virtualpos1", subscription_external_id=sub,
                            new_amount=12000, horizon_start_month="2026-11")


def allow(monkeypatch, value: str) -> None:
    monkeypatch.setattr(settings, "billing_pilot_allowlist", value)


def provider_writes() -> list[str]:
    return [n for n in names() if n != "list_charges"]


@pytest.fixture
def world(db_session, real_pilot_allowlist):
    kit = roles_kit(db_session)
    admin, requester = make_user(db_session, kit["admin"]), make_user(db_session, kit["solicitante"])
    seed_sub(db_session)
    return db_session, admin, requester


# ----------------------------- formato -----------------------------


def test_parse_allowlist_formats_and_fail_closed(real_pilot_allowlist, monkeypatch):
    """Vacia = nada; `plataforma:sub`, id sin plataforma = virtualpos1, alias vp2; plataformas invalidas se ignoran."""
    assert br.pilot_allowlist() == frozenset()
    assert not br.is_pilot_allowlisted("virtualpos1", SUB)
    allow(monkeypatch, f" {SUB} , virtualpos2:s2, vp2:s3, toku:s4, :s5, virtualpos1: ,")
    assert br.pilot_allowlist() == {("virtualpos1", SUB), ("virtualpos2", "s2"), ("virtualpos2", "s3")}
    assert br.is_pilot_allowlisted("vp", SUB) and br.is_pilot_allowlisted("virtualpos2", "s2")
    assert not br.is_pilot_allowlisted("virtualpos2", SUB)  # la plataforma cuenta
    assert not br.is_pilot_allowlisted("toku", "s4") and not br.is_pilot_allowlisted("virtualpos1", "s5")


def test_setting_is_empty_by_default():
    assert type(settings).model_fields["billing_pilot_allowlist"].default == ""


# ----------------------------- solicitudes -----------------------------


def test_empty_allowlist_blocks_create_and_preview_without_reading_provider(world):
    """GB-JB-20: allowlist vacia bloquea todo, antes de leer VirtualPOS."""
    db, _admin, requester = world
    with pytest.raises(br.NotInPilotAllowlistError):
        asyncio.run(br.create_request(db, requester, params(), now=NOW))
    with pytest.raises(br.NotInPilotAllowlistError):
        asyncio.run(br.prepare_request(db, params(), now=NOW))
    assert CALLS == []
    assert db.scalar(select(BillingChangeRequest.id)) is None


def test_only_allowlisted_subscription_can_create(world, monkeypatch):
    db, _admin, requester = world
    allow(monkeypatch, f"virtualpos1:{SUB}")
    req = asyncio.run(br.create_request(db, requester, params(), now=NOW))
    assert req.status == "pendiente"
    db.add(Subscription(source="virtualpos1", external_id="otra", plan_external_id="plan-1", status="ACTIVA"))
    db.commit()
    with pytest.raises(br.NotInPilotAllowlistError):
        asyncio.run(br.create_request(db, requester, params("otra"), now=NOW))


def test_removed_from_allowlist_blocks_approve_reopen_and_apply_without_writes(world, monkeypatch):
    """GB-PI-07 (reversion): al quitarla de la allowlist ya no se aprueba, reabre ni aplica; no se escribe en VP."""
    db, admin, requester = world
    allow(monkeypatch, SUB)
    pending = asyncio.run(br.create_request(db, requester, params(), now=NOW))
    allow(monkeypatch, "")
    with pytest.raises(br.NotInPilotAllowlistError):
        br.approve(db, pending.id, admin, now=NOW)
    db.refresh(pending)
    assert pending.status == "pendiente" and pending.approvals_count == 0

    pending.status = "fallida"
    db.commit()
    with pytest.raises(br.NotInPilotAllowlistError):
        br.reopen(db, pending.id, admin, "reabrir", now=NOW)
    db.refresh(pending)
    assert pending.status == "fallida"

    pending.status = "aprobada"
    db.commit()
    CALLS.clear()
    with pytest.raises(br.NotInPilotAllowlistError):
        asyncio.run(br.apply_request(db, pending.id, admin, now=NOW))
    db.refresh(pending)
    assert pending.status == "aprobada" and provider_writes() == []


def test_withdraw_and_reject_stay_allowed_outside_allowlist(world, monkeypatch):
    """Salir del piloto no deja solicitudes atrapadas: retirar y rechazar siguen permitidos."""
    db, admin, requester = world
    allow(monkeypatch, SUB)
    a = asyncio.run(br.create_request(db, requester, params(), now=NOW))
    allow(monkeypatch, "")
    assert br.reject(db, a.id, admin, "fuera del piloto", now=NOW).status == "rechazada"


def test_api_returns_403_with_clear_message(world, monkeypatch):
    db, admin, _requester = world
    client, h = client_for(db, admin)
    r = client.post(f"{BASE}/changes", json=BODY, headers=h)
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "not_in_pilot_allowlist" and "allowlist del piloto" in detail["message"]
    assert SUB not in detail["message"]
    allow(monkeypatch, SUB)
    assert client.post(f"{BASE}/changes", json=BODY, headers=h).status_code == 201
    policy = client.get(f"{BASE}/policy").json()
    assert policy["pilot_allowlist"] == [f"virtualpos1:{SUB}"]


# ----------------------------- chequeo de renovacion -----------------------------


def test_renewal_check_only_reviews_allowlisted_marks(world, monkeypatch):
    """GB-JB-20: el chequeo solo revisa marcas de la allowlist; las demas se omiten sin crear ni cerrar tareas."""
    db, _admin, _requester = world
    db.add(Subscription(source="virtualpos1", external_id="otra", plan_external_id="plan-1", status="ACTIVA"))
    db.add(SyncRun(source="virtualpos1", status="completed", started_at=NOW - timedelta(hours=1),
                   finished_at=NOW - timedelta(hours=1)))
    for sub in (SUB, "otra"):
        db.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=sub, last_scheduled_month="2026-11",
                              last_scheduled_date=NOW.date() + timedelta(days=10), scheduled_amount=12000,
                              charge_day=5, is_active=True))
    db.commit()

    empty = rn.run_renewal_check(db, NOW)
    assert empty.examined == 0 and empty.not_allowlisted == 2 and empty.opened == 0
    assert db.scalar(select(BillingRenewalTask.id)) is None

    allow(monkeypatch, SUB)
    result = rn.run_renewal_check(db, NOW)
    assert result.opened == 1 and result.not_allowlisted == 1
    subs = set(db.scalars(select(BillingRenewalTask.subscription_external_id)))
    assert subs == {SUB}
