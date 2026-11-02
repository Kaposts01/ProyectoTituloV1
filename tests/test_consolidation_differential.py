"""SYNC-O-07 / SYNC-D-07: consolidacion diferencial (datos sinteticos, sin PII).

- Guarda IS DISTINCT FROM: una segunda consolidacion sin cambios escribe 0 filas y 0 eventos.
- Regresion de `status_change_events`: un cambio real da exactamente un evento; nada espurio al repetir.
- Lectura diferencial (bandera): solo se leen las filas del canal cambiadas desde la ultima consolidacion.
- `upsert_channel` solo mueve `updated_at` cuando la fila cambia.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.status_change import StatusChangeEvent
from app.models.sync_cursor import SyncCursor
from app.models.tch import TchSubscription, TchTransaction
from app.models.toku_channel import TokuCustomer, TokuInvoice
from app.models.vp import VpCharge, VpClient, VpPayment, VpSubscription
from app.services import channel_consolidation
from app.services.channel_consolidation import consolidate_to_centralized
from app.services.channel_store import store_toku_resources

OLD = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed(db: Session) -> None:
    db.add_all([
        VpClient(platform="virtualpos1", external_id="dif-c1", first_name="Uno", status="ACTIVO"),
        VpSubscription(platform="virtualpos1", external_id="dif-s1", client_external_id="dif-c1", status="ACTIVA",
                       amount="5000"),
        VpCharge(platform="virtualpos1", external_id="dif-ch1", subscription_external_id="dif-s1", status="PENDIENTE",
                 amount="5000", charge_date="2026-10-01"),
        VpPayment(platform="virtualpos1", external_id="dif-p1", charge_external_id="dif-ch1", status="PAGADO",
                  amount="5000"),
        TokuCustomer(external_id="dif-tc1", name="Toku Uno", status="active"),
        TokuInvoice(external_id="dif-ti1", subscription_id="dif-ts1", status="UNPAID", amount="7000", currency="CLP",
                    due_date="2026-10-05"),
        PaykuSubscription(external_id="dif-ps1", client_id="dif-pc1", status="active", amount="3000"),
        PaykuTransaction(external_id="dif-pt1", subscription_id="dif-ps1", status="pending", amount="3000",
                         currency="CLP"),
        TchSubscription(file_number=990001, client_rut="11111111-1", status="ACTIVA", amount="4000"),
        TchTransaction(file_number=990001, period="2026-09", dedupe_key="990001|2026-09|1", status="RECHAZADA",
                       amount="4000", charge_date="2026-09-05"),
    ])
    db.flush()


def _events(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StatusChangeEvent))


def _run(db: Session, sources: list[str], **kwargs) -> list[dict]:
    timings: list[dict] = []
    consolidate_to_centralized(db, sources, timings=timings, run_id=uuid.uuid4(), **kwargs)
    return timings


def _by_fn(timings: list[dict], key: str) -> dict[str, int]:
    return {f"{t['source']}.{t['fn']}": t[key] for t in timings}


ALL = ["virtualpos", "toku", "payku", "tch"]


def test_second_consolidation_without_changes_writes_zero_rows_and_zero_events(db_session: Session) -> None:
    _seed(db_session)
    first = _run(db_session, ALL)
    assert sum(t["written"] for t in first) > 0
    events_after_first = _events(db_session)
    assert events_after_first > 0

    second = _run(db_session, ALL)
    assert _by_fn(second, "written") == {name: 0 for name in _by_fn(second, "written")}
    read = lambda timings: {k: v for k, v in _by_fn(timings, "records").items() if not k.startswith("core.")}  # noqa: E731
    assert read(second) == read(first)  # leyo lo mismo (sin bandera diferencial)
    assert _events(db_session) == events_after_first


def test_identical_rows_are_not_rewritten(db_session: Session) -> None:
    """La tupla canonica no se reescribe: xmin (id de la transaccion que escribio la fila) no cambia."""
    _seed(db_session)
    _run(db_session, ["virtualpos"])
    xmin_sql = "SELECT xmin::text FROM charges WHERE source = 'virtualpos1' AND external_id = 'dif-ch1'"
    from sqlalchemy import text

    before = db_session.execute(text(xmin_sql)).scalar_one()
    _run(db_session, ["virtualpos"])
    # Cada consolidacion escribe dentro de un SAVEPOINT nuevo (subtransaccion con su propio XID): una reescritura
    # cambiaria el xmin de la tupla aun dentro de la transaccion del test.
    assert db_session.execute(text(xmin_sql)).scalar_one() == before
    assert db_session.scalars(select(Charge.status).where(Charge.external_id == "dif-ch1")).one() == "PENDIENTE"


def test_status_change_events_regression_exactly_one_event_per_real_change(db_session: Session) -> None:
    _seed(db_session)
    _run(db_session, ALL)
    base = _events(db_session)

    charge = db_session.scalars(select(VpCharge).where(VpCharge.external_id == "dif-ch1")).one()
    charge.status = "PAGADO"
    db_session.flush()
    timings = _run(db_session, ALL)
    written = _by_fn(timings, "written")
    assert written["virtualpos.vp_charges"] == 1
    assert sum(written.values()) == 1  # nada mas se reescribe
    new = list(db_session.scalars(
        select(StatusChangeEvent).where(StatusChangeEvent.event_kind == "status_changed")
    ))
    assert [(e.source, e.external_id, e.from_value, e.to_value) for e in new] == [
        ("virtualpos1", "dif-ch1", "PENDIENTE", "PAGADO")
    ]
    assert _events(db_session) == base + 1

    # Repetir sin cambios: ni filas ni eventos (antes la reescritura completa no generaba eventos, pero si escrituras).
    again = _run(db_session, ALL)
    assert sum(_by_fn(again, "written").values()) == 0
    assert _events(db_session) == base + 1


def test_canonical_value_restored_if_channel_row_unchanged_but_canonical_drifted(db_session: Session) -> None:
    """La guarda compara contra la fila canonica: si alguien la altero, la consolidacion la corrige."""
    _seed(db_session)
    _run(db_session, ["toku"])
    db_session.execute(update(Client).where(Client.external_id == "dif-tc1").values(first_name="Alterado"))
    timings = _run(db_session, ["toku"])
    assert _by_fn(timings, "written")["toku.toku_clients"] == 1
    assert db_session.scalars(select(Client.first_name).where(Client.external_id == "dif-tc1")).one() == "Toku Uno"


# ── Lectura diferencial (bandera) ───────────────────────────────────────────────────────────────────────


def _age_channel_rows(db: Session) -> None:
    for model in (VpClient, VpSubscription, VpCharge, VpPayment, TokuCustomer, TokuInvoice, PaykuSubscription,
                  PaykuTransaction):
        db.execute(update(model).values(updated_at=OLD))
    db.flush()


def test_differential_reads_only_changed_rows(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "consolidation_differential_overlap_minutes", 0)
    _seed(db_session)
    _age_channel_rows(db_session)

    first = _run(db_session, ["virtualpos", "toku", "payku"], differential=True)  # sin marca: lectura completa
    records = _by_fn(first, "records")
    assert records["virtualpos.vp_charges"] == 1 and records["payku.payku_transactions"] == 1
    marks = db_session.scalars(
        select(SyncCursor.resource).where(SyncCursor.source == channel_consolidation.CURSOR_SOURCE)
    ).all()
    assert "virtualpos.vp_charges" in marks and "toku.toku_subscriptions" not in marks

    second = _run(db_session, ["virtualpos", "toku", "payku"], differential=True)
    records = _by_fn(second, "records")
    for name in ("virtualpos.vp_clients", "virtualpos.vp_charges", "virtualpos.vp_payments",
                 "virtualpos.vp_subscriptions", "toku.toku_clients", "toku.toku_invoices",
                 "payku.payku_subscriptions", "payku.payku_transactions"):
        assert records[name] == 0, name
    assert sum(_by_fn(second, "written").values()) == 0

    # Un cobro VP cambia: se lee el cobro y tambien su suscripcion (el monto vigente sale de los cobros).
    charge = db_session.scalars(select(VpCharge).where(VpCharge.external_id == "dif-ch1")).one()
    charge.status = "PAGADO"
    tx = db_session.scalars(select(PaykuTransaction).where(PaykuTransaction.external_id == "dif-pt1")).one()
    tx.status = "success"
    db_session.flush()
    third = _run(db_session, ["virtualpos", "toku", "payku"], differential=True)
    records = _by_fn(third, "records")
    assert records["virtualpos.vp_charges"] == 1 and records["virtualpos.vp_subscriptions"] == 1
    assert records["virtualpos.vp_payments"] == 0
    assert records["payku.payku_transactions"] == 1 and records["payku.payku_subscriptions"] == 1
    assert db_session.scalars(select(Charge.status).where(Charge.external_id == "dif-ch1")).one() == "PAGADO"
    assert db_session.scalars(select(Payment.status).where(Payment.external_id == "dif-pt1")).one() == "success"


def test_baseline_and_explicit_flag_off_always_read_everything(db_session: Session,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "consolidation_differential_enabled", True)
    monkeypatch.setattr(settings, "consolidation_differential_overlap_minutes", 0)
    _seed(db_session)
    _age_channel_rows(db_session)
    _run(db_session, ["virtualpos"])  # con la bandera: deja marca
    assert _by_fn(_run(db_session, ["virtualpos"]), "records")["virtualpos.vp_charges"] == 0
    assert _by_fn(_run(db_session, ["virtualpos"], differential=False), "records")["virtualpos.vp_charges"] == 1
    assert _by_fn(_run(db_session, ["virtualpos"], baseline=True), "records")["virtualpos.vp_charges"] == 1


def test_flag_is_off_by_default() -> None:
    assert type(settings).model_fields["consolidation_differential_enabled"].default is False


# ── upsert_channel: updated_at solo con cambios reales ───────────────────────────────────────────────────


def test_upsert_channel_moves_updated_at_only_on_real_change(db_session: Session) -> None:
    record = {"id": "dif-tc9", "name": "Nueve", "email": None, "status": "active"}
    store_toku_resources(db_session, "customer", [record])
    db_session.execute(update(TokuCustomer).where(TokuCustomer.external_id == "dif-tc9").values(updated_at=OLD))

    store_toku_resources(db_session, "customer", [record])  # identico: no se toca
    row = db_session.scalars(select(TokuCustomer).where(TokuCustomer.external_id == "dif-tc9")).one()
    db_session.refresh(row)
    assert row.updated_at == OLD

    store_toku_resources(db_session, "customer", [{**record, "status": "inactive"}])
    db_session.refresh(row)
    assert row.status == "inactive" and row.updated_at > OLD


def test_scoped_consolidation_unaffected(db_session: Session) -> None:
    """MGT-06: la consolidacion por suscripcion sigue igual (sin marca ni filtro diferencial)."""
    _seed(db_session)
    total = channel_consolidation.consolidate_subscription(db_session, "virtualpos1", "dif-s1")
    assert total == 2
    assert db_session.scalars(select(Subscription.status).where(Subscription.external_id == "dif-s1")).one() == "ACTIVA"
