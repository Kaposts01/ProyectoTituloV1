import csv
import io
import uuid
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.recovery import (
    CSV_COLUMNS,
    RecoveryFilters,
    _cancelled_rows,
    _csv_response,
    _csv_safe,
    _rejected_rows,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import CoreCharge
from app.models.crm import Charge, Client, Subscription
from app.models.write_run import WriteRun
from app.services.rbac import seed_permissions
from app.services.vp_rejection_codes import format_rejection_reason
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)


def _rejected(ext: str, **kw) -> Charge:
    base = {"source": "virtualpos1", "external_id": ext, "status": "rechazado", "charge_date": "2099-03-10", "amount": "1000"}
    base.update(kw)
    return Charge(**base)


def test_format_rejection_reason_catalog_raw_and_unknown() -> None:
    assert format_rejection_reason("-8", "x") == "Tarjeta expirada"
    assert format_rejection_reason("ZZ-99", None) == "ZZ-99"
    assert format_rejection_reason("ZZ-99", "Texto del proveedor") == "Texto del proveedor"
    assert format_rejection_reason(None, None) == "No informado por VirtualPOS"


def test_rejected_rows_prefer_core_rejection_and_fallback_to_raw_payload(db_session: Session) -> None:  # noqa: F811
    db_session.add_all([
        _rejected("rec03-core", raw_payload={"rejected_object": {"code": "-2", "message": "viejo"}}),
        _rejected("rec03-raw", raw_payload={"rejected_object": {"code": "-6", "message": "Texto"}}),
        _rejected("rec03-unknown", raw_payload={"rejected_object": {"code": "-7777", "message": ""}}),
        CoreCharge(source="virtualpos1", external_id="rec03-core", latest_rejection_code="-8", latest_rejection_reason="Tarjeta expirada",
                   latest_rejection_at=datetime(2099, 3, 9, tzinfo=UTC)),
    ])
    db_session.flush()
    rows = {r["external_id"]: r for r in _rejected_rows(db_session, None, None, "retry")}
    rows.update({r["external_id"]: r for r in _rejected_rows(db_session, None, None, "card")})
    assert rows["rec03-core"]["rejection_code"] == "-8"
    assert rows["rec03-core"]["rejection_reason"] == "Tarjeta expirada"
    assert rows["rec03-core"]["rejection_at"] == "2099-03-09"
    assert rows["rec03-raw"]["rejection_code"] == "-6"
    assert rows["rec03-raw"]["rejection_reason"] == "Rechazo general"
    assert rows["rec03-raw"]["rejection_at"] == "2099-03-10"
    assert rows["rec03-unknown"]["rejection_reason"] == "-7777"


def test_filters_apply_globally_and_monto_vigente(db_session: Session) -> None:  # noqa: F811
    db_session.add_all([
        Subscription(source="virtualpos1", external_id="rec03-sub", status="activa", amount="5000", suscription_date="2098-01-01"),
        Charge(source="virtualpos1", external_id="rec03-paid", subscription_external_id="rec03-sub", status="pagado", charge_date="2020-01-01", amount="7000"),
        _rejected("rec03-a", subscription_external_id="rec03-sub", amount="100", raw_payload={"rejected_object": {"code": "-2"}}),
        _rejected("rec03-b", source="virtualpos2", amount="900", charge_date="2099-05-01", raw_payload={"rejected_object": {"code": "-6"}}),
    ])
    db_session.flush()

    def ids(**kw):
        return {r["external_id"] for r in _rejected_rows(db_session, None, None, "retry", RecoveryFilters(**kw))}

    assert {"rec03-a", "rec03-b"} <= ids()
    assert "rec03-b" in ids(account="virtualpos2") and "rec03-a" not in ids(account="virtualpos2")
    assert "rec03-b" not in ids(rejection_code="-2") and "rec03-a" in ids(rejection_code="-2")
    assert "rec03-a" not in ids(min_amount=500) and "rec03-b" in ids(min_amount=500)
    assert "rec03-b" not in ids(max_amount=500) and "rec03-a" in ids(max_amount=500)
    assert "rec03-a" in ids(secondary_status="incobrable")
    assert "rec03-b" in ids(rejected_from=date(2099, 4, 1)) and "rec03-a" not in ids(rejected_from=date(2099, 4, 1))
    row = next(r for r in _rejected_rows(db_session, None, None, "retry") if r["external_id"] == "rec03-a")
    assert row["monto_vigente"] == 7000.0 and row["monto"] == 100.0 and row["attempts"] == 2


def test_csv_columns_order_neutralization_and_pii() -> None:
    row = {"account": "virtualpos1", "subscription_id": "=cmd", "charge_id": "c1", "monto": 10.0, "rejection_at": "2099-01-01",
           "rejection_code": "-8", "rejection_reason": "+SUM(1)", "estado": "rechazado", "attempts": 2, "last_paid_date": None,
           "cancelled_at": None, "source_record_id": None, "external_id": "c1", "rut": "@x", "client_name": "-Ana", "email": "a@b.cl", "phone": "123"}
    expected = ["cuenta", "id_suscripcion", "id_cargo", "monto", "fecha_rechazo", "codigo_rechazo", "motivo_rechazo", "estado", "intentos",
                "ultimo_cobro", "fecha_cancelacion", "source_record_id", "external_id", "rut", "nombre", "email", "telefono"]
    assert list(CSV_COLUMNS) == expected
    full = list(csv.reader(io.StringIO(_csv_response([row], "f.csv", True).body.decode("utf-8-sig"))))
    assert full[0] == expected
    data = dict(zip(full[0], full[1], strict=True))
    assert data["id_suscripcion"] == "'=cmd" and data["motivo_rechazo"] == "'+SUM(1)" and data["rut"] == "'@x" and data["nombre"] == "'-Ana"
    assert data["codigo_rechazo"] == "'-8"
    assert _csv_safe(5) == 5 and _csv_safe(None) is None
    masked = list(csv.reader(io.StringIO(_csv_response([row], "f.csv", False).body.decode("utf-8-sig"))))
    assert masked[0] == expected[:13]
    assert "a@b.cl" not in str(masked)


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        role = Role(name=f"r03-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"r03-{suffix}", password_hash=hash_password("Pw-r03-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": f"r03-{suffix}", "password": "Pw-r03-12345"}).status_code == 200
    return client


def test_export_endpoint_includes_pii_audits_without_content_and_view_cannot_export(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:10]
    code = f"=X{suffix}"
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{suffix}", first_name="Ana", last_name="Rios", email=f"ana{suffix}@example.test", social_id="11111111-1"),
            Subscription(source="virtualpos1", external_id=f"sub-{suffix}", client_external_id=f"cl-{suffix}", status="activa"),
            Charge(source="virtualpos1", external_id=f"ch-{suffix}", subscription_external_id=f"sub-{suffix}", status="rechazado",
                   charge_date="2099-07-01", amount="1500", raw_payload={"rejected_object": {"code": code, "message": "m"}}),
        ])
        db.commit()
    finally:
        db.close()
    exporter = _login(monkeypatch, suffix + "e", ["virtualpos.recovery.export", "virtualpos.recovery.view"])
    resp = exporter.get("/api/v1/recovery/rejected/export", params={"rejection_code": code, "account": "virtualpos1"})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert rows[0] == list(CSV_COLUMNS) and len(rows) == 2
    data = dict(zip(rows[0], rows[1], strict=True))
    assert data["rut"] == "11111111-1" and data["nombre"] == "Ana Rios" and data["id_cargo"] == f"ch-{suffix}"
    assert data["codigo_rechazo"] == "'" + code

    db = SessionLocal()
    try:
        run = db.scalars(select(WriteRun).where(WriteRun.operation == "export_csv", WriteRun.request_payload["username"].astext == f"r03-{suffix}e")).first()
        payload = run.request_payload
        assert payload["endpoint"] == "recovery/rejected/export" and payload["rows"] == 1 and payload["filters"]["account"] == "virtualpos1"
        assert run.started_at is not None
        dumped = str(payload)
        assert "11111111-1" not in dumped and "Ana" not in dumped and "example.test" not in dumped
    finally:
        db.close()

    viewer = _login(monkeypatch, suffix + "v", ["virtualpos.recovery.view"])
    assert viewer.get("/api/v1/recovery/rejected/export").status_code == 403
    assert viewer.get("/api/v1/recovery/rejected", params={"rejection_code": code}).json()["total"] == 1


def test_cancelled_rows_filter_before_pagination(db_session: Session) -> None:  # noqa: F811
    db_session.add(Subscription(source="virtualpos2", external_id="rec03-can", status="cancelada", canceled_at="2099-02-02", amount="300"))
    db_session.flush()
    rows = _cancelled_rows(db_session, None, None, RecoveryFilters(account="virtualpos2", max_amount=400))
    assert any(r["external_id"] == "rec03-can" for r in rows)
    assert all(r["account"] == "virtualpos2" for r in rows)
