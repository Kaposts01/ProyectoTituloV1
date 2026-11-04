"""Recuperador general, pestaña Payku (REC-05): RBAC propio, vistas desde core y estado normalizado, migracion 0055.

Datos sinteticos (sin PII, sin Payku). La migracion se ejecuta dentro de una transaccion que se revierte.
"""

import importlib.util
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models.auth import Permission, Role
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.services import rbac, recovery_payku
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)
from tests.test_recovery_general import (
    GEN,
    TCH,
    TCH_PATHS,
    TOKU,
    TOKU_PATHS,
    VP_PATHS,
    _login,
)

ROOT = Path(__file__).resolve().parent.parent
PAYKU = rbac.RECOVERY_PAYKU_VIEW
PAYKU_PATHS = ("/api/v1/recovery/payku/cancelled", "/api/v1/recovery/payku/suspended", "/api/v1/recovery/payku/rejected")


def test_payku_permission_in_catalog() -> None:
    assert PAYKU == "general.recovery.payku.view" and rbac.PERMISSIONS[PAYKU].strip()
    assert PAYKU in rbac.executive_permission_codes()  # solo lectura: los roles de consulta la heredan por sufijo


def test_payku_tab_permission_only_opens_payku_api(monkeypatch) -> None:
    client = _login(monkeypatch, [GEN, PAYKU])
    for path in PAYKU_PATHS:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert {"items", "total", "offset", "limit", "empty_reason"} <= set(resp.json())
    for path in TOKU_PATHS + TCH_PATHS + VP_PATHS:
        assert client.get(path).status_code == 403, path


def test_other_tabs_do_not_open_payku_api(monkeypatch) -> None:
    client = _login(monkeypatch, [GEN, TOKU, TCH, "virtualpos.recovery.view", "payku.subscriptions.view"])
    for path in PAYKU_PATHS:
        assert client.get(path).status_code == 403, path


@pytest.mark.parametrize("path", PAYKU_PATHS)
def test_payku_endpoints_reject_anonymous(path: str) -> None:
    assert TestClient(app, base_url="https://testserver").get(path).status_code == 401


def test_bad_date_is_a_client_error(monkeypatch) -> None:
    client = _login(monkeypatch, [PAYKU])
    assert client.get("/api/v1/recovery/payku/cancelled?date_from=31-12-2095").status_code in (400, 422)


def _seed(db: Session, tag: str) -> dict[str, str]:
    """Una suscripcion por estado comun, con su fila de canal (el estado normalizado manda, no el crudo)."""
    ids = {}
    specs = {
        "deleted": ("delete", "cancelled", datetime(2095, 3, 1, tzinfo=UTC)),
        "finished": ("finish", "cancelled", datetime(2095, 5, 1, tzinfo=UTC)),
        "suspended": ("suspended", "suspended", datetime(2095, 4, 1, tzinfo=UTC)),
        "active": ("active", "active", None),
        # crudo «cancel» pero normalizado distinto: demuestra que la vista usa la columna normalizada
        "stale": ("cancel", "active", datetime(2095, 3, 15, tzinfo=UTC)),
    }
    for key, (raw, common, ended) in specs.items():
        ext = f"pk-{key}-{tag}"
        ids[key] = ext
        db.add(PaykuSubscription(external_id=ext, status=raw, status_normalized=common))
        db.add(CoreSubscription(source="payku", external_id=ext, status=raw, started_at=datetime(2095, 1, 1, tzinfo=UTC),
                                ended_at=ended, amount=5000, currency="CLP",
                                last_payment_status="maximum attempt limit" if key == "suspended" else None))
    db.flush()
    return ids


def test_cancelled_and_suspended_views_use_normalized_status(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    ids = _seed(db_session, tag)
    window = (date(2095, 1, 1), date(2095, 12, 31))

    cancelled = recovery_payku.cancelled(db_session, *window, 0, 50)
    mine = [r for r in cancelled["items"] if r["subscription_id"].endswith(tag)]
    assert [r["subscription_id"] for r in mine] == [ids["finished"], ids["deleted"]]  # baja mas reciente primero
    assert mine[1]["cancelled_at"] == "2095-03-01" and mine[1]["antiquity_days"] == 59
    assert mine[1]["status"] == "delete" and mine[1]["status_normalized"] == "cancelled"

    narrow = recovery_payku.cancelled(db_session, date(2095, 4, 1), date(2095, 12, 31), 0, 50)
    assert ids["deleted"] not in [r["subscription_id"] for r in narrow["items"]]

    suspended = recovery_payku.suspended(db_session, *window, 0, 50)
    mine = [r for r in suspended["items"] if r["subscription_id"].endswith(tag)]
    assert [r["subscription_id"] for r in mine] == [ids["suspended"]]
    assert mine[0]["last_payment_status"] == "maximum attempt limit"


def test_rejected_view_uses_normalized_transaction_status_and_cycle(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    ids = _seed(db_session, tag)
    sub = db_session.scalar(select(CoreSubscription).where(CoreSubscription.external_id == ids["suspended"]))
    charge = CoreCharge(source="payku", external_id=f"{ids['suspended']}:2095-02-09", subscription_id=sub.id,
                        period_reference="2095-02", source_status="maximum attempt limit")
    db_session.add(charge)
    db_session.flush()
    rows = [
        (f"rej-{tag}", "rejected", "rejected", datetime(2095, 2, 10, tzinfo=UTC), charge.id, "maximum attempt limit"),
        (f"ok-{tag}", "success", "paid", datetime(2095, 1, 10, tzinfo=UTC), None, None),
        (f"old-{tag}", "rejected", "rejected", datetime(2094, 1, 10, tzinfo=UTC), None, None),
    ]
    for ext, raw, common, when, charge_id, reason in rows:
        db_session.add(PaykuTransaction(external_id=ext, subscription_id=ids["suspended"], status=raw, status_normalized=common))
        db_session.add(CorePayment(source="payku", external_id=ext, subscription_id=sub.id, charge_id=charge_id,
                                   source_status=raw, occurred_at=when, amount=0, currency="CLP", rejection_reason=reason))
    db_session.flush()

    result = recovery_payku.rejected(db_session, date(2095, 1, 1), date(2095, 12, 31), 0, 50)
    mine = [r for r in result["items"] if r["charge_id"].endswith(tag)]
    assert [r["charge_id"] for r in mine] == [f"rej-{tag}"]  # el pagado y el fuera de rango quedan fuera
    row = mine[0]
    assert row["subscription_id"] == ids["suspended"] and row["period"] == "2095-02" and row["charge_date"] == "2095-02-10"
    assert row["rejection_reason"] == "Se agotaron los reintentos de cobro"


def test_payku_service_has_no_write_paths_or_provider_calls() -> None:
    text = (ROOT / "app" / "services" / "recovery_payku.py").read_text(encoding="utf-8")
    for forbidden in ("insert(", "update(", "delete(", ".add(", "commit(", "integrations", "httpx", "PaykuClient("):
        assert forbidden not in text


# --- Permiso en la migracion 0055 -------------------------------------------------------------------------------------

def _migration():
    path = ROOT / "alembic" / "versions" / "20261102_0055_payku_cycles_status_recovery.py"
    spec = importlib.util.spec_from_file_location("mig_0055_rec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _role(db: Session, codes: list[str]) -> Role:
    perms = [db.scalar(select(Permission).where(Permission.code == c)) for c in codes]
    role = Role(name=f"mig55-{uuid.uuid4().hex[:8]}", permissions=perms)
    db.add(role)
    db.flush()
    return role


def _has_payku(db: Session, role: Role) -> bool:
    db.expire(role)
    return PAYKU in {p.code for p in role.permissions}


def test_migration_0055_grants_payku_tab_by_data_and_downgrade_removes(db_session: Session) -> None:  # noqa: F811
    mig = _migration()
    rbac.seed_permissions(db_session)
    db_session.flush()
    mig.revoke(db_session.connection())  # como una base en 0052
    full = _role(db_session, ["virtualpos.recovery.view", "payku.subscriptions.view"])
    vp_only = _role(db_session, ["virtualpos.recovery.view"])
    payku_only = _role(db_session, ["payku.subscriptions.view"])

    mig.grant(db_session.connection())
    mig.grant(db_session.connection())  # idempotente
    assert _has_payku(db_session, full)
    assert not _has_payku(db_session, vp_only) and not _has_payku(db_session, payku_only)

    mig.revoke(db_session.connection())
    assert not _has_payku(db_session, full)
    assert db_session.scalar(select(Permission).where(Permission.code == PAYKU)) is None


def test_ensure_general_grants_includes_payku_tab(db_session: Session) -> None:  # noqa: F811
    rbac.seed_permissions(db_session)
    role = _role(db_session, ["virtualpos.recovery.view", "payku.subscriptions.view"])
    rbac.ensure_general_grants(db_session)
    assert _has_payku(db_session, role)
