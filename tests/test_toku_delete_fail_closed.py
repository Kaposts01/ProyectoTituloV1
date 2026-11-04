"""MGT-05: `delete_subscription` de Toku falla CERRADO tambien en produccion.

Si alguna invoice esta `in_progress` (D30) la baja se NIEGA (409 `INVOICE_IN_PROGRESS`) sin anular nada.
Si falla el listado de invoices impagas, o la anulacion de alguna invoice impaga que no esta `in_progress`, NO se
borra la suscripcion (el DELETE es irreversible). El error expone un codigo fijo (sin texto libre del proveedor) y el
`write_run` queda con el paso fallido; con anulaciones ya hechas (irreversibles) queda `reconciliation_required`.
Cliente falso: ninguna llamada de red.
"""

import asyncio
from typing import ClassVar

import httpx
import pytest
import test_toku_write_guard as base
from sqlalchemy import select

from app.models.crm import Subscription
from app.models.write_run import WriteRun
from app.services import write_toku

db_session = base.db_session
production = base.production
use_settings = base.use_settings

SECRET_TEXT = "texto-libre-del-proveedor-no-debe-salir"


class FakeToku:
    calls: ClassVar[list[tuple[str, str]]] = []
    invoices: ClassVar[list[dict]] = []
    list_error = False
    void_fail: ClassVar[set[str]] = set()
    delete_error = False

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def precheck_writes(self, operations):
        return None

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        FakeToku.calls.append(("list", subscription_id))
        if FakeToku.list_error:
            raise RuntimeError(SECRET_TEXT)
        return {"invoices": list(FakeToku.invoices)}

    async def void_invoice(self, invoice_id, data):
        FakeToku.calls.append(("void", invoice_id))
        if invoice_id in FakeToku.void_fail:
            raise RuntimeError(SECRET_TEXT)
        return {}

    async def delete_subscription(self, subscription_id):
        FakeToku.calls.append(("delete", subscription_id))
        if FakeToku.delete_error:
            request = httpx.Request("DELETE", "https://toku.invalid/x")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))
        return {}


@pytest.fixture(autouse=True)
def _fake(monkeypatch, db_session):
    FakeToku.calls = []
    FakeToku.invoices = []
    FakeToku.list_error = False
    FakeToku.void_fail = set()
    FakeToku.delete_error = False
    use_settings(monkeypatch, production())
    monkeypatch.setattr(write_toku, "TokuClient", FakeToku)
    db_session.add(Subscription(source="toku", external_id="sub_fc", raw_payload={}, status="ACTIVE"))
    db_session.flush()


def _run(db):
    return db.scalars(select(WriteRun).where(WriteRun.external_id == "sub_fc")).one()


def _deleted() -> bool:
    return ("delete", "sub_fc") in FakeToku.calls


def test_production_listing_failure_aborts_without_deleting(db_session) -> None:
    FakeToku.list_error = True
    with pytest.raises(write_toku.DeleteAbortedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    assert e.value.code == "INVOICE_LIST_FAILED"
    assert SECRET_TEXT not in str(e.value)
    assert not _deleted()
    run = _run(db_session)
    assert run.status == "failed"
    assert "INVOICE_LIST_FAILED" in run.error_message and SECRET_TEXT not in run.error_message
    assert run.response_payload["step"] == "list_invoices"
    sub = db_session.scalar(select(Subscription).where(Subscription.external_id == "sub_fc"))
    assert sub.status == "ACTIVE"  # la suscripcion local no se toca


def test_production_void_failure_midway_aborts_and_flags_reconciliation(db_session) -> None:
    FakeToku.invoices = [{"id": "in_1"}, {"id": "in_2"}, {"id": "in_3"}]
    FakeToku.void_fail = {"in_2"}
    with pytest.raises(write_toku.DeleteAbortedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    assert e.value.code == "INVOICE_VOID_FAILED"
    assert SECRET_TEXT not in str(e.value)
    assert ("void", "in_3") not in FakeToku.calls  # se detiene en el primer fallo
    assert not _deleted()
    run = _run(db_session)
    assert run.status == "reconciliation_required"  # in_1 ya quedo anulada (irreversible)
    assert SECRET_TEXT not in run.error_message
    assert run.response_payload["step"] == "void_invoice"
    assert run.response_payload["voided_invoice_ids"] == ["in_1"]
    assert run.response_payload["failed_invoice_id"] == "in_2"
    assert run.response_payload["requires_reconciliation"] is True


def test_production_first_void_failure_is_plain_failed(db_session) -> None:
    FakeToku.invoices = [{"id": "in_1"}]
    FakeToku.void_fail = {"in_1"}
    with pytest.raises(write_toku.DeleteAbortedError):
        asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    run = _run(db_session)
    assert run.status == "failed"  # nada irreversible hecho todavia
    assert run.response_payload["voided_invoice_ids"] == []
    assert run.response_payload["requires_reconciliation"] is False
    assert not _deleted()


def test_production_success_voids_all_unpaid_then_deletes(db_session) -> None:
    FakeToku.invoices = [{"id": "in_1"}, {"id": "in_2"}]
    sub = asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    assert sub.status == "deleted"
    assert [c for c in FakeToku.calls if c[0] != "list"] == [("void", "in_1"), ("void", "in_2"), ("delete", "sub_fc")]
    run = _run(db_session)
    assert run.status == "completed"
    assert run.response_payload["voided_invoice_ids"] == ["in_1", "in_2"]
    assert run.response_payload["skipped_in_progress"] == []


def test_in_progress_invoice_denies_delete_and_voids_nothing(db_session) -> None:
    """D30: una factura in_progress impide la baja; no se anula NADA (ni las demas impagas)."""
    FakeToku.invoices = [{"id": "in_1"}, {"id": "in_busy", "in_progress": True}, {"id": "in_2"}]
    with pytest.raises(write_toku.DeleteAbortedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    assert e.value.code == "INVOICE_IN_PROGRESS"
    assert SECRET_TEXT not in str(e.value)
    assert [c for c in FakeToku.calls if c[0] != "list"] == []  # ni void ni delete
    run = _run(db_session)
    assert run.status == "failed"  # nada irreversible hecho
    assert "INVOICE_IN_PROGRESS" in run.error_message
    assert run.response_payload["step"] == "invoice_in_progress"
    assert run.response_payload["skipped_in_progress"] == ["in_busy"]
    assert run.response_payload["voided_invoice_ids"] == []
    assert run.response_payload["requires_reconciliation"] is False
    sub = db_session.scalar(select(Subscription).where(Subscription.external_id == "sub_fc"))
    assert sub.status == "ACTIVE"


def test_route_in_progress_returns_409_fixed_code(monkeypatch, db_session) -> None:
    from billing_requests_support import client_for, make_role, make_user

    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    FakeToku.invoices = [{"id": "in_busy", "in_progress": True}]
    user = make_user(db_session, make_role(db_session, "tk-manage-ip", {"toku.subscriptions.manage"}), make_role(db_session, "admin", {"toku.subscriptions.manage"}))
    client, h = client_for(db_session, user)
    r = client.delete("/api/v1/writes/toku/subscriptions/sub_fc", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVOICE_IN_PROGRESS"
    assert SECRET_TEXT not in r.text
    assert not _deleted()
    assert ("void", "in_busy") not in FakeToku.calls


def test_delete_failure_after_voids_flags_reconciliation(db_session) -> None:
    FakeToku.invoices = [{"id": "in_1"}]
    FakeToku.delete_error = True
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(write_toku.delete_subscription(db_session, "sub_fc"))
    run = _run(db_session)
    assert run.status == "reconciliation_required"
    assert run.response_payload["voided_invoice_ids"] == ["in_1"]


def test_route_maps_abort_to_fixed_code_without_provider_text(monkeypatch, db_session) -> None:
    from billing_requests_support import client_for, make_role, make_user

    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    FakeToku.list_error = True
    user = make_user(db_session, make_role(db_session, "tk-manage-t", {"toku.subscriptions.manage"}), make_role(db_session, "admin", {"toku.subscriptions.manage"}))
    client, h = client_for(db_session, user)
    r = client.delete("/api/v1/writes/toku/subscriptions/sub_fc", headers=h)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "toku_deletion_aborted"
    assert "INVOICE_LIST_FAILED" in r.json()["detail"]["message"]
    assert SECRET_TEXT not in r.text
    assert not _deleted()
