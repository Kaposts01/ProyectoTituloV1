# ruff: noqa: F811  (fixtures importadas: db_session/env/providers)
"""MGT-11/13/14: tareas manuales de suscripcion con estados, confirmacion auditada y verificacion externa.

- MGT-11 (d105): la baja de Toku/Payku/VirtualPOS CONSERVA el medio de pago y deja una tarea `payment_method_retained`.
- MGT-13 (d107): la baja TCH crea la tarea del mandato (responsable = solicitante); un ejecutivo CONFIRMA que la hizo
  (usuario y fecha), el CSV de bajas en tramite no lleva PAN ni datos de cuenta, y el Excel la verifica y la cierra.
- MGT-14 (d108): el cambio de monto de Payku es una tarea manual que la sincronizacion de Payku verifica y cierra.
Todo con proveedores falsos y datos sinteticos (sin datos personales reales); ninguna llamada de red.
"""

import csv
import importlib.util
import io
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from billing_requests_support import (  # noqa: F401 - env (autouse en sus tests): JWT secret y banderas
    client_for,
    env,
)
from cancellation_support import (
    approved_request,
    db_session,  # noqa: F401 - fixture
    make_roles,
    make_user,
    seed_tch,
    seed_toku,
)
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError
from test_cancellation_apply import (  # noqa: F401 - fixture + fakes
    FakeToku,
    _apply,
    _jefa,
    _reload,
    providers,
)

from app.db.session import engine
from app.models.auth import Permission
from app.models.crm import Subscription
from app.models.manual_task import SubscriptionManualTask, SubscriptionManualTaskEvent
from app.models.payku_channel import PaykuSubscription
from app.models.tch import TchSubscription
from app.services import cancellation_apply as ca
from app.services import manual_tasks as mt
from app.services import payku_sync
from app.services.billing_requests import PERM_REQUEST
from app.services.rbac import (
    MANUAL_TASK_ROLE_GRANTS,
    MANUAL_TASKS_CONFIRM,
    MANUAL_TASKS_VIEW,
    PERMISSIONS,
    executive_permission_codes,
)

BASE = "/api/v1/manual-tasks"
ROOT = Path(__file__).resolve().parent.parent
PAN_LIKE = re.compile(r"\d{13,19}")


def _roles(db):
    roles = make_roles(db)
    from billing_requests_support import make_role

    # make_roles no da los permisos nuevos a jefatura: se le agregan como en la migracion 0066
    roles["jefatura"] = make_role(db, "jefatura", {p.code for p in roles["jefatura"].permissions}
                                  | {MANUAL_TASKS_VIEW, MANUAL_TASKS_CONFIRM})
    roles["ejecutivo"] = make_role(db, "ejecutivo", executive_permission_codes())
    return roles


def _client(db, role_name):
    user = make_user(db, _roles(db)[role_name])
    client, headers = client_for(db, user)
    return user, client, headers


def _events(db, task_id):
    return [e.event_type for e in mt.get_events(db, task_id)]


def _tasks(db, task_type=None):
    q = select(SubscriptionManualTask)
    if task_type:
        q = q.where(SubscriptionManualTask.task_type == task_type)
    return list(db.scalars(q))


# ============================== permisos y migracion ==============================


def test_permissions_are_declared_and_executive_stays_read_only() -> None:
    assert MANUAL_TASKS_VIEW in PERMISSIONS and MANUAL_TASKS_CONFIRM in PERMISSIONS
    assert MANUAL_TASKS_VIEW in executive_permission_codes()  # lectura por sufijo `.view`
    assert MANUAL_TASKS_CONFIRM not in executive_permission_codes()  # el rol ejecutivo sigue siendo solo lectura (D12)
    assert MANUAL_TASK_ROLE_GRANTS["jefatura"] == {MANUAL_TASKS_VIEW, MANUAL_TASKS_CONFIRM}
    assert MANUAL_TASK_ROLE_GRANTS["coordinador"] == {MANUAL_TASKS_VIEW}


def _migration():
    path = ROOT / "alembic" / "versions" / "20261102_0066_manual_tasks_toku_amount.py"
    spec = importlib.util.spec_from_file_location("mig_0066", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0066_chain_and_grants_match_the_code() -> None:
    mig = _migration()
    assert mig.revision == "20261102_0066" and mig.down_revision == "20261102_0061"
    assert {r: set(c) for r, c in mig.ROLE_GRANTS.items()} == {r: set(c) for r, c in MANUAL_TASK_ROLE_GRANTS.items()}


def test_migration_0066_downgrade_and_upgrade_roundtrip_in_rolled_back_transaction() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    mig = _migration()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with Operations.context(MigrationContext.configure(connection)):
            mig.downgrade()
            names = set(inspect(connection).get_table_names())
            assert "subscription_manual_tasks" not in names and "subscription_manual_task_events" not in names
            assert connection.execute(text(
                "SELECT count(*) FROM permissions WHERE code LIKE 'subscriptions.manual_tasks.%'")).scalar() == 0
            mig.upgrade()
            assert "subscription_manual_tasks" in set(inspect(connection).get_table_names())
            assert connection.execute(text(
                "SELECT count(*) FROM permissions WHERE code LIKE 'subscriptions.manual_tasks.%'")).scalar() == 2
    finally:
        transaction.rollback()
        connection.close()


def test_events_are_immutable(db_session) -> None:
    jefa = _jefa(db_session)
    task = mt.ensure_task(db_session, mt.TASK_PAYMENT_METHOD, "toku", "sub_imm", actor=jefa.id)
    db_session.commit()
    event = db_session.scalar(select(SubscriptionManualTaskEvent).where(SubscriptionManualTaskEvent.task_id == task.id))
    event.detail = {"alterado": True}
    with pytest.raises(DBAPIError):
        db_session.commit()
    db_session.rollback()


# ============================== MGT-11: medio de pago conservado ==============================


def test_toku_cancellation_retains_payment_method_and_registers_manual_task(db_session, providers) -> None:
    seed_toku(db_session, "sub_tk1", unpaid=1)
    FakeToku.invoices = [{"id": "in_a", "in_progress": False}]
    jefa = _jefa(db_session)
    req = approved_request(db_session, jefa, "toku", "sub_tk1")
    _apply(db_session, req, jefa)
    req = _reload(db_session, req)
    step = next(s for s in req.steps if s["step"] == "payment_method")
    assert (step["status"], step["code"], step["task"]) == ("manual", "TOKU_PAYMENT_METHOD_RETAINED",
                                                            "payment_method_retained")
    assert not [c for c in FakeToku.calls if c[0] in ("delete", "delete_payment_method")]  # nunca se borra
    task = db_session.get(SubscriptionManualTask, uuid.UUID(step["manual_task_id"]))
    assert task.task_type == "payment_method_retained" and task.status == "pending"
    assert task.cancellation_request_id == req.id and task.assigned_to_user_id == jefa.id
    assert task.detail == {"code": "TOKU_PAYMENT_METHOD_RETAINED", "decision": "retained"}
    assert _events(db_session, task.id) == ["created"]
    assert req.cascade_preview["steps"][2]["reason"] == "retained"


def test_ensure_task_is_idempotent_while_open(db_session) -> None:
    jefa = _jefa(db_session)
    a = mt.ensure_task(db_session, mt.TASK_PAYMENT_METHOD, "payku", "sus_x", actor=jefa.id)
    b = mt.ensure_task(db_session, mt.TASK_PAYMENT_METHOD, "payku", "sus_x", actor=jefa.id)
    db_session.commit()
    assert a.id == b.id and len(_tasks(db_session, mt.TASK_PAYMENT_METHOD)) == 1


# ============================== MGT-13: TCH ==============================


def _tch_pending(db, file_number=910300):
    ficha = seed_tch(db, file_number)
    row = db.scalar(select(TchSubscription).where(TchSubscription.file_number == file_number))
    # datos sinteticos de pago que el CSV NUNCA debe exportar
    row.account_number = "4111111111111111"
    row.client_rut = "11111111-1"
    row.mandate_number = 77001
    row.bank_name = "BANCO SINTETICO"
    row.mandate_type = "PAT"
    row.amount = "5000"
    row.currency = "CLP"
    db.commit()
    jefa = _jefa(db)
    req = approved_request(db, jefa, "tch", ficha)
    _apply(db, req, jefa)
    req = _reload(db, req)
    task = next(t for t in _tasks(db, mt.TASK_TCH_MANDATE) if t.cancellation_request_id == req.id)
    return req, task, jefa


def test_tch_apply_creates_mandate_task_with_responsible(db_session, providers) -> None:
    req, task, jefa = _tch_pending(db_session)
    assert req.status == "pending_external"
    step = next(s for s in req.steps if s["step"] == "bank_mandate")
    assert step["manual_task_id"] == str(task.id) and step["code"] == "TCH_BANK_MANDATE_OUTSIDE_CRM"
    assert task.status == "pending" and task.assigned_to_user_id == jefa.id


def test_confirmation_is_audited_with_user_and_date_then_excel_verifies(db_session, providers) -> None:
    req, task, _jefa_user = _tch_pending(db_session)
    other, client, h = _client(db_session, "jefatura")  # otro ejecutivo distinto del responsable
    r = client.post(f"{BASE}/{task.id}/confirm", json={"comment": "Revocado en el banco"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed" and body["confirmed_by_user_id"] == str(other.id)
    assert body["confirmed_at"] and body["confirmation_comment"] == "Revocado en el banco"
    confirmed = [e for e in body["events"] if e["event_type"] == "confirmed"]
    assert len(confirmed) == 1 and confirmed[0]["actor_user_id"] == str(other.id)
    assert confirmed[0]["detail"]["by_assignee"] is False
    # confirmar dos veces: 409
    assert client.post(f"{BASE}/{task.id}/confirm", json={}, headers=h).status_code == 409

    row = db_session.scalar(select(TchSubscription).where(TchSubscription.file_number == 910300))
    row.deletion_date = "2026-11-05"
    db_session.commit()
    assert ca.close_tch_cancellations_from_report(db_session) == [req.id]
    db_session.expire_all()
    task = db_session.get(SubscriptionManualTask, task.id)
    assert task.status == "verified" and task.verification_source == "tch_report" and task.verified_at
    verified = mt.get_events(db_session, task.id)[-1]
    assert verified.event_type == "verified" and verified.actor_user_id is None
    assert verified.detail["confirmed_before"] is True


def test_excel_verifies_even_without_prior_confirmation(db_session, providers) -> None:
    _req, task, _ = _tch_pending(db_session, 910301)
    row = db_session.scalar(select(TchSubscription).where(TchSubscription.file_number == 910301))
    row.deletion_date = "2026-11-05"
    db_session.commit()
    ca.close_tch_cancellations_from_report(db_session)
    db_session.expire_all()
    task = db_session.get(SubscriptionManualTask, task.id)
    assert task.status == "verified" and mt.get_events(db_session, task.id)[-1].detail["confirmed_before"] is False


def test_tch_csv_never_contains_pan_or_card_data(db_session, providers) -> None:
    req, task, _ = _tch_pending(db_session, 910302)
    _, client, _h = _client(db_session, "jefatura")
    r = client.get(f"{BASE}/tch-export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    content = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(content)))
    assert tuple(rows[0]) == mt.TCH_EXPORT_COLUMNS
    assert len(rows) == 2 and rows[1][0] == str(req.id) and rows[1][1] == "910302" and rows[1][2] == "77001"
    # nada de PAN, numero de cuenta, RUT ni columnas de tarjeta
    assert "4111111111111111" not in content and "11111111-1" not in content
    assert not PAN_LIKE.search(content.replace(str(req.id), "").replace(str(task.id), ""))
    header = ",".join(rows[0]).lower()
    for forbidden in ("pan", "tarjeta", "card", "cuenta", "account", "rut", "cvv", "titular", "email", "telefono"):
        assert forbidden not in header, forbidden
    assert _events(db_session, task.id)[-1] == "exported"


def test_csv_cells_cannot_inject_formulas() -> None:
    assert mt._safe_cell("=HYPERLINK(1)").startswith("'")
    assert mt._safe_cell("a\nb") == "a b"


def test_rbac_view_confirm_and_export(db_session, providers) -> None:
    _req, task, _ = _tch_pending(db_session, 910303)
    for role in ("ejecutivo", "soporte", "coordinador"):
        _, client, h = _client(db_session, role)
        if role != "coordinador":  # el coordinador de make_roles solo ve bajas
            assert client.get(BASE).status_code == 200, role
            assert client.get(f"{BASE}/{task.id}").status_code == 200, role
        assert client.post(f"{BASE}/{task.id}/confirm", json={}, headers=h).status_code == 403, role
        assert client.post(f"{BASE}/{task.id}/dismiss", json={"comment": "x"}, headers=h).status_code == 403, role
        assert client.get(f"{BASE}/tch-export").status_code == 403, role
    _, client, h = _client(db_session, "jefatura")
    assert client.post(f"{BASE}/{task.id}/confirm", json={}).status_code == 403  # sin CSRF


def test_assign_and_dismiss_need_valid_input(db_session, providers) -> None:
    _req, task, _ = _tch_pending(db_session, 910304)
    other, client, h = _client(db_session, "jefatura")
    r = client.post(f"{BASE}/{task.id}/assign", json={"assigned_to_user_id": str(other.id)}, headers=h)
    assert r.status_code == 200 and r.json()["assigned_to_user_id"] == str(other.id)
    bogus = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"{BASE}/{task.id}/assign", json={"assigned_to_user_id": bogus}, headers=h).status_code == 422
    assert client.post(f"{BASE}/{task.id}/dismiss", json={"comment": "  "}, headers=h).status_code == 422
    r = client.post(f"{BASE}/{task.id}/dismiss", json={"comment": "Se decidió mantener el mandato"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert [e["event_type"] for e in r.json()["events"]][-2:] == ["assigned", "dismissed"]
    assert client.post(f"{BASE}/{task.id}/confirm", json={}, headers=h).status_code == 409
    assert client.get(f"{BASE}/{bogus}").status_code == 404


def test_assignees_lists_only_users_who_can_confirm(db_session, providers) -> None:
    jefa, client, _ = _client(db_session, "jefatura")
    reader = make_user(db_session, _roles(db_session)["ejecutivo"])
    ids = {i["id"] for i in client.get(f"{BASE}/assignees").json()["items"]}
    assert str(jefa.id) in ids and str(reader.id) not in ids


# ============================== MGT-14: monto de Payku ==============================


def _seed_payku(db, sub="sus_amt1", amount="9900", status="active"):
    db.add(Subscription(source="payku", external_id=sub, status=status, amount=amount, raw_payload={}))
    db.add(PaykuSubscription(external_id=sub, status=status, amount=amount, raw_payload={}))
    db.commit()


def _amount_requester(db):
    from billing_requests_support import make_role

    role = make_role(db, "cobros-t", {PERM_REQUEST, MANUAL_TASKS_VIEW})
    return make_user(db, role)


def test_payku_amount_change_is_a_manual_task_closed_by_the_sync(db_session) -> None:
    _seed_payku(db_session)
    user = _amount_requester(db_session)
    client, h = client_for(db_session, user)
    r = client.post(f"{BASE}/payku-amount", json={"subscription_external_id": "sus_amt1", "new_amount": 15000,
                                                   "comment": "Socio sube su aporte"}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["task_type"] == "payku_amount_change" and body["status"] == "pending"
    assert body["target_amount"] == 15000 and body["previous_amount"] == 9900
    assert body["assigned_to_user_id"] == str(user.id) and body["code"] == "PAYKU_AMOUNT_NO_API"
    # otra igual: 409; mismo monto: 422; suscripcion inexistente: 404
    dup = client.post(f"{BASE}/payku-amount", json={"subscription_external_id": "sus_amt1", "new_amount": 16000},
                      headers=h)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "open_task_exists"
    _seed_payku(db_session, "sus_amt2")
    assert client.post(f"{BASE}/payku-amount", json={"subscription_external_id": "sus_amt2", "new_amount": 9900},
                       headers=h).status_code == 422
    assert client.post(f"{BASE}/payku-amount", json={"subscription_external_id": "nope", "new_amount": 1},
                       headers=h).status_code == 404

    # la sync todavia trae el monto viejo: sigue abierta
    assert mt.verify_payku_amount_tasks(db_session) == []
    # el ejecutivo cambia el monto en el portal; la siguiente sync lo trae y la tarea se cierra sola
    row = db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == "sus_amt1"))
    row.amount = "15000.00"
    db_session.commit()
    payku_sync._verify_manual_amount_tasks(db_session)
    db_session.expire_all()
    task = db_session.get(SubscriptionManualTask, uuid.UUID(body["id"]))
    assert task.status == "verified" and task.verification_source == "payku_sync"
    last = mt.get_events(db_session, task.id)[-1]
    assert last.event_type == "verified" and last.actor_user_id is None and last.detail["observed_amount"] == 15000


def test_payku_amount_requires_billing_request_permission_and_active_subscription(db_session) -> None:
    _seed_payku(db_session, "sus_amt3", status="cancelled")
    _, client, h = _client(db_session, "jefatura")  # jefatura de make_roles no solicita cambios de cobro
    body = {"subscription_external_id": "sus_amt3", "new_amount": 12000}
    assert client.post(f"{BASE}/payku-amount", json=body, headers=h).status_code == 403
    user = _amount_requester(db_session)
    client, h = client_for(db_session, user)
    r = client.post(f"{BASE}/payku-amount", json=body, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "subscription_not_active"
    r = client.post(f"{BASE}/payku-amount", json={**body, "extra": "x"}, headers=h)
    assert r.status_code == 422


def test_payku_verification_failure_never_breaks_the_sync(db_session, monkeypatch) -> None:
    def boom(db):
        raise RuntimeError("fallo")

    monkeypatch.setattr(mt, "verify_payku_amount_tasks", boom)
    payku_sync._verify_manual_amount_tasks(db_session)  # no lanza


def test_parse_amount_handles_provider_formats() -> None:
    assert mt.parse_amount("15000") == Decimal("15000")
    assert mt.parse_amount("15000.00") == Decimal("15000.00")
    assert mt.parse_amount("$ 15,000") == Decimal("15000")
    assert mt.parse_amount("abc") is None and mt.parse_amount(None) is None and mt.parse_amount("0") is None


def test_permission_rows_exist_in_db(db_session) -> None:
    codes = set(db_session.scalars(select(Permission.code).where(Permission.code.like("subscriptions.manual_tasks.%"))))
    assert codes == {MANUAL_TASKS_VIEW, MANUAL_TASKS_CONFIRM}
