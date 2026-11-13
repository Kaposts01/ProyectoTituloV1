# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""CRM-14F: retiro de TODO el saldo de la billetera Payku (GET /api/wallet + POST /api/wallet/withdraw).

Cliente de Payku falso (sin red). Flag propio PAYKU_WALLET_WITHDRAW_ENABLED apagado por defecto, permiso propio
`payku.wallet.withdraw` (solo admin por siembra), CSRF, registro en write_runs y guarda de sandbox.
"""

import asyncio

import pytest
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    client_for,
    db_session,
    env,
    make_role,
    make_user,
)
from sqlalchemy import select

from app.core.config import settings
from app.integrations.payku.client import PaykuApiError, PaykuClient
from app.integrations.payku.write_guard import PROCESS_STATE, PaykuWriteBlockedError
from app.models.write_run import WriteRun
from app.services import rbac, write_payku

BASE = "/api/v1/writes/payku/wallet"
PERM = "payku.wallet.withdraw"
CALLS: list[tuple] = []


class FakeWallet:
    balance: object = {"status": "success", "current_id": "wa-test-1", "amount_available": 1766, "currency": "CLP"}
    withdraw_result: object = {"status": "success", "identifier_wallet": "wab-test-1"}

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_wallet_balance(self):
        CALLS.append(("balance",))
        if isinstance(self.balance, Exception):
            raise self.balance
        return self.balance

    async def wallet_withdraw(self, data):
        CALLS.append(("withdraw", dict(data)))
        if isinstance(self.withdraw_result, Exception):
            raise self.withdraw_result
        return self.withdraw_result


@pytest.fixture(autouse=True)
def wallet(monkeypatch):
    CALLS.clear()
    fake = type("Fake", (FakeWallet,), {})
    monkeypatch.setattr(write_payku, "PaykuClient", fake)
    monkeypatch.setattr(settings, "payku_writes_enabled", True)
    monkeypatch.setattr(settings, "payku_wallet_withdraw_enabled", True)
    return fake


def _admin(db, *codes):
    role = make_role(db, "admin", set(codes))
    user = make_user(db, role)
    client, headers = client_for(db, user)
    return user, client, headers


def _runs(db):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "wallet_withdraw")))


# --- configuracion y permiso -----------------------------------------------------------------------------------------


def test_flag_off_by_default() -> None:
    assert type(settings).model_fields["payku_wallet_withdraw_enabled"].default is False


def test_permission_seeded_only_for_admin() -> None:
    assert PERM in rbac.PERMISSIONS
    assert PERM not in rbac.support_permission_codes()
    assert PERM not in rbac.executive_permission_codes()


# --- servicio --------------------------------------------------------------------------------------------------------


def test_balance_with_flag_off_does_not_call_payku(monkeypatch) -> None:
    monkeypatch.setattr(settings, "payku_wallet_withdraw_enabled", False)
    assert asyncio.run(write_payku.get_wallet_balance()) == {"enabled": False, "amount_available": None, "currency": None}
    assert CALLS == []


def test_balance_requires_general_writes_switch(monkeypatch) -> None:
    monkeypatch.setattr(settings, "payku_writes_enabled", False)
    assert asyncio.run(write_payku.get_wallet_balance())["enabled"] is False
    assert CALLS == []


def test_withdraw_reads_balance_then_withdraws_everything(db_session) -> None:
    run = asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1766))
    assert [c[0] for c in CALLS] == ["balance", "withdraw"]
    body = CALLS[1][1]
    assert body["amount"] == 1766 and body["currency"] == "CLP"
    assert body["order"].startswith("crm-wd-") and len(body["order"]) <= 80
    assert len(body["subject"]) <= 200
    assert run.status == "completed" and run.resource_type == "wallet" and run.external_id == body["order"]
    assert run.response_payload["identifier_wallet"] == "wab-test-1"
    assert run.request_payload["wallet_current_id"] == "wa-test-1"
    assert run.finished_at is not None


def test_withdraw_disabled_by_flag(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "payku_wallet_withdraw_enabled", False)
    with pytest.raises(write_payku.WalletWithdrawDisabledError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1766))
    assert CALLS == [] and _runs(db_session) == []


def test_withdraw_respects_payku_writes_enabled(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "payku_writes_enabled", False)
    with pytest.raises(write_payku.WriteDisabledError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1766))
    assert CALLS == []


def test_withdraw_aborts_when_balance_changed(db_session) -> None:
    with pytest.raises(write_payku.WalletBalanceChangedError) as exc:
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1000))
    assert exc.value.current == 1766
    assert [c[0] for c in CALLS] == ["balance"] and _runs(db_session) == []


def test_withdraw_aborts_when_empty(db_session, wallet) -> None:
    wallet.balance = {"status": "success", "amount_available": 0, "currency": "CLP"}
    with pytest.raises(write_payku.WalletEmptyError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1))
    assert _runs(db_session) == []


@pytest.mark.parametrize("balance", [{"status": "success"}, {"amount_available": "x"}, {"amount_available": 5, "currency": "USD"}, ["no-dict"]])
def test_unreadable_balance_is_unavailable(db_session, wallet, balance) -> None:
    wallet.balance = balance
    with pytest.raises(write_payku.WalletUnavailableError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=5))
    assert _runs(db_session) == []


def test_provider_rejection_is_recorded_failed(db_session, wallet) -> None:
    wallet.withdraw_result = PaykuApiError("POST", "Unprocessable Entity", "amount:invalid", 200)
    with pytest.raises(PaykuApiError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1766))
    runs = _runs(db_session)
    assert len(runs) == 1 and runs[0].status == "failed" and "Unprocessable" in runs[0].error_message


def test_sandbox_guard_blocks_withdraw_endpoint(monkeypatch) -> None:
    """Fuera de produccion /api/wallet/withdraw no esta en la lista blanca: bloqueado antes de la red."""
    from app.integrations.payku import write_guard

    monkeypatch.setattr(settings, "app_env", "sandbox")
    monkeypatch.setattr(settings, "payku_base_url", "https://des.payku.cl")
    monkeypatch.setattr(PROCESS_STATE, "env", {write_guard.ENV_ARMED: "1"})
    client = PaykuClient.__new__(PaykuClient)
    with pytest.raises(PaykuWriteBlockedError) as exc:
        client._guard_write("POST", "/api/wallet/withdraw", {"amount": 1})
    assert exc.value.code == "ENDPOINT_NOT_ALLOWED"


def test_blocked_write_is_recorded(db_session, wallet) -> None:
    wallet.withdraw_result = PaykuWriteBlockedError("ENDPOINT_NOT_ALLOWED", "bloqueado")
    with pytest.raises(PaykuWriteBlockedError):
        asyncio.run(write_payku.withdraw_wallet_balance(db_session, expected_amount=1766))
    assert _runs(db_session)[0].status == "blocked"


# --- rutas -----------------------------------------------------------------------------------------------------------


def test_route_balance_and_withdraw(db_session) -> None:
    user, client, h = _admin(db_session, PERM)
    r = client.get(BASE)
    assert r.status_code == 200 and r.json() == {"enabled": True, "amount_available": 1766, "currency": "CLP"}
    r = client.post(f"{BASE}/withdraw", json={"expected_amount": 1766}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 1766 and body["identifier_wallet"] == "wab-test-1" and body["status"] == "completed"
    runs = _runs(db_session)
    assert len(runs) == 1 and runs[0].requested_by_user_id == user.id


def test_route_requires_permission(db_session) -> None:
    _, client, h = _admin(db_session, "payku.transactions.view")
    assert client.get(BASE).status_code == 403
    assert client.post(f"{BASE}/withdraw", json={"expected_amount": 1766}, headers=h).status_code == 403
    assert CALLS == []


def test_route_requires_admin_role(db_session) -> None:
    role = make_role(db_session, "wallet-no-admin-t", {PERM})
    client, h = client_for(db_session, make_user(db_session, role))
    assert client.post(f"{BASE}/withdraw", json={"expected_amount": 1766}, headers=h).status_code == 403
    assert CALLS == []


def test_route_requires_csrf(db_session) -> None:
    _, client, _ = _admin(db_session, PERM)
    assert client.post(f"{BASE}/withdraw", json={"expected_amount": 1766}).status_code == 403
    assert CALLS == []


@pytest.mark.parametrize(
    ("setup", "expected", "code"),
    [
        ("flag_off", 403, "payku_wallet_withdraw_disabled"),
        ("writes_off", 403, "payku_writes_disabled"),
        ("changed", 409, "payku_wallet_balance_changed"),
        ("empty", 409, "payku_wallet_empty"),
        ("unavailable", 502, "payku_wallet_unavailable"),
        ("rejected", 502, "payku_rejected_withdraw"),
    ],
)
def test_route_error_codes(db_session, wallet, monkeypatch, setup, expected, code) -> None:
    amount = 1766
    if setup == "flag_off":
        monkeypatch.setattr(settings, "payku_wallet_withdraw_enabled", False)
    elif setup == "writes_off":
        monkeypatch.setattr(settings, "payku_writes_enabled", False)
    elif setup == "changed":
        amount = 10
    elif setup == "empty":
        wallet.balance = {"amount_available": 0, "currency": "CLP"}
    elif setup == "unavailable":
        wallet.balance = RuntimeError("red")
    elif setup == "rejected":
        wallet.withdraw_result = PaykuApiError("POST", "Unauthorized", None, 200)
    _, client, h = _admin(db_session, PERM)
    r = client.post(f"{BASE}/withdraw", json={"expected_amount": amount}, headers=h)
    assert r.status_code == expected
    assert r.json()["detail"]["code"] == code


def test_route_rejects_non_positive_amount(db_session) -> None:
    _, client, h = _admin(db_session, PERM)
    assert client.post(f"{BASE}/withdraw", json={"expected_amount": 0}, headers=h).status_code == 422
    assert CALLS == []
