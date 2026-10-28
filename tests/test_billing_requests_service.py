# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""Paso 4: servicio de solicitudes de cambio de cobro y politica (app/services/billing_requests.py), SOLO con fakes.

Sin red: `VirtualPOSClient` es `FakeVP` (ver billing_requests_support.py). Cada test cita en su docstring los
escenarios del doc docs/designs/facturacion-gestionada-escenarios.md (seccion 5: AP-xx; RA-xx; JB-xx).
"""

import asyncio
import inspect
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    CALLS,
    NOW,
    STATE,
    SUB,
    autos,
    db_session,
    env,
    make_user,
    names,
    roles_kit,
    seed_crm_calendar,
    seed_sub,
    set_policy,
)
from sqlalchemy import select, update

from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingPolicy,
    BillingPolicyAudit,
    VpManagedCharge,
)
from app.services import billing_requests as br

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------- helpers -----------------------------


def world(db, *, status="ACTIVA"):
    kit = roles_kit(db)
    admin1, admin2 = make_user(db, kit["admin"]), make_user(db, kit["admin"])
    requester = make_user(db, kit["solicitante"])
    seed_sub(db, status)
    return kit, admin1, admin2, requester


def params(**over) -> br.RequestParams:
    values = dict(request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
                  new_amount=12000, horizon_start_month="2026-11")
    values.update(over)
    return br.RequestParams(**values)


def create(db, user, now=NOW, **over):
    return asyncio.run(br.create_request(db, user, params(**over), now=now))


def events(db, req) -> list[str]:
    return [e.event_type for e in br.get_events(db, req.id)]


def force_status(db, req, status, error=None):
    req.status = status
    req.error_message = error
    req.decision_comment = "motivo" if status == "rechazada" else None
    db.commit()


def no_provider_writes():
    return [n for n in names() if n not in ("list_charges",)] == []


# ----------------------------- crear (4 tipos) -----------------------------


def test_create_change_amount_pending_with_snapshot_and_no_writes(db_session):
    """AP-12/AP-27/AP-29, RA-01: crea pendiente con plan_preview, snapshot, vencimiento a 7 dias y evento creada."""
    _kit, _a1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    assert req.status == "pendiente" and req.approvals_required == 1 and req.approvals_count == 0
    assert req.requested_by_user_id == requester.id and not req.self_approved
    assert req.expires_at == NOW + timedelta(days=7)
    assert len(req.plan_preview["create"]) == 12 and len(req.plan_preview["cancel"]) == 12
    assert req.previous_amount == Decimal(9900) and req.horizon_start_month == "2026-11"
    snap = req.rules_snapshot
    assert snap["plan_external_id"] == "plan-1" and snap["window_days"] == 31 and snap["task_ref"] is None
    assert snap["dual_approval_enabled"] is False and snap["self_approval_enabled"] is True
    assert snap["request_expiry_days"] == 7 and snap["horizon_months"] == 12
    assert events(db_session, req) == ["creada"]
    assert no_provider_writes()  # solo lecturas del proveedor


def test_create_change_date_derives_current_amount(db_session):
    """RA-16, AP-18: cambio de dia sin monto toma el monto actual del proveedor (9900) y reprograma al dia 20."""
    _kit, _a1, _a2, requester = world(db_session)
    req = create(db_session, requester, request_type="change_date", new_amount=None, new_charge_day=20)
    assert req.new_amount == Decimal(9900) and req.previous_amount == Decimal(9900) and req.new_charge_day == 20
    assert len(req.plan_preview["create"]) == 12
    assert all(c["internal_code"].endswith("-d20") and c["charge_date"].endswith("-20") for c in req.plan_preview["create"])
    assert no_provider_writes()


def test_create_renew_calendar_starts_after_last_crm_month(db_session):
    """JB-30, AP-34: renovacion arranca el mes siguiente al ultimo programado por el CRM; monto = marca activa."""
    _kit, _a1, _a2, requester = world(db_session)
    seed_crm_calendar(db_session)
    req = create(db_session, requester, request_type="renew_calendar", new_amount=None, horizon_start_month=None)
    assert req.horizon_start_month == "2027-11" and req.new_amount == Decimal(12000)
    assert len(req.plan_preview["create"]) == 12
    assert sorted(c["charge_id"] for c in req.plan_preview["cancel"]) == ["auto-13", "auto-14"]
    assert no_provider_writes()


def test_create_one_off_charge_with_task_ref(db_session):
    """RA-29: cobro puntual por tarea = un solo create; task_ref queda en el snapshot (codigo propio de la tarea)."""
    _kit, _a1, _a2, requester = world(db_session)
    req = create(db_session, requester, request_type="one_off_charge", new_amount=5000,
                 new_charge_date=date(2026, 11, 20), task_ref="T9", horizon_start_month=None)
    assert len(req.plan_preview["create"]) == 1 and req.plan_preview["cancel"] == []
    assert "T9" in req.plan_preview["create"][0]["internal_code"]
    assert req.rules_snapshot["task_ref"] == "T9" and req.new_charge_date == date(2026, 11, 20)
    assert no_provider_writes()


def test_create_normalizes_platform(db_session):
    """Plataforma 'virtualpos' / mayusculas se normaliza a virtualpos1."""
    _kit, _a1, _a2, requester = world(db_session)
    req = create(db_session, requester, platform=" VirtualPOS ")
    assert req.platform == "virtualpos1"


# ----------------------------- rechazos de creacion -----------------------------


def test_create_rejects_second_open_request(db_session):
    """AP-12: con una solicitud abierta en la suscripcion, otra -> OpenRequestExistsError (409)."""
    _kit, _a1, _a2, requester = world(db_session)
    first = create(db_session, requester)
    with pytest.raises(br.OpenRequestExistsError) as ei:
        create(db_session, requester, new_amount=13000)
    assert ei.value.request_id == first.id and ei.value.status == "pendiente"


def test_create_noop_plan_is_rejected(db_session):
    """Plan sin cambios (los pendientes ya tienen el monto pedido) -> NoChangesError (422)."""
    _kit, _a1, _a2, requester = world(db_session)
    STATE["charges"] = autos(12000)
    with pytest.raises(br.NoChangesError):
        create(db_session, requester)
    assert db_session.scalar(select(BillingChangeRequest)) is None


def test_create_plan_errors_are_rejected_with_detail(db_session):
    """CO-27: fecha de cobro puntual no futura (hoy) -> 422. Desde la tanda 2 la rechaza antes la validacion de entrada
    (new_charge_date entre manana y hoy + 5 anos); el planificador conserva `past_charge_date` como segunda barrera."""
    _kit, _a1, _a2, requester = world(db_session)
    with pytest.raises(br.InvalidRequestFieldsError):
        create(db_session, requester, request_type="one_off_charge", new_amount=5000,
               new_charge_date=date(2026, 10, 28), horizon_start_month=None)


@pytest.mark.parametrize("over", [
    {"new_amount": None},  # change_amount sin monto
    {"new_amount": -5},
    {"platform": "otra"},
    {"horizon_months": 61},
    {"horizon_start_month": "2026-13"},
    {"new_charge_day": 5},  # no aplica a change_amount
    {"task_ref": "x"},  # solo one_off
    {"request_type": "change_date", "new_charge_day": None},
    {"request_type": "one_off_charge", "new_charge_date": None},
    {"request_type": "desconocido"},
])
def test_create_validates_fields_per_type(db_session, over):
    """CHECKs del modelo (monto/dia/horizonte/campos requeridos por tipo) se validan antes de llamar al proveedor."""
    _kit, _a1, _a2, requester = world(db_session)
    with pytest.raises(br.InvalidRequestFieldsError):
        create(db_session, requester, **over)
    assert CALLS == []


def test_create_unknown_and_inactive_subscription(db_session):
    """JB-17/GB-JB-35: suscripcion inexistente o no ACTIVA no admite solicitudes."""
    kit = roles_kit(db_session)
    requester = make_user(db_session, kit["solicitante"])
    with pytest.raises(br.SubscriptionUnknownError):
        create(db_session, requester)
    seed_sub(db_session, "CANCELADA")
    with pytest.raises(br.SubscriptionNotActiveError):
        create(db_session, requester)
    assert CALLS == []


def test_create_blocked_subscription(db_session):
    """RA-09/CS-09: cobros en requiere_conciliacion bloquean nuevas solicitudes."""
    _kit, _a1, _a2, requester = world(db_session)
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="x-1", subscription_external_id=SUB,
                                   internal_code="c", month="2026-11", amount=1, status="requiere_conciliacion"))
    db_session.commit()
    with pytest.raises(br.SubscriptionBlockedError):
        create(db_session, requester)


# ----------------------------- autoaprobacion y aprobacion -----------------------------


def test_self_approval_on_create_when_policy_allows_and_requester_is_approver(db_session):
    """AP-02: admin solicitante con autoaprobacion activada -> aprobada, evento autoaprobada, self_approved."""
    _kit, admin1, _a2, _r = world(db_session)
    req = create(db_session, admin1)
    assert req.status == "aprobada" and req.self_approved and req.approved_by_user_id == admin1.id
    assert req.approvals_count == 1 and req.decided_at is not None
    evs = br.get_events(db_session, req.id)
    assert [e.event_type for e in evs] == ["creada", "autoaprobada"]
    assert evs[1].actor_user_id == admin1.id and evs[1].detail["self_approved"] is True


def test_requester_who_is_not_approver_stays_pending(db_session):
    """AP-04: solicitante sin condicion de aprobador queda pendiente aunque la autoaprobacion este activa."""
    _kit, _a1, _a2, requester = world(db_session)
    assert create(db_session, requester).status == "pendiente"


def test_manual_approval_by_another_admin(db_session):
    """AP-06, AP-16, AP-31: otro admin aprueba (con comentario); evento 'aprobada' con su actor; no es autoaprobacion."""
    _kit, admin1, admin2, requester = world(db_session)
    req = create(db_session, requester)
    out = br.approve(db_session, req.id, admin2, "ok", now=NOW)
    assert out.status == "aprobada" and out.approved_by_user_id == admin2.id and not out.self_approved
    ev = br.get_events(db_session, req.id)[-1]
    assert ev.event_type == "aprobada" and ev.actor_user_id == admin2.id and ev.detail["comment"] == "ok"
    assert no_provider_writes()
    assert admin1.id != admin2.id


def test_self_approval_disabled_blocks_own_approval_but_not_others(db_session):
    """AP-01, AP-26: con autoaprobacion apagada el admin no aprueba lo propio; otro aprobador si."""
    _kit, admin1, admin2, _r = world(db_session)
    req = create(db_session, admin1)  # autoaprobada al crear (politica vigente entonces)
    assert req.status == "aprobada"
    other = create_after_release(db_session, admin1)  # pendiente con la politica nueva
    assert other.status == "pendiente"
    with pytest.raises(br.SelfApprovalNotAllowedError):
        br.approve(db_session, other.id, admin1, now=NOW)
    assert db_session.get(BillingChangeRequest, other.id).status == "pendiente"
    assert br.approve(db_session, other.id, admin2, now=NOW).status == "aprobada"


def create_after_release(db, admin):
    """Libera la suscripcion (la primera pasa a ejecutada) y apaga la autoaprobacion antes de crear otra."""
    db.execute(update(BillingChangeRequest).values(status="ejecutada"))
    db.commit()
    set_policy(db, self_approval_enabled=False)
    return create(db, admin, new_amount=13000)


def test_non_approver_cannot_approve_or_reject(db_session):
    """AP-04: quien no es aprobador segun la politica (aunque tenga el permiso) -> NotApproverError, sin cambio de estado."""
    kit, _a1, _a2, requester = world(db_session)
    with_perm_not_in_policy = make_user(db_session, kit["aprobador"])  # permiso approve, pero no listado en la politica
    req = create(db_session, requester)
    with pytest.raises(br.NotApproverError):
        br.approve(db_session, req.id, with_perm_not_in_policy, now=NOW)
    with pytest.raises(br.NotApproverError):
        br.reject(db_session, req.id, with_perm_not_in_policy, "no", now=NOW)
    assert db_session.get(BillingChangeRequest, req.id).status == "pendiente"
    assert events(db_session, req) == ["creada"]


def test_approver_removed_from_policy_loses_access_immediately(db_session):
    """AP-21, AP-25: quitar al aprobador de la politica lo deja sin acceso al aprobar (se evalua al aprobar)."""
    kit, admin1, admin2, requester = world(db_session)
    userlisted = make_user(db_session, kit["aprobador"])
    set_policy(db_session, approver_roles=[], approver_user_ids=[str(userlisted.id), str(admin2.id)])
    req = create(db_session, requester)
    set_policy(db_session, approver_user_ids=[str(admin2.id)])
    with pytest.raises(br.NotApproverError):
        br.approve(db_session, req.id, userlisted, now=NOW)
    with pytest.raises(br.NotApproverError):
        br.approve(db_session, req.id, admin1, now=NOW)  # admin sin estar listado ya no aprueba
    assert br.approve(db_session, req.id, admin2, now=NOW).status == "aprobada"


def test_listed_non_admin_user_can_approve(db_session):
    """AP-21: un usuario con permiso approve agregado a la politica por id puede aprobar."""
    kit, _a1, _a2, requester = world(db_session)
    listed = make_user(db_session, kit["aprobador"])
    set_policy(db_session, approver_user_ids=[str(listed.id)])
    req = create(db_session, requester)
    assert br.approve(db_session, req.id, listed, now=NOW).status == "aprobada"


# ----------------------------- doble aprobacion -----------------------------


def _policy(**over):
    base = dict(dual_approval_enabled=True, dual_threshold_subscriptions=20, dual_threshold_variation_pct=Decimal("50"))
    base.update(over)
    return BillingPolicy(**base)


def test_required_approvals_thresholds():
    """AP-07/AP-08/AP-09: 21 suscripciones -> 2; 20 exactas -> 1; 50 % -> 1; 50,01 % -> 2; apagada -> siempre 1."""
    p = _policy()
    assert br.required_approvals(p, subscriptions=21, variation_pct=0) == 2
    assert br.required_approvals(p, subscriptions=20, variation_pct=0) == 1
    assert br.required_approvals(p, subscriptions=1, variation_pct=50.0) == 1
    assert br.required_approvals(p, subscriptions=1, variation_pct=50.01) == 2
    assert br.required_approvals(p, subscriptions=1, variation_pct=None) == 1
    off = _policy(dual_approval_enabled=False)
    assert br.required_approvals(off, subscriptions=500, variation_pct=900.0) == 1


def test_dual_approval_self_counts_once_and_needs_distinct_second(db_session):
    """AP-07, AP-36: variacion > 50 %: el solicitante-aprobador cuenta UNA vez; el mismo usuario no suma dos veces."""
    _kit, admin1, admin2, _r = world(db_session)
    set_policy(db_session, dual_approval_enabled=True)
    req = create(db_session, admin1, new_amount=15000)  # 51,5 % sobre 9900
    assert req.approvals_required == 2 and req.approvals_count == 1 and req.status == "pendiente" and req.self_approved
    assert events(db_session, req) == ["creada", "autoaprobada"]
    with pytest.raises(br.DuplicateApproverError):
        br.approve(db_session, req.id, admin1, now=NOW)  # mismo usuario dos veces no cuenta
    assert db_session.get(BillingChangeRequest, req.id).approvals_count == 1
    out = br.approve(db_session, req.id, admin2, now=NOW)
    assert out.status == "aprobada" and out.approvals_count == 2 and out.approved_by_user_id == admin2.id
    assert out.self_approved is True


def test_dual_approval_two_distinct_approvers_when_requester_not_approver(db_session):
    """AP-07: solicitante comun; el primer aprobador deja 1/2 (y no puede repetir); el segundo distinto ejecuta."""
    _kit, admin1, admin2, requester = world(db_session)
    set_policy(db_session, dual_approval_enabled=True)
    req = create(db_session, requester, new_amount=15000)
    assert req.approvals_required == 2 and req.approvals_count == 0
    one = br.approve(db_session, req.id, admin1, now=NOW)
    assert one.status == "pendiente" and one.approvals_count == 1
    with pytest.raises(br.DuplicateApproverError):
        br.approve(db_session, req.id, admin1, now=NOW)
    two = br.approve(db_session, req.id, admin2, now=NOW)
    assert two.status == "aprobada" and two.approvals_count == 2
    assert events(db_session, req) == ["creada", "aprobada", "aprobada"]


def test_dual_approval_small_variation_needs_one(db_session):
    """AP-09: con doble aprobacion encendida, una variacion <= 50 % se aprueba con 1."""
    _kit, admin1, _a2, requester = world(db_session)
    set_policy(db_session, dual_approval_enabled=True)
    req = create(db_session, requester, new_amount=12000)
    assert req.approvals_required == 1
    assert br.approve(db_session, req.id, admin1, now=NOW).status == "aprobada"


# ----------------------------- concurrencia -----------------------------


def test_second_approval_after_decision_gets_conflict(db_session):
    """AP-14: la solicitud ya decidida no se vuelve a aprobar; una sola aprobacion queda registrada."""
    _kit, admin1, admin2, requester = world(db_session)
    req = create(db_session, requester)
    br.approve(db_session, req.id, admin1, now=NOW)
    with pytest.raises(br.RequestStateConflictError) as ei:
        br.approve(db_session, req.id, admin2, now=NOW)
    assert ei.value.current_status == "aprobada"
    assert events(db_session, req).count("aprobada") == 1


def test_stale_read_loses_the_conditional_update(db_session, monkeypatch):
    """AP-14: aunque la lectura sea 'pendiente', si otra transaccion decidio antes, el UPDATE condicional no aplica."""
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    original = br._lock_request

    def racing(db, rid):
        locked = original(db, rid)  # ve 'pendiente'...
        db.execute(update(BillingChangeRequest).where(BillingChangeRequest.id == rid)
                   .values(status="aprobada", approvals_count=1).execution_options(synchronize_session=False))
        return locked  # ...pero otra transaccion ya la aprobo

    monkeypatch.setattr(br, "_lock_request", racing)
    with pytest.raises(br.RequestStateConflictError):
        br.approve(db_session, req.id, admin1, now=NOW)
    assert events(db_session, req) == ["creada"]  # el perdedor no deja evento de aprobacion


# ----------------------------- rechazar / retirar -----------------------------


@pytest.mark.parametrize("comment", [None, "", "   \n"])
def test_reject_requires_non_blank_comment(db_session, comment):
    """AP-11: rechazar sin comentario (o solo espacios) -> CommentRequiredError; estado intacto."""
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    with pytest.raises(br.CommentRequiredError):
        br.reject(db_session, req.id, admin1, comment, now=NOW)
    assert db_session.get(BillingChangeRequest, req.id).status == "pendiente"


def test_reject_with_comment(db_session):
    """AP-11: rechazada con comentario visible para el solicitante y evento con actor."""
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    out = br.reject(db_session, req.id, admin1, "  monto incorrecto ", now=NOW)
    assert out.status == "rechazada" and out.decision_comment == "monto incorrecto"
    ev = br.get_events(db_session, req.id)[-1]
    assert (ev.event_type, ev.actor_user_id, ev.detail["comment"]) == ("rechazada", admin1.id, "monto incorrecto")
    with pytest.raises(br.RequestStateConflictError):
        br.reject(db_session, req.id, admin1, "otra vez", now=NOW)


def test_withdraw_only_requester_or_admin_and_only_pending(db_session):
    """AP-33: retira el solicitante o un admin; otro usuario -> NotAllowedError; solo pendiente."""
    kit, admin1, _a2, requester = world(db_session)
    stranger = make_user(db_session, kit["solicitante"])
    req = create(db_session, requester)
    with pytest.raises(br.NotAllowedError):
        br.withdraw(db_session, req.id, stranger)
    assert br.withdraw(db_session, req.id, requester, "ya no").status == "retirada"
    ev = br.get_events(db_session, req.id)[-1]
    assert (ev.event_type, ev.actor_user_id) == ("retirada", requester.id)
    with pytest.raises(br.RequestStateConflictError):
        br.withdraw(db_session, req.id, requester)
    again = create(db_session, requester)
    assert br.withdraw(db_session, again.id, admin1).status == "retirada"  # admin retira ajena
    approved = create(db_session, admin1)  # autoaprobada: ya no es pendiente
    with pytest.raises(br.RequestStateConflictError):
        br.withdraw(db_session, approved.id, admin1)


# ----------------------------- expiracion -----------------------------


def test_expire_pending_requests_boundary_is_inclusive(db_session):
    """AP-10: vence a los 7 dias; en el instante exacto ya esta expirada (limite inclusivo); idempotente."""
    _kit, _a1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    limit = req.expires_at
    assert br.expire_pending_requests(db_session, limit - timedelta(seconds=1)) == []
    assert db_session.get(BillingChangeRequest, req.id).status == "pendiente"
    assert br.expire_pending_requests(db_session, limit) == [req.id]
    db_session.refresh(req)
    assert req.status == "expirada"
    ev = br.get_events(db_session, req.id)[-1]
    assert ev.event_type == "expirada" and ev.actor_user_id is None
    assert br.expire_pending_requests(db_session, limit + timedelta(days=1)) == []


def test_expire_does_not_touch_approved_requests(db_session):
    """Solo las pendientes expiran: una aprobada (pendiente de aplicar) no."""
    _kit, admin1, _a2, _r = world(db_session)
    req = create(db_session, admin1)
    assert br.expire_pending_requests(db_session, NOW + timedelta(days=30)) == []
    assert db_session.get(BillingChangeRequest, req.id).status == "aprobada"


def test_approve_after_expiry_marks_expired(db_session):
    """AP-10: aprobar una vencida -> RequestExpiredError, queda 'expirada' y no es ejecutable."""
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    with pytest.raises(br.RequestExpiredError):
        br.approve(db_session, req.id, admin1, now=req.expires_at)
    assert db_session.get(BillingChangeRequest, req.id).status == "expirada"
    assert events(db_session, req) == ["creada", "expirada"]


# ----------------------------- reabrir -----------------------------


@pytest.mark.parametrize("status", ["fallida", "requiere_conciliacion"])
def test_reopen_with_comment_goes_back_to_approved(db_session, status):
    """Reabrir: solo desde fallida/requiere_conciliacion, con comentario; evento reintentada{action: reabierta}."""
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    force_status(db_session, req, status, "RuntimeError E-113")
    out = br.reopen(db_session, req.id, admin1, " tras revisar el proveedor ", now=NOW)
    assert out.status == "aprobada" and out.error_message is None
    ev = br.get_events(db_session, req.id)[-1]
    assert ev.event_type == "reintentada" and ev.actor_user_id == admin1.id
    assert ev.detail["action"] == "reabierta" and ev.detail["from_status"] == status
    assert ev.detail["comment"] == "tras revisar el proveedor" and ev.detail["previous_error"] == "RuntimeError E-113"
    assert no_provider_writes()  # no hay reintento automatico


@pytest.mark.parametrize("comment", [None, "", "  "])
def test_reopen_without_comment_is_rejected(db_session, comment):
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    force_status(db_session, req, "fallida")
    with pytest.raises(br.CommentRequiredError):
        br.reopen(db_session, req.id, admin1, comment)
    assert db_session.get(BillingChangeRequest, req.id).status == "fallida"


@pytest.mark.parametrize("status", ["pendiente", "aprobada", "aplicando", "ejecutada", "rechazada", "expirada", "retirada", "no_ejecutable"])
def test_reopen_only_from_failed_states(db_session, status):
    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    force_status(db_session, req, status)
    with pytest.raises(br.RequestStateConflictError) as ei:
        br.reopen(db_session, req.id, admin1, "intento")
    assert ei.value.current_status == status


def test_reopen_authorization(db_session):
    """Tanda 2: reabre SOLO un aprobador segun la politica vigente; billing_policy.manage por si solo no basta."""
    kit, admin1, _a2, requester = world(db_session)
    manager = make_user(db_session, kit["gestor"])  # manage, sin condicion de aprobador
    listed = make_user(db_session, kit["aprobador"])
    unlisted = make_user(db_session, kit["aprobador"])
    executive = make_user(db_session, kit["ejecutivo"])
    set_policy(db_session, approver_user_ids=[str(listed.id)])
    req = create(db_session, requester)
    force_status(db_session, req, "fallida")
    for denied in (executive, unlisted, requester, manager):
        with pytest.raises(br.NotApproverError):
            br.reopen(db_session, req.id, denied, "x")
    assert db_session.get(BillingChangeRequest, req.id).status == "fallida"
    force_status(db_session, req, "requiere_conciliacion")
    assert br.reopen(db_session, req.id, listed, "aprobador").status == "aprobada"
    force_status(db_session, req, "fallida")
    assert br.reopen(db_session, req.id, admin1, "admin").status == "aprobada"


def test_reopen_blocked_if_another_open_request_exists(db_session):
    """Una fallida no cuenta como abierta: si se creo otra, reabrir la vieja choca con el indice unico -> 409."""
    _kit, admin1, _a2, requester = world(db_session)
    old = create(db_session, requester)
    force_status(db_session, old, "fallida")
    newer = create(db_session, requester, new_amount=13000)
    with pytest.raises(br.OpenRequestExistsError):
        br.reopen(db_session, old.id, admin1, "reabrir")
    assert db_session.get(BillingChangeRequest, old.id).status == "fallida"
    assert db_session.get(BillingChangeRequest, newer.id).status == "pendiente"


# ----------------------------- politica -----------------------------


def test_default_policy_values(db_session):
    """AP-20: valores por defecto de la politica vigente (decisiones 2026-10-28)."""
    v = br.policy_values(br.get_policy(db_session))
    assert v["approver_roles"] == ["admin"] and v["approver_user_ids"] == []
    assert v["self_approval_enabled"] is True and v["dual_approval_enabled"] is False
    assert (v["dual_threshold_subscriptions"], v["dual_threshold_variation_pct"]) == (20, 50.0)
    assert (v["renewal_threshold_days"], v["request_expiry_days"], v["horizon_months"], v["window_days"]) == (60, 7, 12, 31)


def test_policy_cannot_be_saved_without_approvers(db_session):
    """AP-23: sin roles ni usuarios aprobadores -> PolicyValidationError no_approvers; la politica no cambia."""
    _kit, admin1, _a2, _r = world(db_session)
    with pytest.raises(br.PolicyValidationError) as ei:
        br.update_policy(db_session, admin1, {"approver_roles": []}, "x")
    assert ei.value.policy_code == "no_approvers"
    assert br.policy_values(br.get_policy(db_session))["approver_roles"] == ["admin"]
    assert db_session.scalar(select(BillingPolicyAudit)) is None


def test_self_approval_cannot_be_disabled_without_another_approver(db_session):
    """AP-24: desactivar la autoaprobacion se bloquea si no queda otro aprobador activo distinto de quien edita."""
    kit, admin1, admin2, _r = world(db_session)
    set_policy(db_session, approver_roles=[], approver_user_ids=[str(admin1.id)])
    with pytest.raises(br.PolicyValidationError) as ei:
        br.update_policy(db_session, admin1, {"self_approval_enabled": False}, "x")
    assert ei.value.policy_code == "no_other_approver"
    inactive = make_user(db_session, kit["admin"], active=False)
    with pytest.raises(br.PolicyValidationError):  # un inactivo no cuenta (ademas: no se puede listar)
        br.update_policy(db_session, admin1, {"approver_user_ids": [str(admin1.id), str(inactive.id)], "self_approval_enabled": False})
    out = br.update_policy(db_session, admin1, {"approver_user_ids": [str(admin1.id), str(admin2.id)], "self_approval_enabled": False}, "ok")
    assert out.self_approval_enabled is False


@pytest.mark.parametrize("patch", [
    {"dual_threshold_subscriptions": 0}, {"dual_threshold_variation_pct": -1}, {"renewal_threshold_days": 0},
    {"request_expiry_days": 0}, {"horizon_months": 61}, {"horizon_months": 0}, {"window_days": 0},
    {"approver_roles": ["rol-que-no-existe"]}, {"approver_user_ids": ["no-es-uuid"]},
    {"approver_user_ids": ["00000000-0000-0000-0000-000000000001"]}, {"campo_inventado": 1},
])
def test_policy_rejects_invalid_values(db_session, patch):
    """Rangos del modelo, roles inexistentes y usuarios inexistentes/inactivos -> PolicyValidationError."""
    _kit, admin1, _a2, _r = world(db_session)
    with pytest.raises(br.PolicyValidationError):
        br.update_policy(db_session, admin1, patch, "x")


def test_policy_update_writes_audit_in_same_transaction(db_session):
    """AP-35: toda edicion deja before/after/reason/actor; sin cambios -> NoChangesError y sin auditoria."""
    _kit, admin1, _a2, _r = world(db_session)
    out = br.update_policy(db_session, admin1, {"request_expiry_days": 14, "dual_approval_enabled": True}, " endurecer ")
    assert out.request_expiry_days == 14 and out.dual_approval_enabled and out.updated_by_user_id == admin1.id
    audit = db_session.scalars(select(BillingPolicyAudit)).all()
    assert len(audit) == 1
    a = audit[0]
    assert a.changed_by_user_id == admin1.id and a.reason == "endurecer" and a.policy_id == out.id
    assert (a.before_values["request_expiry_days"], a.after_values["request_expiry_days"]) == (7, 14)
    assert (a.before_values["dual_approval_enabled"], a.after_values["dual_approval_enabled"]) == (False, True)
    with pytest.raises(br.NoChangesError):
        br.update_policy(db_session, admin1, {"request_expiry_days": 14}, "igual")
    assert len(db_session.scalars(select(BillingPolicyAudit)).all()) == 1


def test_policy_change_does_not_rewrite_pending_snapshot(db_session):
    """AP-27: la solicitud pendiente conserva su regla (cuantas aprobaciones, vencimiento, ventana); las nuevas usan la nueva."""
    kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    before = dict(req.rules_snapshot)
    br.update_policy(db_session, admin1, {"dual_approval_enabled": True, "request_expiry_days": 30, "window_days": 10}, "cambio")
    db_session.refresh(req)
    assert req.rules_snapshot == before and req.rules_snapshot["dual_approval_enabled"] is False
    assert req.approvals_required == 1 and req.expires_at == NOW + timedelta(days=7)
    assert br.approve(db_session, req.id, admin1, now=NOW).status == "aprobada"  # 1 aprobacion basta para la vieja
    db_session.execute(update(BillingChangeRequest).values(status="ejecutada"))
    db_session.commit()
    newer = create(db_session, requester, new_amount=15000)
    assert newer.rules_snapshot["dual_approval_enabled"] is True and newer.rules_snapshot["window_days"] == 10
    assert newer.approvals_required == 2 and newer.expires_at == NOW + timedelta(days=30)
    assert kit  # roles creados


# ----------------------------- consulta -----------------------------


def test_list_filters_and_pagination(db_session):
    """AP-28/AP-32: filtros por estado, plataforma, suscripcion, tipo, solicitante, fechas y paginacion."""
    _kit, admin1, _a2, requester = world(db_session)
    first = create(db_session, requester)
    br.withdraw(db_session, first.id, requester)
    second = create(db_session, admin1, request_type="one_off_charge", new_amount=5000,
                    new_charge_date=date(2026, 11, 20), horizon_start_month=None)
    def f(**kw):
        return br.RequestFilters(**{"subscription_external_id": SUB, **kw})

    rows, total = br.list_requests(db_session, f())
    assert total == 2 and {r.id for r in rows} == {first.id, second.id}
    assert [r.id for r in br.list_requests(db_session, f(statuses=["retirada"]))[0]] == [first.id]
    assert [r.id for r in br.list_requests(db_session, f(statuses=["aprobada"]))[0]] == [second.id]
    assert br.list_requests(db_session, f(request_type="one_off_charge"))[1] == 1
    assert br.list_requests(db_session, f(requested_by_user_id=requester.id))[1] == 1
    assert br.list_requests(db_session, f(platform="virtualpos1"))[1] == 2
    assert br.list_requests(db_session, f(subscription_external_id="otra"))[1] == 0
    assert br.list_requests(db_session, f(platform="virtualpos2"))[1] == 0
    page, total = br.list_requests(db_session, f(limit=1, offset=1))
    assert len(page) == 1 and total == 2


def test_events_are_immutable_audit_with_actor(db_session):
    """AP-16: cada transicion deja un evento con actor; el trigger de BD impide modificarlos."""
    from sqlalchemy.exc import DBAPIError

    _kit, admin1, _a2, requester = world(db_session)
    req = create(db_session, requester)
    br.approve(db_session, req.id, admin1, now=NOW)
    evs = br.get_events(db_session, req.id)
    assert [(e.event_type, e.actor_user_id) for e in evs] == [("creada", requester.id), ("aprobada", admin1.id)]
    with pytest.raises(DBAPIError):
        db_session.execute(update(BillingChangeRequestEvent).values(detail={"x": 1}))
    db_session.rollback()


# ----------------------------- guardas -----------------------------


def test_service_and_routes_never_use_plural_delete():
    """CO-16: ni el servicio ni las rutas tocan el DELETE plural ni cancelan en bloque."""
    for rel in ("app/services/billing_requests.py", "app/api/v1/routes/billing_changes.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "delete_subscription_charges" not in src and "cancel_future_charges" not in src, rel
        assert "dry_run=False" not in src
    assert "apply_change_request" in inspect.getsource(br.apply_request)
