"""RJ-15: los intentos FAILED de Toku se materializan como core_payments SIN distorsionar los KPIs.

Payloads sinteticos con la forma real de `GET /transactions` (ver test_toku_rejection_projection). La garantia central:
las cifras de Toku (dashboard centralizado, estadistica de rechazo de cargos, recuperacion) son identicas antes y
despues de materializar, porque ningun lector de KPIs usa `core_payments`.
"""

import ast
import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes import recovery, staging
from app.core.config import settings
from app.models.core import CoreCharge, CorePayment
from app.models.crm import Charge, Payment, Subscription
from app.models.toku_channel import TokuTransaction
from app.services import charge_stats, core_toku_etl
from app.services.toku_failed_payments import materialize_failed_toku_payments
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


def _uid() -> str:
    return "rj15-" + uuid.uuid4().hex[:10]


def _tx(invoice: str | None, *, tx_id: str | None = None, status: str = "FAILED", code: str | None = "TEPSP1008",
        message: str | None = "[51] EXCEDE SALDO MAXIMO", date: str = "2026-10-05T12:00:00.000000",
        amount: str | None = "5000") -> TokuTransaction:
    tx_id = tx_id or _uid()
    transaction = {"id": tx_id, "type": "PAYMENT", "status": status, "transaction_date": date}
    if amount is not None:
        transaction["amount"] = amount
    if code is not None:
        transaction["response_code"] = code
    if message is not None:
        transaction["original_response_message"] = message
    intents = [{"id": _uid(), "id_invoice": invoice, "id_subscription": _uid()}] if invoice else []
    return TokuTransaction(external_id=tx_id, status=status, amount=amount, currency="CLP", created_at_api=date,
                           raw_payload={"transaction": transaction, "payment_intents": intents})


def _charge(db: Session, invoice: str) -> CoreCharge:
    charge = CoreCharge(source="toku", external_id=invoice, source_status="UNPAID")
    db.add(charge)
    db.flush()
    return charge


def _failed_payments(db: Session) -> list[CorePayment]:
    return list(db.scalars(select(CorePayment).where(CorePayment.source == "toku", CorePayment.source_status == "FAILED")))


# -- comportamiento de la funcion -----------------------------------------------------------------------------------

def test_failed_transaction_becomes_a_core_payment_with_the_projected_rejection(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    tx = _tx(inv, message="[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33")
    db_session.add(tx)
    db_session.flush()
    stats = materialize_failed_toku_payments(db_session)
    assert stats["to_create"] >= 1 and stats["written"] >= 1
    payment = db_session.scalar(select(CorePayment).where(CorePayment.source == "toku", CorePayment.external_id == tx.external_id))
    assert payment is not None
    assert payment.source_status == "FAILED"
    assert payment.charge_id == charge.id
    assert payment.rejection_code == "TEPSP1008"
    assert payment.rejection_reason == "RECHAZADA- REINTENTAR"  # misma normalizacion que RJ-01
    assert payment.rejection_reported_at == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert payment.occurred_at == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert float(payment.amount) == 5000.0 and payment.currency == "CLP"


def test_it_is_idempotent_and_a_second_run_writes_nothing(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    _charge(db_session, inv)
    db_session.add_all([_tx(inv), _tx(inv, code=None, message=None)])
    db_session.flush()
    first = materialize_failed_toku_payments(db_session)
    assert first["written"] >= 2
    count = db_session.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == "toku"))
    second = materialize_failed_toku_payments(db_session)
    assert second["written"] == 0 and second["to_create"] == 0 and second["to_update"] == 0
    assert db_session.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == "toku")) == count


def test_a_changed_transaction_updates_only_its_own_failed_row(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    _charge(db_session, inv)
    tx = _tx(inv, code="TEPSP1008")
    db_session.add(tx)
    db_session.flush()
    materialize_failed_toku_payments(db_session)
    tx.raw_payload = {**tx.raw_payload, "transaction": {**tx.raw_payload["transaction"], "response_code": "TEPSP2070"}}
    db_session.flush()
    stats = materialize_failed_toku_payments(db_session)
    assert stats["to_update"] == 1
    payment = db_session.scalar(select(CorePayment).where(CorePayment.source == "toku", CorePayment.external_id == tx.external_id))
    db_session.refresh(payment)
    assert payment.rejection_code == "TEPSP2070"


def test_it_never_overwrites_a_successful_payment_with_the_same_id(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    _charge(db_session, inv)
    tx = _tx(inv)
    db_session.add(tx)
    paid = CorePayment(source="toku", external_id=tx.external_id, source_status=None, amount=9999)
    db_session.add(paid)
    db_session.flush()
    stats = materialize_failed_toku_payments(db_session)
    assert stats["skipped_foreign_conflict"] == 1 and stats["written"] == 0
    db_session.refresh(paid)
    assert paid.source_status is None and float(paid.amount) == 9999.0 and paid.rejection_code is None


def test_only_failed_transactions_and_those_without_invoice_or_data_are_handled(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    _charge(db_session, inv)
    ok = _tx(inv, status="SUCCESS")
    no_invoice = _tx(None)
    no_data = _tx(inv, code=None, message=None)
    db_session.add_all([ok, no_invoice, no_data])
    db_session.flush()
    stats = materialize_failed_toku_payments(db_session)
    assert stats["without_charge"] >= 1 and stats["without_rejection_data"] >= 1
    ids = {p.external_id for p in _failed_payments(db_session)}
    assert ok.external_id not in ids  # un SUCCESS nunca se materializa aqui
    assert no_invoice.external_id in ids and no_data.external_id in ids
    orphan = db_session.scalar(select(CorePayment).where(CorePayment.external_id == no_invoice.external_id))
    assert orphan.charge_id is None and orphan.subscription_id is None
    blank = db_session.scalar(select(CorePayment).where(CorePayment.external_id == no_data.external_id))
    assert blank.rejection_code is None and blank.rejection_reason is None and blank.charge_id is not None


def test_dry_run_writes_nothing_but_reports(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    _charge(db_session, inv)
    db_session.add(_tx(inv))
    db_session.flush()
    before = db_session.scalar(select(func.count()).select_from(CorePayment))
    stats = materialize_failed_toku_payments(db_session, apply=False)
    assert stats["applied"] is False and stats["to_create"] >= 1 and stats["written"] == 0
    assert db_session.scalar(select(func.count()).select_from(CorePayment)) == before


def test_it_does_not_touch_core_charges_or_the_channel_tables(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    db_session.add(_tx(inv))
    db_session.flush()
    snapshot = lambda: db_session.execute(  # noqa: E731
        select(CoreCharge.id, CoreCharge.source_status, CoreCharge.latest_rejection_code, CoreCharge.latest_rejection_reason,
               CoreCharge.latest_rejection_at, CoreCharge.latest_rejection_payment_id, CoreCharge.updated_at)
        .where(CoreCharge.source == "toku").order_by(CoreCharge.id)).all()
    before, tx_before = snapshot(), db_session.scalar(select(func.count()).select_from(TokuTransaction))
    materialize_failed_toku_payments(db_session)
    assert snapshot() == before
    assert db_session.scalar(select(func.count()).select_from(TokuTransaction)) == tx_before
    db_session.refresh(charge)
    assert charge.latest_rejection_code is None


# -- KPIs: las cifras de Toku NO cambian ------------------------------------------------------------------------------

def _kpi_snapshot(db: Session) -> dict:
    """Todo lo que alimenta las tarjetas/alertas/recuperacion de Toku."""
    dash = staging._toku_centralized_dashboard(db)
    rows = [
        {"date": c.charge_date, "status": c.status}
        for c in db.scalars(select(Charge).where(Charge.source == "toku"))
    ]
    stats = charge_stats.charge_rejection_stats(rows, charge_stats.chile_today())
    recovery_rows = recovery._rejected_rows(db, None, None, "retry")
    core = db.execute(select(CoreCharge.external_id, CoreCharge.latest_rejection_code, CoreCharge.latest_rejection_reason)
                      .where(CoreCharge.source == "toku").order_by(CoreCharge.external_id)).all()
    return {"dashboard": dash, "stats": stats, "recovery": recovery_rows, "core_charges": [tuple(r) for r in core]}


def test_toku_kpis_are_identical_before_and_after_materializing_failed_attempts(db_session: Session) -> None:  # noqa: F811
    paid_inv, rej_inv = _uid(), _uid()
    sub_ext = _uid()
    db_session.add_all([
        Subscription(source="toku", external_id=sub_ext, client_external_id=_uid(), status="ACTIVE", amount="5000",
                     suscription_date="2026-01-01", raw_payload={}),
        Charge(source="toku", external_id=paid_inv, subscription_external_id=sub_ext, status="PAID", amount="5000",
               charge_date="2026-09-05", raw_payload={}),
        Charge(source="toku", external_id=rej_inv, subscription_external_id=sub_ext, status="UNPAID", amount="5000",
               charge_date="2026-10-05", raw_payload={}),
        Payment(source="toku", external_id=_uid(), charge_external_id=paid_inv, status="SUCCESS", amount="5000",
                payment_date="2026-09-05", raw_payload={}),
        Payment(source="toku", external_id=_uid(), charge_external_id=rej_inv, status="FAILED", amount="5000",
                payment_date="2026-10-05", raw_payload={}),
    ])
    _charge(db_session, rej_inv)
    for i in range(3):
        db_session.add(_tx(rej_inv, date=f"2026-10-0{i + 1}T12:00:00.000000"))
    db_session.flush()

    before = _kpi_snapshot(db_session)
    stats = materialize_failed_toku_payments(db_session)
    assert stats["written"] == 3  # los FAILED SI se materializaron
    after = _kpi_snapshot(db_session)
    assert after == before  # y ninguna cifra cambio
    assert before["stats"]["paid"] == 1  # la estadistica sigue usando la definicion unica sobre los cargos


def _references_core_payments(path: Path) -> bool:
    """True si el codigo (no los docstrings ni comentarios) usa el modelo `CorePayment` o nombra `core_payments` en SQL."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "CorePayment":
            return True
        if isinstance(node, ast.alias) and node.name == "CorePayment":
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings                 and "core_payments" in node.value:
            return True
    return False


def test_no_app_module_reads_core_payments_outside_the_reviewed_allowlist() -> None:
    """Guardian: si alguien empieza a leer `core_payments` (KPIs, dashboards), este test obliga a revisar el efecto
    de las filas FAILED de Toku (excluirlas con `source_status = 'FAILED'`) antes de ampliar la lista."""
    allowed = {
        "app/models/core.py",
        "app/services/core_vp_etl.py",
        "app/services/core_toku_etl.py",
        "app/services/core_payku_etl.py",
        "app/services/core_tch_etl.py",
        "app/services/toku_failed_payments.py",
        "app/services/toku_rejection_projection.py",
        "app/services/vp_rejection_capture.py",
        "app/services/vp_report_import.py",  # revisado: solo UPDATE de charge_id (vinculo pago->cobro de VirtualPOS)
    }
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*.py")
        if _references_core_payments(path)
    }
    unexpected = found - allowed
    assert not unexpected, f"Nuevo lector de core_payments sin revisar frente a las filas FAILED de Toku: {sorted(unexpected)}"


# -- integracion con el ETL y bandera ------------------------------------------------------------------------------------

def _stub_etl(monkeypatch, calls: list[str]) -> None:
    monkeypatch.setattr(core_toku_etl, "materialize_core_clients", lambda *a, **k: 0)
    for name in ("_materialize_client_attributes", "_materialize_subscriptions", "_materialize_stub_subscriptions",
                 "_materialize_charges", "_materialize_payments"):
        monkeypatch.setattr(core_toku_etl, name, lambda *a, _n=name, **k: calls.append(_n) or 0)
    monkeypatch.setattr(core_toku_etl, "project_toku_rejections", lambda db, **k: calls.append("project") or {"charges_updated": 0})
    monkeypatch.setattr(core_toku_etl, "materialize_failed_toku_payments",
                        lambda db, **k: calls.append("failed") or {"written": 4})


def test_flag_is_off_by_default_and_the_etl_does_not_materialize(db_session: Session, monkeypatch) -> None:  # noqa: F811
    assert settings.toku_materialize_failed_payments is False
    calls: list[str] = []
    _stub_etl(monkeypatch, calls)
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert "failed" not in calls and "failed_payments_materialized" not in result


def test_flag_on_materializes_after_payments_and_the_projection(db_session: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(settings, "toku_materialize_failed_payments", True)
    calls: list[str] = []
    _stub_etl(monkeypatch, calls)
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert calls[-2:] == ["project", "failed"]
    assert result["failed_payments_materialized"] == 4


def test_a_failure_in_the_materialization_does_not_break_the_etl(db_session: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(settings, "toku_materialize_failed_payments", True)
    calls: list[str] = []
    _stub_etl(monkeypatch, calls)

    def boom(db, **k):
        raise RuntimeError("falla")

    monkeypatch.setattr(core_toku_etl, "materialize_failed_toku_payments", boom)
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert result["failed_payments_materialized"] == 0 and result["charges_rejection_projected"] == 0


def test_maintenance_script_is_dry_run_unless_apply_is_explicit() -> None:
    path = ROOT / "scripts" / "maintenance" / "materialize_toku_failed_payments.py"
    spec = importlib.util.spec_from_file_location("materialize_toku_failed_payments_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.parse_args([]).apply is False
    assert module.parse_args(["--apply"]).apply is True
