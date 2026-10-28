# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""Paso 4: API REST /api/v1/billing (solicitudes de cambio de cobro y politica), SOLO con fakes del proveedor.

Autenticacion real (JWT + cookie + CSRF) con usuarios y roles reales dentro de una transaccion revertida.
Cada test cita los escenarios del doc docs/designs/facturacion-gestionada-escenarios.md que cubre.
"""

from pathlib import Path

import httpx
import pytest
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    CALLS,
    STATE,
    SUB,
    api_error,
    client_for,
    db_session,
    deleted,
    env,
    make_user,
    names,
    roles_kit,
    seed_crm_calendar,
    seed_sub,
    set_policy,
)
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.main import app
from app.services import billing_apply as ba

BASE = "/api/v1/billing"
ROOT = Path(__file__).resolve().parent.parent
BODY = {"request_type": "change_amount", "platform": "virtualpos1", "subscription_external_id": SUB,
        "new_amount": 12000, "horizon_start_month": "2026-11"}


class World:
    def __init__(self, db):
        self.db = db
        kit = roles_kit(db)
        self.kit = kit
        self.admin1, self.admin2 = make_user(db, kit["admin"]), make_user(db, kit["admin"])
        self.requester, self.stranger = make_user(db, kit["solicitante"]), make_user(db, kit["solicitante"])
        self.executive, self.support = make_user(db, kit["ejecutivo"]), make_user(db, kit["soporte"])
        self.manager = make_user(db, kit["gestor"])
        seed_sub(db)
        self._clients: dict[str, tuple[TestClient, dict]] = {}

    def c(self, who: str) -> tuple[TestClient, dict]:
        if who not in self._clients:
            self._clients[who] = client_for(self.db, getattr(self, who))
        return self._clients[who]

    def post(self, who, path, json=None):
        client, h = self.c(who)
        return client.post(f"{BASE}{path}", json=json, headers=h)

    def get(self, who, path, **kw):
        client, _ = self.c(who)
        return client.get(f"{BASE}{path}", **kw)

    def put(self, who, path, json=None):
        client, h = self.c(who)
        return client.put(f"{BASE}{path}", json=json, headers=h)

    def create(self, who="requester", **over):
        r = self.post(who, "/changes", {**BODY, **over})
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def w(db_session):
    return World(db_session)


def no_plural_delete():
    assert "delete_plural" not in names()


# ----------------------------- rutas, permisos, CSRF, autenticacion -----------------------------


def test_openapi_lists_new_routes():
    """Las rutas nuevas estan registradas bajo /api/v1/billing (con su metodo)."""
    r = TestClient(app).get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    expected = {
        "/api/v1/billing/changes/preview": {"post"}, "/api/v1/billing/changes": {"get", "post"},
        "/api/v1/billing/changes/{request_id}": {"get"}, "/api/v1/billing/changes/{request_id}/events": {"get"},
        "/api/v1/billing/changes/{request_id}/approve": {"post"}, "/api/v1/billing/changes/{request_id}/reject": {"post"},
        "/api/v1/billing/changes/{request_id}/withdraw": {"post"}, "/api/v1/billing/changes/{request_id}/reopen": {"post"},
        "/api/v1/billing/changes/{request_id}/apply": {"post"},
        "/api/v1/billing/policy": {"get", "put"}, "/api/v1/billing/policy/audit": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths, path
        assert methods <= set(paths[path]), path
    assert not any("delete" in paths[p] for p in expected if p in paths)  # ninguna ruta DELETE


def test_executive_and_support_can_view_but_not_request_approve_or_manage(w):
    """AP-04, AP-05, AP-19, AP-22: ejecutivo/soporte solo ven; solicitar/aprobar/administrar -> 403."""
    created = w.create("admin1")
    rid = created["id"]
    for who in ("executive", "support"):
        assert w.get(who, "/changes").status_code == 200
        assert w.get(who, f"/changes/{rid}").status_code == 200
        assert w.get(who, f"/changes/{rid}/events").status_code == 200
        for path, body in [
            ("/changes/preview", BODY), ("/changes", BODY), (f"/changes/{rid}/approve", {}),
            (f"/changes/{rid}/reject", {"comment": "x"}), (f"/changes/{rid}/withdraw", {}),
            (f"/changes/{rid}/reopen", {"comment": "x"}), (f"/changes/{rid}/apply", {}),
        ]:
            assert w.post(who, path, body).status_code == 403, (who, path)
        assert w.get(who, "/policy").status_code == 403
        assert w.get(who, "/policy/audit").status_code == 403
        assert w.put(who, "/policy", {"request_expiry_days": 9}).status_code == 403
    assert "create_charge" not in names()
    no_plural_delete()


def test_missing_csrf_is_403_and_missing_session_is_401(w):
    """AP-19: sin CSRF -> 403; sin sesion -> 401, en cada ruta de escritura (y 401 tambien en lecturas)."""
    rid = w.create("admin1")["id"]
    client, _headers = w.c("admin1")
    writes = [
        ("post", "/changes/preview", BODY), ("post", "/changes", BODY), ("post", f"/changes/{rid}/approve", {}),
        ("post", f"/changes/{rid}/reject", {"comment": "x"}), ("post", f"/changes/{rid}/withdraw", {}),
        ("post", f"/changes/{rid}/reopen", {"comment": "x"}), ("post", f"/changes/{rid}/apply", {}),
        ("put", "/policy", {"request_expiry_days": 9}),
    ]
    anonymous = TestClient(app)
    for method, path, body in writes:
        assert getattr(client, method)(f"{BASE}{path}", json=body).status_code == 403, path  # sin cabecera CSRF
        assert getattr(anonymous, method)(f"{BASE}{path}", json=body).status_code == 401, path
    for path in ("/changes", f"/changes/{rid}", f"/changes/{rid}/events", "/policy", "/policy/audit"):
        assert anonymous.get(f"{BASE}{path}").status_code == 401, path
    assert "create_charge" not in names()


# ----------------------------- vista previa y creacion -----------------------------


def test_preview_is_read_only_and_reports_rules(w):
    """AP-29: la vista previa calcula el plan sin guardar nada ni escribir en el proveedor."""
    r = w.post("requester", "/changes/preview", BODY)
    assert r.status_code == 200
    out = r.json()
    assert out["summary"]["creates"] == 12 and out["summary"]["cancels"] == 12 and out["approvals_required"] == 1
    assert out["would_self_approve"] is False and out["open_request"] is None
    assert w.post("admin1", "/changes/preview", BODY).json()["would_self_approve"] is True
    assert w.get("admin1", "/changes").json()["total"] == 0
    assert set(names()) == {"list_charges"}
    w.create("requester")
    assert w.post("requester", "/changes/preview", BODY).json()["open_request"]["status"] == "pendiente"


@pytest.mark.parametrize("kind", ["change_amount", "change_date", "renew_calendar", "one_off_charge"])
def test_create_each_request_type_returns_201(w, kind):
    """AP-12, RA-01, RA-16, JB-30, RA-29: los 4 tipos se crean (pendiente), con el actor del token y evento creada."""
    bodies = {
        "change_amount": BODY,
        "change_date": {**BODY, "request_type": "change_date", "new_amount": None, "new_charge_day": 20},
        "renew_calendar": {**BODY, "request_type": "renew_calendar", "new_amount": None, "horizon_start_month": None},
        "one_off_charge": {**BODY, "request_type": "one_off_charge", "new_amount": 5000, "new_charge_date": "2026-11-20",
                           "horizon_start_month": None, "task_ref": "T9"},
    }
    if kind == "renew_calendar":
        seed_crm_calendar(w.db)
    body = {k: v for k, v in bodies[kind].items() if v is not None}
    r = w.post("requester", "/changes", body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "pendiente" and out["request_type"] == kind
    assert out["requested_by_user_id"] == str(w.requester.id)
    assert out["events"][0]["event_type"] == "creada" and out["events"][0]["actor_user_id"] == str(w.requester.id)
    assert out["plan_preview"]["create"] and out["rules_snapshot"]["window_days"] == 31
    assert out["expires_at"] and out["approvals_required"] == 1
    assert set(names()) == {"list_charges"}  # solo lectura


def test_actor_cannot_be_forged_from_body(w):
    """El actor sale del token: un body con requested_by_user_id / actor_user_id / approved_by se rechaza (422)."""
    for forged in ("requested_by_user_id", "actor_user_id", "approved_by_user_id", "status"):
        r = w.post("requester", "/changes", {**BODY, forged: str(w.admin1.id)})
        assert r.status_code == 422, forged
    rid = w.create("requester")["id"]
    assert w.post("admin1", f"/changes/{rid}/approve", {"actor_user_id": str(w.admin2.id)}).status_code == 422
    out = w.post("admin1", f"/changes/{rid}/approve", {"comment": "ok"}).json()
    assert out["approved_by_user_id"] == str(w.admin1.id)
    assert out["events"][-1]["actor_user_id"] == str(w.admin1.id)


def test_create_errors_map_to_409_and_422(w):
    """AP-12 (409 abierta), noop (422 no_changes), errores del plan (422 plan_errors), campos (422), 404 suscripcion."""
    first = w.create("requester")
    dup = w.post("requester", "/changes", {**BODY, "new_amount": 13000})
    assert dup.status_code == 409
    detail = dup.json()["detail"]
    assert detail["code"] == "open_request_exists" and detail["open_request_id"] == first["id"]

    bad_plan = w.post("admin1", "/changes", {**BODY, "request_type": "one_off_charge", "new_amount": 5000,
                                              "new_charge_date": "2026-10-28", "horizon_start_month": None,
                                              "subscription_external_id": SUB})
    assert bad_plan.status_code == 409  # sigue la solicitud abierta
    w.post("requester", f"/changes/{first['id']}/withdraw")
    bad_plan = w.post("admin1", "/changes", {**BODY, "request_type": "one_off_charge", "new_amount": 5000,
                                              "new_charge_date": "2026-10-28", "horizon_start_month": None})
    assert bad_plan.status_code == 422 and bad_plan.json()["detail"]["code"] == "plan_errors"
    assert bad_plan.json()["detail"]["errors"][0]["code"] == "past_charge_date"
    assert w.post("admin1", "/changes", {**BODY, "new_amount": None}).status_code == 422
    assert w.post("admin1", "/changes", {**BODY, "new_amount": 0}).status_code == 422
    assert w.post("admin1", "/changes", {**BODY, "platform": "otra"}).status_code == 422
    unknown = w.post("admin1", "/changes", {**BODY, "subscription_external_id": "no-existe"})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "subscription_not_found"

    STATE["charges"] = [dict(c, amount=12000) if c["status"] == "pendiente" else c for c in STATE["charges"]]
    noop = w.post("admin1", "/changes", BODY)
    assert noop.status_code == 422 and noop.json()["detail"]["code"] == "no_changes"


def test_inactive_subscription_is_422(w):
    w.db.execute(text("UPDATE subscriptions SET status='CANCELADA' WHERE external_id=:s"), {"s": SUB})
    r = w.post("requester", "/changes", BODY)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "subscription_not_active"


def test_self_approval_event_over_api(w):
    """AP-02: admin solicitante -> aprobada al crear, self_approved=true, evento autoaprobada con su usuario."""
    out = w.create("admin1")
    assert out["status"] == "aprobada" and out["self_approved"] is True and out["approved_by_user_id"] == str(w.admin1.id)
    assert [e["event_type"] for e in out["events"]] == ["creada", "autoaprobada"]
    assert out["events"][1]["actor"] == w.admin1.username


# ----------------------------- aprobar / rechazar / retirar -----------------------------


def test_manual_approval_by_other_admin_and_double_approve_conflict(w):
    """AP-06, AP-14, AP-16: otro admin aprueba; la segunda aprobacion recibe 409 con el estado actual."""
    rid = w.create("requester")["id"]
    ok = w.post("admin2", f"/changes/{rid}/approve", {"comment": "visto bueno"})
    assert ok.status_code == 200 and ok.json()["status"] == "aprobada" and ok.json()["self_approved"] is False
    assert [e["event_type"] for e in ok.json()["events"]] == ["creada", "aprobada"]
    again = w.post("admin1", f"/changes/{rid}/approve", {})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "invalid_request_state" and again.json()["detail"]["current_status"] == "aprobada"
    assert w.get("admin1", f"/changes/{rid}/events").json()["total"] == 2


def test_non_listed_user_with_permission_gets_403_not_approver(w):
    """AP-04, AP-25: tener el permiso no basta; hay que ser aprobador segun la politica vigente."""
    other = make_user(w.db, w.kit["aprobador"])
    w.db.commit()
    rid = w.create("requester")["id"]
    client, h = client_for(w.db, other)
    r = client.post(f"{BASE}/changes/{rid}/approve", json={}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_approver"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "pendiente"
    set_policy(w.db, approver_user_ids=[str(other.id)])
    assert client.post(f"{BASE}/changes/{rid}/approve", json={}, headers=h).status_code == 200


def test_self_approval_disabled_blocks_over_api(w):
    """AP-01, AP-26: autoaprobacion apagada -> el admin solicitante queda pendiente y no puede aprobar lo propio (403)."""
    set_policy(w.db, self_approval_enabled=False)
    created = w.create("admin1")
    assert created["status"] == "pendiente"
    r = w.post("admin1", f"/changes/{created['id']}/approve", {})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_approval_not_allowed"
    assert w.post("admin2", f"/changes/{created['id']}/approve", {}).json()["status"] == "aprobada"


def test_dual_approval_over_api_same_user_twice_does_not_count(w):
    """AP-07, AP-36: doble aprobacion ON: variacion > 50 % exige dos aprobadores distintos; el mismo usuario no suma."""
    set_policy(w.db, dual_approval_enabled=True)
    created = w.create("admin1", new_amount=15000)
    rid = created["id"]
    assert created["approvals_required"] == 2 and created["approvals_count"] == 1 and created["status"] == "pendiente"
    again = w.post("admin1", f"/changes/{rid}/approve", {})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate_approver"
    done = w.post("admin2", f"/changes/{rid}/approve", {})
    assert done.status_code == 200 and done.json()["status"] == "aprobada" and done.json()["approvals_count"] == 2


@pytest.mark.parametrize("payload", [None, {}, {"comment": ""}, {"comment": "   "}])
def test_reject_without_comment_is_422(w, payload):
    """AP-11: rechazar sin comentario (ausente, vacio o en blanco) -> 422; la solicitud sigue pendiente."""
    rid = w.create("requester")["id"]
    assert w.post("admin1", f"/changes/{rid}/reject", payload).status_code == 422
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "pendiente"


def test_reject_with_comment_and_visible_to_viewers(w):
    rid = w.create("requester")["id"]
    r = w.post("admin1", f"/changes/{rid}/reject", {"comment": "monto no corresponde"})
    assert r.status_code == 200 and r.json()["status"] == "rechazada" and r.json()["decision_comment"] == "monto no corresponde"
    assert w.get("executive", f"/changes/{rid}").json()["decision_comment"] == "monto no corresponde"
    assert w.post("admin1", f"/changes/{rid}/reject", {"comment": "otra vez"}).status_code == 409


def test_withdraw_only_requester_or_admin(w):
    """AP-33: un tercero con permiso de solicitar -> 403; el solicitante o un admin retiran."""
    rid = w.create("requester")["id"]
    denied = w.post("stranger", f"/changes/{rid}/withdraw", {})
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "forbidden"
    assert w.post("requester", f"/changes/{rid}/withdraw", {"comment": "ya no"}).json()["status"] == "retirada"
    rid2 = w.create("requester", new_amount=13000)["id"]
    assert w.post("admin2", f"/changes/{rid2}/withdraw").json()["status"] == "retirada"
    assert w.post("requester", f"/changes/{rid2}/withdraw").status_code == 409


# ----------------------------- aplicar -----------------------------


def test_apply_happy_path_over_api(w):
    """RA-01, AP-16, CO-16: crea, aprueba y aplica; 12 POST y luego 12 DELETE individuales; nunca el DELETE plural."""
    rid = w.create("admin1")["id"]
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ejecutada" and out["request_status"] == "ejecutada" and len(out["created"]) == 12
    assert len(out["cancelled"]) == 12 and out["plan_summary"]["creates"] == 12 and out["write_run_id"]
    assert len(deleted()) == 12 and all(d.startswith("auto-") for d in deleted())
    no_plural_delete()
    detail = w.get("executive", f"/changes/{rid}").json()
    assert detail["status"] == "ejecutada" and detail["executed_at"]
    assert [e["event_type"] for e in detail["events"]] == ["creada", "autoaprobada", "aplicando", "aplicada"]
    assert detail["events"][2]["actor_user_id"] == str(w.admin1.id)
    again = w.post("admin1", f"/changes/{rid}/apply", {})
    assert again.status_code == 200 and again.json()["already_applied"] is True


def test_apply_requires_approve_permission_and_policy_approver(w):
    """AP-04: sin permiso approve -> 403; con permiso pero fuera de la politica -> 403 not_approver. Nada se escribe."""
    rid = w.create("admin1")["id"]
    assert w.post("requester", f"/changes/{rid}/apply", {}).status_code == 403
    other = make_user(w.db, w.kit["aprobador"])
    w.db.commit()
    client, h = client_for(w.db, other)
    r = client.post(f"{BASE}/changes/{rid}/apply", json={}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_approver"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"
    assert "create_charge" not in names()


def test_apply_pending_request_is_409_with_state(w):
    rid = w.create("requester")["id"]
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 409 and r.json()["detail"]["current_status"] == "pendiente"
    assert "create_charge" not in names()


def test_apply_drift_then_accept_drift(w):
    """AP-30: si el proveedor cambio tras aprobar -> 409 plan_drift (nada escrito); con accept_drift=true se ejecuta."""
    rid = w.create("admin1")["id"]
    next(c for c in STATE["charges"] if c["id"] == "auto-02")["status"] = "pagado"  # el mes 2026-12 ya se cobro
    CALLS.clear()
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "plan_drift" and d["retry_with"] == {"accept_drift": True}
    assert d["diff"]["create_removed"] and d["new_preview"]["create"] and "accept_drift" in d["message"]
    assert "create_charge" not in names() and "delete_charge" not in names()
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"
    ok = w.post("admin1", f"/changes/{rid}/apply", {"accept_drift": True})
    assert ok.status_code == 200 and ok.json()["status"] == "ejecutada" and ok.json()["drift_accepted"]
    assert len(ok.json()["created"]) == 11
    no_plural_delete()


def test_apply_with_busy_subscription_lock_is_409(w):
    """Lock de suscripcion ocupado -> 409 subscription_busy; la solicitud sigue aprobada y no se escribe nada."""
    rid = w.create("admin1")["id"]
    with ba.subscription_lock(w.db, "virtualpos1", SUB):
        r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "subscription_busy"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"
    assert "create_charge" not in names()


def test_apply_with_writes_disabled_is_403(w, monkeypatch):
    """JB-19: VIRTUALPOS_WRITES_ENABLED apagada -> 403 writes_disabled; sigue aprobada, sin llamadas de escritura."""
    rid = w.create("admin1")["id"]
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "writes_disabled"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"
    assert "create_charge" not in names()


def test_apply_with_fixed_plan_flag_off_is_422(w, monkeypatch):
    """JB-19: bandera de plan fijo apagada y plan MONTO_FIJO -> 422 fixed_plan_charge_blocked; sigue aprobada."""
    rid = w.create("admin1")["id"]
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", False)
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "fixed_plan_charge_blocked"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"
    assert "create_charge" not in names()


def test_apply_failure_is_502_fallida_then_reopen_and_retry(w):
    """RA-07: fallo con compensacion limpia -> 502 y 'fallida'; reabrir exige comentario; luego se reaplica a mano."""
    rid = w.create("admin1")["id"]
    STATE["create_fail"] = {"at": 5}
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 502
    d = r.json()["detail"]
    assert d["code"] == "apply_failed" and d["request_status"] == "fallida" and d["compensated"] == 4
    assert "E-113" not in r.text and "nok" not in r.text.lower()
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "fallida"
    assert sorted(deleted()) == ["new-1", "new-2", "new-3", "new-4"]
    # no hay reintento automatico: reabrir exige comentario y solo entonces vuelve a 'aprobada'
    assert w.post("admin1", f"/changes/{rid}/reopen", {}).status_code == 422
    assert w.post("admin1", f"/changes/{rid}/reopen", {"comment": " "}).status_code == 422
    reopened = w.post("admin1", f"/changes/{rid}/reopen", {"comment": "proveedor estable de nuevo"})
    assert reopened.status_code == 200 and reopened.json()["status"] == "aprobada"
    last = reopened.json()["events"][-1]
    assert last["event_type"] == "reintentada" and last["detail"]["action"] == "reabierta"
    assert last["actor_user_id"] == str(w.admin1.id)
    assert w.post("admin1", f"/changes/{rid}/apply", {}).json()["status"] == "ejecutada"
    no_plural_delete()


def test_apply_reconciliation_is_503_and_reopen_by_policy_manager(w):
    """RA-09/RA-10: no se pudo cancelar un antiguo -> 503 y 'requiere_conciliacion'; reabre quien tiene billing_policy.manage."""
    rid = w.create("admin1")["id"]
    STATE["delete_fail"] = {"auto-03": 10}
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "reconciliation_required" and r.json()["detail"]["request_status"] == "requiere_conciliacion"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "requiere_conciliacion"
    no_plural_delete()
    assert w.post("executive", f"/changes/{rid}/reopen", {"comment": "x"}).status_code == 403
    assert w.post("requester", f"/changes/{rid}/reopen", {"comment": "x"}).status_code == 403
    done = w.post("manager", f"/changes/{rid}/reopen", {"comment": "conciliado a mano"})
    assert done.status_code == 200 and done.json()["status"] == "aprobada"


def test_reopen_only_from_failed_states_over_api(w):
    rid = w.create("admin1")["id"]
    r = w.post("admin1", f"/changes/{rid}/reopen", {"comment": "x"})
    assert r.status_code == 409 and r.json()["detail"]["current_status"] == "aprobada"


# ----------------------------- errores del proveedor / PII -----------------------------


def test_provider_errors_are_generic_and_do_not_leak(w):
    """Un error del proveedor (payload con PII/credenciales en el mensaje) se traduce a 502 generico."""
    secret = "SECRET-TOKEN-123 juan.perez@example.com 12.345.678-5"
    STATE["list_error"] = api_error("E-999")
    STATE["list_error"].message = secret
    STATE["list_error"].args = (secret,)
    for path in ("/changes", "/changes/preview"):
        r = w.post("requester", path, BODY)
        assert r.status_code == 502, path
        text = r.text
        assert r.json()["detail"]["code"] == "provider_error"
        for leaked in ("SECRET-TOKEN-123", "juan.perez@example.com", "12.345.678-5", "nok"):
            assert leaked not in text
    STATE["list_error"] = httpx.ReadTimeout("timeout con detalle interno")
    r = w.post("requester", "/changes", BODY)
    assert r.status_code == 502 and "detalle interno" not in r.text
    assert w.get("admin1", "/changes").json()["total"] == 0


def test_not_found_and_invalid_ids(w):
    unknown = "00000000-0000-0000-0000-000000000099"
    for who, method, path in [("admin1", "get", f"/changes/{unknown}"), ("admin1", "get", f"/changes/{unknown}/events"),
                              ("admin1", "post", f"/changes/{unknown}/approve"), ("admin1", "post", f"/changes/{unknown}/apply")]:
        r = getattr(w, method)(who, path) if method == "get" else w.post(who, path, {})
        assert r.status_code == 404 and r.json()["detail"]["code"] == "request_not_found", path
    assert w.get("admin1", "/changes/no-es-uuid").status_code == 422


# ----------------------------- politica -----------------------------


def test_policy_get_put_and_audit(w):
    """AP-20, AP-35: lectura de la politica, edicion y auditoria (quien, cuando, antes, despues, motivo)."""
    got = w.get("admin1", "/policy")
    assert got.status_code == 200
    p = got.json()
    assert p["approver_roles"] == ["admin"] and p["self_approval_enabled"] is True and p["dual_approval_enabled"] is False
    assert (p["renewal_threshold_days"], p["request_expiry_days"], p["horizon_months"], p["window_days"]) == (60, 7, 12, 31)
    put = w.put("admin1", "/policy", {"request_expiry_days": 10, "dual_threshold_variation_pct": 40.5, "reason": "revision mensual"})
    assert put.status_code == 200 and put.json()["request_expiry_days"] == 10 and put.json()["dual_threshold_variation_pct"] == 40.5
    audit = w.get("manager", "/policy/audit").json()
    assert audit["total"] == 1
    a = audit["items"][0]
    assert a["changed_by"] == w.admin1.username and a["reason"] == "revision mensual" and a["changed_at"]
    assert (a["before_values"]["request_expiry_days"], a["after_values"]["request_expiry_days"]) == (7, 10)
    assert w.get("manager", "/policy").status_code == 200 and w.put("manager", "/policy", {"window_days": 20}).status_code == 200
    assert w.get("admin1", "/policy/audit").json()["total"] == 2


def test_policy_ap23_and_ap24_and_validation(w):
    """AP-23 (sin aprobador -> 422), AP-24 (sin otro aprobador -> 422), rangos y campos desconocidos."""
    r = w.put("admin1", "/policy", {"approver_roles": []})
    assert r.status_code == 422 and r.json()["detail"]["policy_code"] == "no_approvers"
    set_policy(w.db, approver_roles=[], approver_user_ids=[str(w.admin1.id)])
    r = w.put("admin1", "/policy", {"self_approval_enabled": False})
    assert r.status_code == 422 and r.json()["detail"]["policy_code"] == "no_other_approver"
    ok = w.put("admin1", "/policy", {"approver_user_ids": [str(w.admin1.id), str(w.admin2.id)], "self_approval_enabled": False})
    assert ok.status_code == 200 and ok.json()["self_approval_enabled"] is False
    for bad in ({}, {"window_days": 0}, {"horizon_months": 61}, {"request_expiry_days": 0}, {"renewal_threshold_days": 0},
                {"dual_threshold_subscriptions": 0}, {"dual_threshold_variation_pct": -1}, {"inventado": 1},
                {"window_days": None}, {"approver_user_ids": ["no-uuid"]},
                {"approver_user_ids": ["00000000-0000-0000-0000-000000000001"]}, {"approver_roles": ["rol-inexistente"]}):
        assert w.put("admin1", "/policy", bad).status_code == 422, bad
    assert w.get("admin1", "/policy/audit").json()["total"] == 1  # solo el cambio valido quedo auditado


def test_policy_change_keeps_pending_snapshot_over_api(w):
    """AP-27: cambiar la politica no reescribe el snapshot ni las aprobaciones requeridas de una pendiente."""
    created = w.create("requester")
    assert w.put("admin1", "/policy", {"dual_approval_enabled": True, "request_expiry_days": 30}).status_code == 200
    detail = w.get("admin1", f"/changes/{created['id']}").json()
    assert detail["rules_snapshot"] == created["rules_snapshot"] and detail["approvals_required"] == 1
    assert detail["expires_at"] == created["expires_at"]
    assert w.post("admin2", f"/changes/{created['id']}/approve", {}).json()["status"] == "aprobada"


# ----------------------------- consulta -----------------------------


def test_list_filters_and_pagination_over_api(w):
    """AP-28, AP-32: bandeja e historial con filtros (estado, plataforma, suscripcion, tipo, solicitante, fechas, paginacion)."""
    first = w.create("requester")
    w.post("requester", f"/changes/{first['id']}/withdraw")
    second = w.create("admin1", request_type="one_off_charge", new_amount=5000, new_charge_date="2026-11-20",
                      horizon_start_month=None)
    items = w.get("executive", "/changes").json()
    assert items["total"] == 2 and "plan_preview" not in items["items"][0]

    def ids(query):
        return {i["id"] for i in w.get("executive", f"/changes?{query}").json()["items"]}

    assert ids("status=retirada") == {first["id"]}
    assert ids("status=retirada&status=aprobada") == {first["id"], second["id"]}
    assert ids("request_type=one_off_charge") == {second["id"]}
    assert ids(f"requested_by={w.requester.id}") == {first["id"]}
    assert ids(f"subscription_id={SUB}&platform=virtualpos1") == {first["id"], second["id"]}
    assert ids("platform=virtualpos2") == set() and ids("subscription_id=otra") == set()
    assert ids("date_from=2000-01-01&date_to=2100-01-01") == {first["id"], second["id"]}
    assert ids("date_from=2100-01-01") == set()
    page = w.get("executive", "/changes?limit=1&offset=1").json()
    assert len(page["items"]) == 1 and page["total"] == 2
    assert w.get("executive", "/changes?status=inventado").status_code == 422
    assert w.get("executive", "/changes?limit=0").status_code == 422


def test_events_endpoint_matches_detail(w):
    rid = w.create("admin1")["id"]
    ev = w.get("executive", f"/changes/{rid}/events").json()
    detail = w.get("executive", f"/changes/{rid}").json()
    assert [e["event_type"] for e in ev["items"]] == [e["event_type"] for e in detail["events"]] == ["creada", "autoaprobada"]


# ----------------------------- guardas -----------------------------


def test_expiry_job_is_not_registered_in_scheduler():
    """El paso 6 registra el scheduler: aqui `expire_pending_requests` queda sin registrar."""
    for rel in ("app/services/scheduler.py", "app/api/v1/routes/scheduler.py"):
        path = ROOT / rel
        if path.exists():
            assert "expire_pending_requests" not in path.read_text(encoding="utf-8"), rel
    for path in (ROOT / "app").rglob("*.py"):
        if path.name in ("billing_requests.py",):
            continue
        assert "expire_pending_requests" not in path.read_text(encoding="utf-8"), path
