# ruff: noqa: F811  (fixtures importadas: db_session/env/providers)
"""MGT-07/16: API `/api/v1/cancellations` con autenticacion real (JWT + cookie + CSRF) y proveedores falsos.

Roles (D12): jefatura solicita y aprueba; admin todo; ejecutivo, soporte y coordinador solo leen. Errores con
`detail={code,message}` sin eco de valores. Ademas: los botones directos de baja de `/writes/*` quedan para `admin`.
"""

from billing_requests_support import (  # noqa: F401 - env (autouse): JWT secret y banderas
    client_for,
    env,
)
from cancellation_support import (
    db_session,  # noqa: F401 - fixture
    make_roles,
    make_user,
    seed_payku,
    seed_tch,
    seed_toku,
    seed_vp,
)
from test_cancellation_apply import (  # noqa: F401 - fixture + fakes
    REFRESH,
    FakeToku,
    providers,
)

from app.models.cancellation import SubscriptionCancellationRequest

BASE = "/api/v1/cancellations"
BODY = {"channel": "virtualpos1", "subscription_external_id": "sub-c1", "reason_code": "member_request",
        "reason_comment": "El socio pidio la baja"}


def _client(db, role_name):
    roles = make_roles(db)
    user = make_user(db, roles[role_name])
    client, headers = client_for(db, user)
    return user, client, headers


# ----------------------------- roles -----------------------------


def test_jefatura_requests_and_approves_in_one_step_self_approval_is_audited(db_session) -> None:
    seed_vp(db_session)
    user, client, h = _client(db_session, "jefatura")
    r = client.post(BASE, json=BODY, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "approved" and body["self_approved"] is True
    assert body["requested_by_user_id"] == str(user.id) and body["approved_by_user_id"] == str(user.id)
    assert body["cascade_preview"]["pending_charges"] == 2
    assert [e["event_type"] for e in body["events"]] == ["created", "self_approved"]
    assert body["reason_code"] == "member_request" and body["steps"] == []


def test_admin_can_do_everything(db_session) -> None:
    seed_vp(db_session)
    _, client, h = _client(db_session, "admin")
    assert client.post(f"{BASE}/preview", json=BODY, headers=h).status_code == 200
    assert client.post(BASE, json=BODY, headers=h).status_code == 201
    assert client.get(BASE).status_code == 200


def test_executive_support_and_coordinator_only_read(db_session) -> None:
    seed_vp(db_session)
    _, jefa_client, jh = _client(db_session, "jefatura")
    req_id = jefa_client.post(BASE, json=BODY, headers=jh).json()["id"]
    for role in ("ejecutivo", "soporte", "coordinador"):
        _, client, h = _client(db_session, role)
        assert client.get(BASE).status_code == 200, role
        assert client.get(f"{BASE}/{req_id}").status_code == 200, role
        assert client.get(f"{BASE}/{req_id}/events").status_code == 200, role
        assert client.post(BASE, json=BODY, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/preview", json=BODY, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{req_id}/approve", json={}, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{req_id}/reject", json={"comment": "x"}, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{req_id}/apply", json={}, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{req_id}/reopen", json={"comment": "x"}, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{req_id}/withdraw", json={}, headers=h).status_code == 403, role


def test_requires_authentication_and_csrf(db_session) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    seed_vp(db_session)
    assert TestClient(app, base_url="https://testserver").get(BASE).status_code == 401
    _, client, h = _client(db_session, "jefatura")
    assert h
    assert client.post(BASE, json=BODY).status_code == 403  # sin cabecera CSRF
    assert client.post(BASE, json=BODY, headers={"X-CSRF-Token": "otro"}).status_code == 403


# ----------------------------- validacion y errores -----------------------------


def test_reason_is_mandatory_and_errors_do_not_echo_values(db_session) -> None:
    seed_vp(db_session)
    _, client, h = _client(db_session, "jefatura")
    no_comment = {k: v for k, v in BODY.items() if k != "reason_comment"}
    r = client.post(BASE, json=no_comment, headers=h)
    assert r.status_code == 422
    r = client.post(BASE, json={**BODY, "reason_comment": "   "}, headers=h)
    assert r.status_code == 422
    secret = "VALOR-SECRETO-123"
    r = client.post(BASE, json={**BODY, "reason_code": secret}, headers=h)
    assert r.status_code == 422 and secret not in r.text
    r = client.post(BASE, json={**BODY, "requested_by_user_id": secret}, headers=h)  # el actor jamas viene del cuerpo
    assert r.status_code == 422 and secret not in r.text
    assert client.get(BASE).json()["total"] == 0


def test_domain_errors_are_code_message_without_echo(db_session) -> None:
    _, client, h = _client(db_session, "jefatura")
    r = client.post(BASE, json={**BODY, "subscription_external_id": "no-existe-zzz"}, headers=h)
    assert r.status_code == 404
    assert set(r.json()["detail"]) >= {"code", "message"} and r.json()["detail"]["code"] == "subscription_not_found"
    assert "no-existe-zzz" not in r.text
    seed_vp(db_session, "sub-baja", status="CANCELADA")
    r = client.post(BASE, json={**BODY, "subscription_external_id": "sub-baja"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "subscription_not_active"
    seed_payku(db_session)
    r = client.post(BASE, json={"channel": "payku", "subscription_external_id": "sus_pk1",
                                "reason_code": "member_request", "reason_comment": "x"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "irreversibility_confirmation_required"


def test_open_request_conflict_returns_409_with_existing_id(db_session) -> None:
    seed_vp(db_session)
    _, client, h = _client(db_session, "jefatura")
    first = client.post(BASE, json=BODY, headers=h).json()
    r = client.post(BASE, json=BODY, headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "open_request_exists" and detail["open_request_id"] == first["id"]


# ----------------------------- ciclo de vida -----------------------------


def test_approve_reject_withdraw_flow_with_separate_requester(db_session) -> None:
    seed_vp(db_session, "sub-a")
    seed_vp(db_session, "sub-b")
    seed_vp(db_session, "sub-c")
    _, req_client, rh = _client(db_session, "solicitante")
    _, boss_client, bh = _client(db_session, "jefatura")
    a, b, c = (req_client.post(BASE, json={**BODY, "subscription_external_id": s}, headers=rh).json()["id"]
               for s in ("sub-a", "sub-b", "sub-c"))
    assert req_client.get(f"{BASE}/{a}").json()["status"] == "pending"
    assert req_client.post(f"{BASE}/{a}/approve", json={}, headers=rh).status_code == 403  # no aprueba su propia baja
    ok = boss_client.post(f"{BASE}/{a}/approve", json={"comment": "ok"}, headers=bh)
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["self_approved"] is False
    assert boss_client.post(f"{BASE}/{a}/approve", json={}, headers=bh).status_code == 409  # ya no esta pendiente
    assert boss_client.post(f"{BASE}/{b}/reject", json={"comment": ""}, headers=bh).status_code == 422
    rej = boss_client.post(f"{BASE}/{b}/reject", json={"comment": "Sin respaldo"}, headers=bh)
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert boss_client.post(f"{BASE}/{c}/withdraw", json={}, headers=bh).status_code == 403  # ajena y no admin
    wd = req_client.post(f"{BASE}/{c}/withdraw", json={}, headers=rh)
    assert wd.status_code == 200 and wd.json()["status"] == "withdrawn"
    listing = boss_client.get(BASE, params={"status": ["approved", "rejected"]}).json()
    assert listing["total"] == 2
    assert boss_client.get(BASE, params={"channel": "toku"}).json()["total"] == 0
    events = boss_client.get(f"{BASE}/{a}/events").json()
    assert [e["event_type"] for e in events["items"]] == ["created", "approved"]
    assert boss_client.get(f"{BASE}/00000000-0000-0000-0000-000000000000").status_code == 404


def test_apply_dry_run_then_real_apply_toku_and_idempotent(db_session, providers) -> None:
    seed_toku(db_session)
    FakeToku.invoices = [{"id": "in_a", "in_progress": False}]
    _, client, h = _client(db_session, "jefatura")
    req_id = client.post(BASE, json={"channel": "toku", "subscription_external_id": "sub_tk1",
                                     "reason_code": "payment_failure", "reason_comment": "3 cuotas impagas"},
                         headers=h).json()["id"]
    dry = client.post(f"{BASE}/{req_id}/apply", json={"dry_run": True}, headers=h)
    assert dry.status_code == 200 and dry.json()["status"] == "dry_run" and dry.json()["plan"]["blockers"] == []
    assert client.get(f"{BASE}/{req_id}").json()["status"] == "approved"
    done = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed" and done.json()["request_status"] == "completed"
    assert [s["step"] for s in done.json()["steps"]] == ["stop_subscription", "cancel_pending_charges", "payment_method"]
    again = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert again.status_code == 200 and again.json()["already_applied"] is True
    assert [c for c in FakeToku.calls if c[0] == "status"] == [("status", "PAUSED")]  # una sola pausa


def test_apply_denied_by_in_progress_invoice_is_409_fixed_code(db_session, providers) -> None:
    seed_toku(db_session)
    FakeToku.invoices = [{"id": "in_busy", "in_progress": True}]
    _, client, h = _client(db_session, "jefatura")
    req_id = client.post(BASE, json={"channel": "toku", "subscription_external_id": "sub_tk1",
                                     "reason_code": "other", "reason_comment": "x"}, headers=h).json()["id"]
    r = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INVOICE_IN_PROGRESS"
    assert r.json()["detail"]["request_status"] == "approved"
    assert not [c for c in FakeToku.calls if c[0] in ("status", "void", "delete")]


def test_apply_failure_midway_503_then_reopen_and_resume(db_session, providers) -> None:
    seed_toku(db_session)
    FakeToku.invoices = [{"id": "in_a", "in_progress": False}, {"id": "in_b", "in_progress": False}]
    FakeToku.void_fail = {"in_b"}
    _, client, h = _client(db_session, "jefatura")
    req_id = client.post(BASE, json={"channel": "toku", "subscription_external_id": "sub_tk1",
                                     "reason_code": "other", "reason_comment": "x"}, headers=h).json()["id"]
    r = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "reconciliation_required" and detail["request_status"] == "requires_reconciliation"
    assert detail["step_code"] == "INVOICE_VOID_FAILED" and "texto-libre" not in r.text
    shown = client.get(f"{BASE}/{req_id}").json()
    assert shown["requires_reconciliation"] is True and shown["steps"][0]["status"] == "done"
    assert client.post(f"{BASE}/{req_id}/reopen", json={"comment": ""}, headers=h).status_code == 422
    FakeToku.void_fail = set()
    assert client.post(f"{BASE}/{req_id}/reopen", json={"comment": "Reintento"}, headers=h).status_code == 200
    ok = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert ok.status_code == 200 and ok.json()["request_status"] == "completed"
    assert [c for c in FakeToku.calls if c[0] == "status"] == [("status", "PAUSED")]


def test_tch_apply_through_api_is_in_process(db_session, providers) -> None:
    file_number = seed_tch(db_session, 910200)
    _, client, h = _client(db_session, "jefatura")
    req_id = client.post(BASE, json={"channel": "tch", "subscription_external_id": file_number,
                                     "reason_code": "member_request", "reason_comment": "mandato"}, headers=h).json()["id"]
    r = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "pending_external"
    assert db_session.get(SubscriptionCancellationRequest, __import__("uuid").UUID(req_id)).status == "pending_external"


# ----------------------------- botones directos de /writes/* -----------------------------


def _writes_client(db, with_admin: bool, *codes):
    from billing_requests_support import make_role
    from billing_requests_support import make_user as make_plain_user

    roles = [make_role(db, "gestor-directo-t", set(codes))]
    if with_admin:
        roles.append(make_role(db, "admin", set(codes)))
    client, h = client_for(db, make_plain_user(db, *roles))
    return client, h


def test_direct_cancellation_buttons_are_restricted_to_admin(db_session) -> None:
    routes = [
        ("/api/v1/writes/virtualpos/subscriptions/x-no-existe", "virtualpos.subscriptions.cancel"),
        ("/api/v1/writes/toku/subscriptions/x-no-existe", "toku.subscriptions.manage"),
        ("/api/v1/writes/payku/subscriptions/x-no-existe", "payku.subscriptions.cancel"),
    ]
    for path, perm in routes:
        client, h = _writes_client(db_session, False, perm)  # tiene el permiso pero no es admin
        assert client.delete(path, headers=h).status_code == 403, path
        admin_client, ah = _writes_client(db_session, True, perm)
        assert admin_client.delete(path, headers=ah).status_code in (403, 404), path  # admin pasa: llega al servicio
    # jefatura con el permiso de baja directo tampoco: la via correcta es /cancellations
    client, h = _writes_client(db_session, False, "virtualpos.subscriptions.cancel")
    assert client.delete(routes[0][0], headers=h).status_code == 403


def test_admin_passes_the_direct_button_authorization(db_session, monkeypatch) -> None:
    """Con rol admin la autorizacion pasa: la ruta llega al servicio y responde 404 (suscripcion inexistente), no 403."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "toku_writes_enabled", True)
    monkeypatch.setattr(settings, "payku_writes_enabled", True)
    for path, perm in [
        ("/api/v1/writes/virtualpos/subscriptions/x-no-existe", "virtualpos.subscriptions.cancel"),
        ("/api/v1/writes/toku/subscriptions/x-no-existe", "toku.subscriptions.manage"),
        ("/api/v1/writes/payku/subscriptions/x-no-existe", "payku.subscriptions.cancel"),
    ]:
        client, h = _writes_client(db_session, True, perm)
        assert client.delete(path, headers=h).status_code == 404, path


def test_toku_status_cancelled_is_admin_only_but_pause_is_not(db_session, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "toku_writes_enabled", True)
    path = "/api/v1/writes/toku/subscriptions/x-no-existe/status"
    client, h = _writes_client(db_session, False, "toku.subscriptions.manage")
    assert client.post(path, json={"status": "CANCELLED"}, headers=h).status_code == 403
    assert client.post(path, json={"status": "PAUSED"}, headers=h).status_code == 404  # pausar sigue como antes
    admin_client, ah = _writes_client(db_session, True, "toku.subscriptions.manage")
    assert admin_client.post(path, json={"status": "CANCELLED"}, headers=ah).status_code == 404
