"""Recuperador general (UX-12, REC-04, REC-06): RBAC por pestaña, vistas Toku y TCH, migracion 0052.

Datos sinteticos, sin datos personales. La migracion 0052 se ejecuta dentro de una transaccion que se revierte (nunca
Alembic). Las pruebas de contenido usan la sesion revertible; las de API solo verifican permisos.
"""

import importlib.util
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.toku_report import CoreSubscriptionSignal
from app.services import rbac, recovery_tch, recovery_toku
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
TOKU, TCH, GEN, BILL = rbac.RECOVERY_TOKU_VIEW, rbac.RECOVERY_TCH_VIEW, rbac.GENERAL_RECOVERY_VIEW, rbac.GENERAL_BILLING_VIEW
NEW_CODES = {TOKU, TCH, GEN, BILL}


def _login(monkeypatch, perms: list[str]) -> TestClient:
    suffix = uuid.uuid4().hex[:10]
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        rbac.seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        role = Role(name=f"rg-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"rg-{suffix}", password_hash=hash_password("Pw-rg-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"rg-{suffix}", "password": "Pw-rg-12345"}).status_code == 200
    return client


TOKU_PATHS = ("/api/v1/recovery/toku/cancelled", "/api/v1/recovery/toku/rejected", "/api/v1/recovery/toku/recoverable")
TCH_PATHS = ("/api/v1/recovery/tch/deleted", "/api/v1/recovery/tch/rejected")
VP_PATHS = ("/api/v1/recovery/group", "/api/v1/recovery/rejected")


def test_catalog_has_general_permissions_with_spanish_descriptions() -> None:
    for code in NEW_CODES:
        assert code.startswith("general.") and code.endswith(".view") and rbac.PERMISSIONS[code].strip()
    # Roles de solo lectura las heredan por sufijo `.view`.
    assert NEW_CODES <= rbac.executive_permission_codes()


def test_toku_tab_permission_only_opens_toku_api(monkeypatch) -> None:
    client = _login(monkeypatch, [GEN, TOKU])
    for path in TOKU_PATHS:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert {"items", "total", "offset", "limit", "empty_reason"} <= set(resp.json())
    for path in TCH_PATHS + VP_PATHS:
        assert client.get(path).status_code == 403, path


def test_tch_tab_permission_only_opens_tch_api(monkeypatch) -> None:
    client = _login(monkeypatch, [GEN, TCH])
    for path in TCH_PATHS:
        assert client.get(path).status_code == 200, path
    for path in TOKU_PATHS + VP_PATHS:
        assert client.get(path).status_code == 403, path


def test_vp_tab_unchanged_and_does_not_open_other_tabs(monkeypatch) -> None:
    client = _login(monkeypatch, ["virtualpos.recovery.view"])
    for path in VP_PATHS:
        assert client.get(path).status_code == 200, path
    for path in TOKU_PATHS + TCH_PATHS:
        assert client.get(path).status_code == 403, path


def test_general_page_permission_alone_opens_no_tab_api(monkeypatch) -> None:
    client = _login(monkeypatch, [GEN])
    for path in TOKU_PATHS + TCH_PATHS + VP_PATHS:
        assert client.get(path).status_code == 403, path


def test_billing_inbox_accepts_general_or_virtualpos_view(monkeypatch) -> None:
    assert _login(monkeypatch, [BILL]).get("/api/v1/billing/changes").status_code == 200
    assert _login(monkeypatch, ["virtualpos.billing_changes.view"]).get("/api/v1/billing/changes").status_code == 200
    assert _login(monkeypatch, [GEN]).get("/api/v1/billing/changes").status_code == 403


def _sub(source: str, ext: str, **kw) -> CoreSubscription:
    return CoreSubscription(source=source, external_id=ext, **kw)


def test_toku_cancelled_and_rejected_views(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    gone = _sub("toku", f"sub-gone-{tag}", status="deleted_at_source", started_at=datetime(2097, 1, 1, tzinfo=UTC),
                ended_at=datetime(2097, 3, 1, tzinfo=UTC), amount=5000)
    alive = _sub("toku", f"sub-alive-{tag}", status="ACTIVE", started_at=datetime(2097, 1, 1, tzinfo=UTC))
    vp = _sub("virtualpos1", f"sub-vp-{tag}", ended_at=datetime(2097, 3, 1, tzinfo=UTC))
    db_session.add_all([gone, alive, vp])
    db_session.flush()
    db_session.add_all([
        CoreCharge(source="toku", external_id=f"in-rej-{tag}", subscription_id=alive.id, source_status="UNPAID", amount=5000,
                   latest_rejection_code="1001", latest_rejection_reason=None, latest_rejection_at=datetime(2097, 2, 5, tzinfo=UTC)),
        CoreCharge(source="toku", external_id=f"in-paid-{tag}", subscription_id=alive.id, source_status="PAID",
                   latest_rejection_code="1001", latest_rejection_at=datetime(2097, 2, 6, tzinfo=UTC)),
        CoreCharge(source="toku", external_id=f"in-ok-{tag}", subscription_id=alive.id, source_status="UNPAID"),
    ])
    db_session.flush()
    window = (date(2097, 1, 1), date(2097, 12, 31))

    cancelled = recovery_toku.cancelled(db_session, *window, 0, 50)
    ids = [row["subscription_id"] for row in cancelled["items"]]
    assert ids == [gone.external_id]
    row = cancelled["items"][0]
    assert row["cancelled_at"] == "2097-03-01" and row["antiquity_days"] == 59 and row["amount"] == 5000.0
    assert cancelled["total"] == 1 and cancelled["empty_reason"] is None

    rejected = recovery_toku.rejected(db_session, *window, 0, 50)
    assert [r["charge_id"] for r in rejected["items"]] == [f"in-rej-{tag}"]  # pagada y sin rechazo quedan fuera
    assert rejected["items"][0]["subscription_id"] == alive.external_id
    assert rejected["items"][0]["rejection_at"] == "2097-02-05"
    assert rejected["items"][0]["rejection_reason"]  # catalogo de Toku o, si falta, el codigo


def test_toku_recoverable_is_explicitly_empty_when_flag_is_off(db_session: Session, monkeypatch) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    sub = _sub("toku", f"sub-rec-{tag}", status="ACTIVE", amount=3000)
    db_session.add(sub)
    db_session.flush()
    db_session.add(CoreSubscriptionSignal(
        subscription_id=sub.id, source="toku", external_id=sub.external_id, lifecycle_status="active",
        payment_method_status="permanent_failed", is_recoverable=True, recoverable_reason="blocked_card",
        consecutive_failed_debts=1, computed_at=datetime.now(UTC),
    ))
    db_session.flush()

    monkeypatch.setattr(settings, "toku_report_signals_enabled", False)
    off = recovery_toku.recoverable(db_session, None, 0, 50)
    assert off == {"items": [], "total": 0, "offset": 0, "limit": 50, "empty_reason": "signals_disabled", "pii_included": False}

    monkeypatch.setattr(settings, "toku_report_signals_enabled", True)
    on = recovery_toku.recoverable(db_session, "blocked_card", 0, 500)
    mine = [r for r in on["items"] if r["subscription_id"] == sub.external_id]
    assert mine and mine[0]["recoverable_reason"] == "blocked_card" and mine[0]["amount"] == 3000.0
    assert on["empty_reason"] is None
    assert all(r["subscription_id"] != sub.external_id for r in recovery_toku.recoverable(db_session, "streak", 0, 500)["items"])


def test_toku_recoverable_without_signals_reports_no_signals(db_session: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(settings, "toku_report_signals_enabled", True)
    db_session.query(CoreSubscriptionSignal).delete()
    db_session.flush()
    assert recovery_toku.recoverable(db_session, None, 0, 50)["empty_reason"] == "no_signals"


def test_tch_deleted_and_rejected_views(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().int % 10_000_000
    gone = _sub("tch", f"9{tag}", status="ELIMINADO", started_at=datetime(2096, 1, 1, tzinfo=UTC), ended_at=datetime(2096, 6, 1, tzinfo=UTC))
    alive = _sub("tch", f"8{tag}", status="ACTIVO", started_at=datetime(2096, 1, 1, tzinfo=UTC))
    db_session.add_all([gone, alive])
    db_session.flush()
    db_session.add_all([
        CorePayment(source="tch", external_id=f"8{tag}|2096-02|1", subscription_id=alive.id, source_status="RECHAZADA",
                    occurred_at=datetime(2096, 2, 10, tzinfo=UTC), amount=4000, rejection_code="05", rejection_reason="Sin fondos"),
        CorePayment(source="tch", external_id=f"8{tag}|2096-03|1", subscription_id=alive.id, source_status="ACEPTADA",
                    occurred_at=datetime(2096, 3, 10, tzinfo=UTC), amount=4000),
    ])
    db_session.flush()
    window = (date(2096, 1, 1), date(2096, 12, 31))

    deleted = recovery_tch.deleted(db_session, *window, 0, 50)
    assert [r["subscription_id"] for r in deleted["items"]] == [gone.external_id]
    assert deleted["items"][0]["cancelled_at"] == "2096-06-01"

    rejected = recovery_tch.rejected(db_session, *window, 0, 50)
    assert [r["charge_id"] for r in rejected["items"]] == [f"8{tag}|2096-02|1"]
    assert rejected["items"][0]["subscription_id"] == alive.external_id
    assert rejected["items"][0]["rejection_reason"] == "Sin fondos"
    assert rejected["total"] == 1


def test_tch_service_has_no_write_paths() -> None:
    text = (ROOT / "app" / "services" / "recovery_tch.py").read_text(encoding="utf-8")
    for forbidden in ("insert(", "update(", "delete(", ".add(", "commit("):
        assert forbidden not in text


# --- Migracion 0052 ---------------------------------------------------------------------------------------------------

def _migration():
    path = ROOT / "alembic" / "versions" / "20261102_0052_seed_general_operation_permissions.py"
    spec = importlib.util.spec_from_file_location("mig_0052", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0052_chain_and_rules_match_rbac() -> None:
    mig = _migration()
    assert mig.revision == "20261102_0052" and mig.down_revision == "20261029_0051"
    assert mig.GRANT_RULES == rbac.GENERAL_GRANT_RULES
    assert {code: rbac.PERMISSIONS[code] for code in mig.PERMISSIONS} == mig.PERMISSIONS


def _role(db: Session, codes: list[str]) -> Role:
    perms = [db.scalar(select(Permission).where(Permission.code == c)) for c in codes]
    role = Role(name=f"mig52-{uuid.uuid4().hex[:8]}", permissions=perms)
    db.add(role)
    db.flush()
    return role


def _general_codes(db: Session, role: Role) -> set[str]:
    db.expire(role)
    return {p.code for p in role.permissions if p.code.startswith("general.")}


def test_migration_0052_grants_by_data_and_downgrade_removes(db_session: Session) -> None:  # noqa: F811
    mig = _migration()
    rbac.seed_permissions(db_session)
    db_session.flush()
    # Partimos sin los permisos nuevos (como una base en 0051).
    mig.revoke(db_session.connection())
    full = _role(db_session, ["virtualpos.recovery.view", "virtualpos.billing_changes.view", "toku.subscriptions.view", "tch.suscripciones.view"])
    vp_only = _role(db_session, ["virtualpos.recovery.view"])
    toku_only = _role(db_session, ["toku.subscriptions.view"])

    mig.grant(db_session.connection())
    mig.grant(db_session.connection())  # idempotente
    assert _general_codes(db_session, full) == NEW_CODES
    assert _general_codes(db_session, vp_only) == {GEN}
    assert _general_codes(db_session, toku_only) == set()

    mig.revoke(db_session.connection())
    assert _general_codes(db_session, full) == set()
    assert not db_session.scalars(select(Permission).where(Permission.code.in_(NEW_CODES))).all()


def test_ensure_general_grants_matches_migration(db_session: Session) -> None:  # noqa: F811
    rbac.seed_permissions(db_session)
    role = _role(db_session, ["virtualpos.recovery.view", "toku.subscriptions.view"])
    rbac.ensure_general_grants(db_session)
    rbac.ensure_general_grants(db_session)
    assert _general_codes(db_session, role) == {GEN, TOKU}


@pytest.mark.parametrize("path", TOKU_PATHS + TCH_PATHS)
def test_new_endpoints_reject_anonymous(path: str) -> None:
    assert TestClient(app, base_url="https://testserver").get(path).status_code == 401
