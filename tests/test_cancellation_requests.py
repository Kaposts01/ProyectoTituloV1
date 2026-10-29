# ruff: noqa: F811  (fixtures importadas de cancellation_support: db_session/_env)
"""MGT-07: ciclo de vida de las solicitudes de baja multicanal (crear, vista previa, aprobar, rechazar, retirar, expirar,
reabrir). Solo base de test; ningun proveedor es llamado."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from billing_requests_support import set_policy
from cancellation_support import (
    NOW,
    db_session,  # noqa: F401 - fixture
    expire_in_past,
    make_roles,
    make_user,
    params,
    seed_payku,
    seed_tch,
    seed_toku,
    seed_vp,
)
from sqlalchemy import select

from app.models.cancellation import (
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)
from app.services import cancellation_requests as cr


def _events(db, req):
    return [e.event_type for e in cr.get_events(db, req.id)]


def test_jefatura_request_is_self_approved_and_audited(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    req = cr.create_request(db_session, jefa, params(), now=NOW)
    assert req.status == "approved" and req.self_approved is True and req.approved_by_user_id == jefa.id
    assert req.requested_by_user_id == jefa.id
    assert _events(db_session, req) == ["created", "self_approved"]
    assert req.expires_at == NOW + timedelta(days=7)
    assert req.cascade_preview["pending_charges"] == 2
    assert [s["step"] for s in req.cascade_preview["steps"]] == [
        "stop_subscription", "cancel_pending_charges", "payment_method"]
    assert req.approvals_required == 1  # doble aprobacion apagada


def test_requester_without_approve_waits_for_another_approver(db_session) -> None:
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    req = cr.create_request(db_session, solicitante, params(), now=NOW)
    assert req.status == "pending" and req.self_approved is False
    approved = cr.approve(db_session, req.id, jefa, "ok", now=NOW)
    assert approved.status == "approved" and approved.approved_by_user_id == jefa.id and approved.self_approved is False
    assert _events(db_session, req) == ["created", "approved"]
    with pytest.raises(cr.RequestStateConflictError):
        cr.approve(db_session, req.id, jefa, now=NOW)  # ya no esta pendiente


def test_self_approval_can_be_disabled_by_policy(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    otra = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    set_policy(db_session, self_approval_enabled=False)
    req = cr.create_request(db_session, jefa, params(), now=NOW)
    assert req.status == "pending"
    with pytest.raises(cr.SelfApprovalNotAllowedError):
        cr.approve(db_session, req.id, jefa, now=NOW)
    assert cr.approve(db_session, req.id, otra, now=NOW).status == "approved"


def test_dual_approval_is_off_by_default_and_one_subscription_never_needs_two(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    assert req_policy_dual(db_session) is False
    set_policy(db_session, dual_approval_enabled=True)
    req = cr.create_request(db_session, jefa, params(), now=NOW)
    assert req.approvals_required == 1  # una sola suscripcion nunca supera el umbral de lote


def req_policy_dual(db) -> bool:
    from app.services import billing_requests as br

    return bool(br.get_policy(db).dual_approval_enabled)


def test_reason_is_mandatory_code_and_comment(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    with pytest.raises(cr.CommentRequiredError):
        cr.create_request(db_session, jefa, params(reason_comment="   "), now=NOW)
    with pytest.raises(cr.InvalidFieldsError):
        cr.create_request(db_session, jefa, params(reason_code="porque_si"), now=NOW)
    assert db_session.scalars(select(SubscriptionCancellationRequest)).first() is None


def test_unknown_or_already_cancelled_subscription_is_rejected(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    with pytest.raises(cr.SubscriptionUnknownError):
        cr.create_request(db_session, jefa, params(sub="no-existe"), now=NOW)
    seed_vp(db_session, "sub-cancelada", status="CANCELADA")
    with pytest.raises(cr.SubscriptionNotActiveError):
        cr.create_request(db_session, jefa, params(sub="sub-cancelada"), now=NOW)
    with pytest.raises(cr.InvalidFieldsError):
        cr.create_request(db_session, jefa, params(channel="otro"), now=NOW)


def test_only_one_open_request_per_subscription(db_session) -> None:
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    first = cr.create_request(db_session, solicitante, params(), now=NOW)
    with pytest.raises(cr.OpenRequestExistsError) as exc:
        cr.create_request(db_session, jefa, params(), now=NOW)
    assert exc.value.request_id == first.id
    cr.withdraw(db_session, first.id, solicitante, now=NOW)
    again = cr.create_request(db_session, jefa, params(), now=NOW)  # cerrada la anterior, se puede abrir otra
    assert again.id != first.id


def test_payku_requires_explicit_irreversibility_confirmation(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_payku(db_session)
    with pytest.raises(cr.IrreversibleNotConfirmedError):
        cr.create_request(db_session, jefa, params("payku", "sus_pk1"), now=NOW)
    req = cr.create_request(db_session, jefa, params("payku", "sus_pk1", confirm_irreversible=True), now=NOW)
    assert req.options == {"confirm_irreversible": True}
    assert req.cascade_preview["irreversible"] is True and req.cascade_preview["pending_charges"] == 1
    with pytest.raises(cr.InvalidFieldsError):  # la confirmacion solo aplica a Payku
        seed_vp(db_session)
        cr.create_request(db_session, jefa, params(confirm_irreversible=True), now=NOW)


def test_toku_stop_mode_defaults_to_paused_and_never_delete(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_toku(db_session)
    with pytest.raises(cr.InvalidFieldsError):
        cr.create_request(db_session, jefa, params("toku", "sub_tk1", toku_stop_mode="delete"), now=NOW)
    req = cr.create_request(db_session, jefa, params("toku", "sub_tk1"), now=NOW)
    assert req.options == {"toku_stop_mode": "paused"}
    assert req.cascade_preview["steps"][0] == {"step": "stop_subscription", "action": "pause_subscription", "reversible": True}
    assert "delete" not in str(req.cascade_preview).lower()


def test_toku_end_date_mode_validates_date(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_toku(db_session)
    with pytest.raises(cr.InvalidFieldsError):
        cr.create_request(db_session, jefa, params("toku", "sub_tk1", toku_stop_mode="end_date"), now=NOW)
    with pytest.raises(cr.InvalidFieldsError):
        cr.create_request(db_session, jefa, params("toku", "sub_tk1", toku_stop_mode="end_date",
                                                   toku_end_date=date(2020, 1, 1)), now=NOW)
    req = cr.create_request(db_session, jefa, params("toku", "sub_tk1", toku_stop_mode="end_date",
                                                     toku_end_date=date(2026, 12, 31)), now=NOW)
    assert req.options == {"toku_stop_mode": "end_date", "toku_end_date": "2026-12-31"}


def test_toku_preview_flags_in_progress_invoices_as_blocker(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_toku(db_session, unpaid=2, in_progress=1)
    req = cr.create_request(db_session, jefa, params("toku", "sub_tk1"), now=NOW)
    assert req.cascade_preview["blockers"] == ["INVOICE_IN_PROGRESS"]
    assert req.cascade_preview["pending_charges"] == 2 and req.cascade_preview["in_progress_invoices"] == 1


def test_tch_request_has_internal_steps_and_no_charges(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    ficha = seed_tch(db_session)
    req = cr.create_request(db_session, jefa, params("tch", ficha), now=NOW)
    assert [s["step"] for s in req.cascade_preview["steps"]] == ["register_internal", "bank_mandate"]
    assert req.cascade_preview["pending_charges"] == 0
    seed_tch(db_session, 910002, eliminated=True)
    with pytest.raises(cr.SubscriptionNotActiveError):
        cr.create_request(db_session, jefa, params("tch", "910002"), now=NOW)


def test_reject_needs_comment_and_approver(db_session) -> None:
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    jefa = make_user(db_session, roles["jefatura"])
    ejecutivo = make_user(db_session, roles["ejecutivo"])
    seed_vp(db_session)
    req = cr.create_request(db_session, solicitante, params(), now=NOW)
    with pytest.raises(cr.NotApproverError):
        cr.reject(db_session, req.id, ejecutivo, "no", now=NOW)
    with pytest.raises(cr.NotApproverError):
        cr.approve(db_session, req.id, ejecutivo, now=NOW)
    with pytest.raises(cr.CommentRequiredError):
        cr.reject(db_session, req.id, jefa, "  ", now=NOW)
    rejected = cr.reject(db_session, req.id, jefa, "Falta respaldo", now=NOW)
    assert rejected.status == "rejected" and rejected.decision_comment == "Falta respaldo"
    assert _events(db_session, req)[-1] == "rejected"


def test_withdraw_only_by_requester_or_admin(db_session) -> None:
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    jefa = make_user(db_session, roles["jefatura"])
    admin = make_user(db_session, roles["admin"])
    seed_vp(db_session)
    req = cr.create_request(db_session, solicitante, params(), now=NOW)
    with pytest.raises(cr.NotAllowedError):
        cr.withdraw(db_session, req.id, jefa, now=NOW)  # ni siquiera una jefatura retira lo ajeno
    assert cr.withdraw(db_session, req.id, admin, "duplicada", now=NOW).status == "withdrawn"


def test_expired_request_cannot_be_approved_and_sweeper_expires(db_session) -> None:
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session, "sub-e1")
    seed_vp(db_session, "sub-e2")
    first = cr.create_request(db_session, solicitante, params(sub="sub-e1"), now=NOW)
    second = cr.create_request(db_session, solicitante, params(sub="sub-e2"), now=NOW)
    expire_in_past(db_session, first)
    with pytest.raises(cr.RequestExpiredError):
        cr.approve(db_session, first.id, jefa, now=NOW)
    assert cr.get_request(db_session, first.id).status == "expired"
    expire_in_past(db_session, second)
    assert cr.expire_pending_cancellation_requests(db_session, NOW) == [second.id]
    assert cr.expire_pending_cancellation_requests(db_session, NOW) == []  # idempotente
    assert _events(db_session, second)[-1] == "expired"
    last = cr.get_events(db_session, second.id)[-1]
    assert last.actor_user_id is None  # actor sistema


def test_reopen_keeps_done_steps_and_requires_comment_and_approver(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    ejecutivo = make_user(db_session, roles["ejecutivo"])
    seed_vp(db_session)
    req = cr.create_request(db_session, jefa, params(), now=NOW)
    with pytest.raises(cr.RequestStateConflictError):
        cr.reopen(db_session, req.id, jefa, "x", now=NOW)  # aprobada: no reabrible
    req.status = "requires_reconciliation"
    req.requires_reconciliation = True
    req.error_message = "cancel_pending_charges:PENDING_CHARGES_REMAIN"
    req.steps = [{"step": "stop_subscription", "status": "done", "code": None}]
    db_session.commit()
    with pytest.raises(cr.NotApproverError):
        cr.reopen(db_session, req.id, ejecutivo, "x", now=NOW)
    with pytest.raises(cr.CommentRequiredError):
        cr.reopen(db_session, req.id, jefa, " ", now=NOW)
    reopened = cr.reopen(db_session, req.id, jefa, "Se resolvio a mano en el portal", now=NOW)
    assert reopened.status == "approved" and reopened.requires_reconciliation is False
    assert reopened.error_message is None
    assert reopened.steps == [{"step": "stop_subscription", "status": "done", "code": None}]
    last = cr.get_events(db_session, req.id)[-1]
    assert last.event_type == "reopened" and last.detail["steps_kept"] == ["stop_subscription"]
    assert last.detail["from_status"] == "requires_reconciliation"


def test_list_get_and_filters(db_session) -> None:
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session)
    seed_toku(db_session)
    a = cr.create_request(db_session, jefa, params(), now=NOW)
    cr.create_request(db_session, jefa, params("toku", "sub_tk1"), now=NOW)
    rows, total = cr.list_requests(db_session, cr.RequestFilters(channel="toku"))
    assert total == 1 and rows[0].channel == "toku"
    rows, total = cr.list_requests(db_session, cr.RequestFilters(statuses=["approved"], requested_by_user_id=jefa.id))
    assert total == 2
    assert cr.get_request(db_session, a.id).id == a.id
    with pytest.raises(cr.RequestNotFoundError):
        cr.get_request(db_session, uuid.uuid4())
    assert db_session.scalar(select(SubscriptionCancellationRequestEvent.id).limit(1)) is not None
    assert datetime.now(UTC) is not None
