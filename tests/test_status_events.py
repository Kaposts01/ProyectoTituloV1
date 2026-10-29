"""SYNC-D-02/03: eventos de cambio de estado/monto enganchados en la consolidacion (datos sinteticos, sin PII)."""

import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Subscription
from app.models.payku_channel import PaykuTransaction
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent
from app.models.tch import TchTransaccion
from app.models.toku_channel import TokuInvoice
from app.models.vp import VpCharge, VpSubscription
from app.services import channel_consolidation, status_events
from app.services.channel_consolidation import (
    _upsert_centralized,
    consolidate_to_centralized,
)


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


def _events(db: Session, **filters) -> list[StatusChangeEvent]:
    stmt = select(StatusChangeEvent).order_by(StatusChangeEvent.detected_at, StatusChangeEvent.event_kind)
    for k, v in filters.items():
        stmt = stmt.where(getattr(StatusChangeEvent, k) == v)
    return list(db.scalars(stmt))


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StatusChangeEvent))


# ── Un caso por canal: (fuente, alta, cambio de estado/monto) ───────────────────────────────────────────


def _vp_charge(db: Session, status: str = "PENDIENTE", amount: str = "5000"):
    row = db.scalars(select(VpCharge).where(VpCharge.external_id == "vpc-1")).first()
    if row is None:
        row = VpCharge(external_id="vpc-1", platform="virtualpos1", subscription_external_id="vps-1", status=status, amount=amount)
        db.add(row)
    row.status, row.amount = status, amount
    db.flush()


def _toku_invoice(db: Session, status: str = "UNPAID", amount: str = "7000"):
    row = db.scalars(select(TokuInvoice).where(TokuInvoice.external_id == "in_t1")).first()
    if row is None:
        row = TokuInvoice(external_id="in_t1", subscription_id="sub_t1", currency="CLP", due_date="2026-10-01")
        db.add(row)
    row.status, row.amount = status, amount
    db.flush()


def _payku_tx(db: Session, status: str = "pending", amount: str = "3000"):
    row = db.scalars(select(PaykuTransaction).where(PaykuTransaction.external_id == "trx_p1")).first()
    if row is None:
        row = PaykuTransaction(external_id="trx_p1", subscription_id="sub_p1", currency="CLP")
        db.add(row)
    row.status, row.amount = status, amount
    db.flush()


def _tch_tx(db: Session, status: str = "RECHAZADA", amount: str = "4000", code: str | None = None, reason: str | None = None,
            key: str = "tch-1-2026-09"):
    row = db.scalars(select(TchTransaccion).where(TchTransaccion.dedupe_key == key)).first()
    if row is None:
        row = TchTransaccion(numero_ficha=900001, periodo="2026-09", dedupe_key=key, estado=status)
        db.add(row)
    row.estado, row.monto, row.codigo_respuesta, row.razon_rechazo = status, amount, code, reason
    db.flush()


CASES = {
    "virtualpos": (_vp_charge, "virtualpos1", "charge", ("PENDIENTE", "PAGADO")),
    "toku": (_toku_invoice, "toku", "charge", ("UNPAID", "PAID")),
    "payku": (_payku_tx, "payku", "payment", ("pending", "success")),
    "tch": (_tch_tx, "tch", "charge", ("RECHAZADA", "ACEPTADA")),
}


@pytest.mark.parametrize("channel", list(CASES))
def test_alta_cambio_de_estado_de_monto_y_sin_cambio(db_session: Session, channel: str) -> None:
    setup, source, entity, (first, second) = CASES[channel]
    run = uuid.uuid4()

    setup(db_session, first)
    consolidate_to_centralized(db_session, [channel], run_id=run)
    created = _events(db_session, source=source, entity_type=entity, event_kind="created")
    assert len(created) == 1 and created[0].is_baseline is False and created[0].run_id == run
    assert created[0].from_value is None and created[0].to_value == first
    assert _count(db_session) == len(_events(db_session)) >= 1

    before = _count(db_session)  # sin cambio: nada nuevo
    consolidate_to_centralized(db_session, [channel], run_id=uuid.uuid4())
    assert _count(db_session) == before

    setup(db_session, second)  # cambio de estado
    consolidate_to_centralized(db_session, [channel], run_id=uuid.uuid4())
    changed = _events(db_session, source=source, entity_type=entity, event_kind="status_changed")
    assert [(e.from_value, e.to_value, e.field) for e in changed] == [(first, second, "status")]

    if channel == "payku":  # los pagos solo vigilan estado
        return
    setup(db_session, second, "9990")  # cambio de monto
    consolidate_to_centralized(db_session, [channel], run_id=uuid.uuid4())
    amount_ev = _events(db_session, source=source, entity_type=entity, event_kind="amount_changed")
    assert len(amount_ev) == 1 and amount_ev[0].to_value == "9990" and amount_ev[0].amount == Decimal("9990.00")
    assert amount_ev[0].from_value in {"5000", "7000", "4000"}


def test_misma_corrida_repetida_no_duplica_eventos(db_session: Session) -> None:
    run = uuid.uuid4()
    _vp_charge(db_session)
    consolidate_to_centralized(db_session, ["virtualpos"], run_id=run)
    _vp_charge(db_session, "PAGADO")
    # Se simula el reproceso de la misma corrida: los previos aun son los viejos, mismo run_id.
    rows = [{"source": "virtualpos1", "external_id": "vpc-1", "subscription_external_id": "vps-1", "status": "PAGADO",
             "amount": "5000"}]
    with status_events.event_context(run_id=run, baseline=False):
        first = status_events.emit_status_events(db_session, Charge, rows)
        second = status_events.emit_status_events(db_session, Charge, rows)
    assert first == 1 and second == 0
    assert len(_events(db_session, event_kind="status_changed")) == 1


def test_suscripcion_cambia_de_estado_y_monto_con_su_propio_id(db_session: Session) -> None:
    db_session.add(VpSubscription(external_id="vps-9", platform="virtualpos2", status="ACTIVA", amount="6500"))
    db_session.flush()
    consolidate_to_centralized(db_session, ["virtualpos"], run_id=uuid.uuid4())
    sub = db_session.scalars(select(VpSubscription).where(VpSubscription.external_id == "vps-9")).one()
    sub.status = "CANCELADA"
    db_session.flush()
    consolidate_to_centralized(db_session, ["virtualpos"], run_id=uuid.uuid4())
    ev = _events(db_session, entity_type="subscription", event_kind="status_changed")
    assert [(e.source, e.external_id, e.subscription_external_id, e.from_value, e.to_value) for e in ev] == [
        ("virtualpos2", "vps-9", "vps-9", "ACTIVA", "CANCELADA")
    ]
    assert db_session.scalars(select(Subscription).where(Subscription.external_id == "vps-9")).one().status == "CANCELADA"


def test_monto_equivalente_no_es_cambio(db_session: Session) -> None:
    _toku_invoice(db_session, "UNPAID", "5000")
    consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4())
    before = _count(db_session)
    _toku_invoice(db_session, "UNPAID", "5000.00")
    consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4())
    assert _count(db_session) == before


def test_sin_corrida_usa_token_propio_y_no_duplica(db_session: Session) -> None:
    _vp_charge(db_session)
    consolidate_to_centralized(db_session, ["virtualpos"])  # sin run_id
    ev = _events(db_session, event_kind="created")
    assert len(ev) == 1 and ev[0].run_id is None
    consolidate_to_centralized(db_session, ["virtualpos"])
    assert len(_events(db_session, event_kind="created")) == 1


def test_a_b_a_genera_eventos_distintos(db_session: Session) -> None:
    _toku_invoice(db_session, "UNPAID")
    consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4())
    for status in ("PAID", "UNPAID"):
        _toku_invoice(db_session, status)
        consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4())
    pairs = [(e.from_value, e.to_value) for e in _events(db_session, event_kind="status_changed")]
    assert sorted(pairs) == [("PAID", "UNPAID"), ("UNPAID", "PAID")]


# ── Glosas ──────────────────────────────────────────────────────────────────────────────────────────────


def test_glosa_nueva_emite_reason_changed_una_vez_y_cuenta_ocurrencias(db_session: Session) -> None:
    _tch_tx(db_session, "RECHAZADA", code="51", reason="Fondos insuficientes", key="tch-r1")
    _tch_tx(db_session, "RECHAZADA", code="51", reason="Fondos insuficientes", key="tch-r2")
    consolidate_to_centralized(db_session, ["tch"], run_id=uuid.uuid4())
    assert len(_events(db_session, event_kind="reason_changed")) == 1
    cat = db_session.scalars(select(RejectionReasonCatalog)).one()
    assert (cat.source, cat.code, cat.reason, cat.occurrences) == ("tch", "51", "Fondos insuficientes", 2)

    _tch_tx(db_session, "RECHAZADA", code="51", reason="Fondos insuficientes", key="tch-r3")
    consolidate_to_centralized(db_session, ["tch"], run_id=uuid.uuid4())
    assert len(_events(db_session, event_kind="reason_changed")) == 1  # glosa conocida: sin evento
    assert db_session.scalars(select(RejectionReasonCatalog)).one().occurrences == 3

    _tch_tx(db_session, "RECHAZADA", code="05", reason="No autorizado", key="tch-r4")
    consolidate_to_centralized(db_session, ["tch"], run_id=uuid.uuid4())
    assert len(_events(db_session, event_kind="reason_changed")) == 2


def test_la_glosa_no_se_guarda_en_la_tabla_canonica(db_session: Session) -> None:
    _tch_tx(db_session, "RECHAZADA", code="51", reason="Fondos insuficientes", key="tch-r9")
    consolidate_to_centralized(db_session, ["tch"], run_id=uuid.uuid4())
    charge = db_session.scalars(select(Charge).where(Charge.external_id == "tch-r9")).one()
    assert charge.status == "RECHAZADA"  # las claves transitorias no llegan al INSERT (habria fallado)


# ── Resiliencia ─────────────────────────────────────────────────────────────────────────────────────────


def test_si_la_tabla_de_eventos_falla_la_consolidacion_sigue(db_session: Session, caplog) -> None:
    db_session.execute(text("ALTER TABLE status_change_events RENAME TO status_change_events_off"))  # se revierte al final
    try:
        _vp_charge(db_session)
        failures: list[str] = []
        total = consolidate_to_centralized(db_session, ["virtualpos"], failures=failures)
        assert failures == [] and total >= 1
        assert db_session.scalars(select(Charge).where(Charge.external_id == "vpc-1")).one().status == "PENDIENTE"
        assert any("status_events" in r.message for r in caplog.records)
    finally:
        db_session.rollback()


def test_error_inesperado_en_el_diff_no_tumba_la_consolidacion(db_session: Session, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("diff roto")

    monkeypatch.setattr(status_events, "build_events", boom)
    _vp_charge(db_session)
    failures: list[str] = []
    consolidate_to_centralized(db_session, ["virtualpos"], failures=failures)
    assert failures == [] and _count(db_session) == 0
    assert db_session.scalars(select(Charge).where(Charge.external_id == "vpc-1")).one() is not None


def test_apagado_por_configuracion(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(status_events.settings, "status_events_enabled", False)
    _vp_charge(db_session)
    consolidate_to_centralized(db_session, ["virtualpos"])
    assert _count(db_session) == 0


def test_eventos_sin_datos_personales(db_session: Session) -> None:
    _tch_tx(db_session, "RECHAZADA", code="51", reason="Fondos insuficientes")
    consolidate_to_centralized(db_session, ["tch"], run_id=uuid.uuid4())
    cols = {c.name for c in StatusChangeEvent.__table__.columns}
    assert not cols & {"rut", "email", "name", "first_name", "raw_payload", "social_id", "client_external_id"}


# ── Rendimiento (volumen sintetico moderado) ────────────────────────────────────────────────────────────


def _rows(n: int, status: str, amount: str) -> list[dict]:
    return [
        {"source": "toku", "external_id": f"perf-{i}", "subscription_external_id": f"sub-{i % 500}",
         "client_external_id": None, "amount": amount, "currency": "CLP", "status": status, "charge_date": "2026-10-01",
         "raw_payload": None, "source_record_id": None}
        for i in range(n)
    ]


def test_volumen_sintetico_costo_acotado(db_session: Session, capsys) -> None:
    n = 20_000
    timings: dict[str, float] = {}
    for enabled in (False, True):
        with status_events.event_context(run_id=uuid.uuid4(), baseline=True, enabled=enabled):
            db_session.execute(text("DELETE FROM charges WHERE external_id LIKE 'perf-%'"))
            t0 = time.perf_counter()
            _upsert_centralized(db_session, Charge, "uq_charge_source_external_id", _rows(n, "UNPAID", "5000"))
            timings[f"alta_{enabled}"] = time.perf_counter() - t0
            t0 = time.perf_counter()
            _upsert_centralized(db_session, Charge, "uq_charge_source_external_id", _rows(n, "UNPAID", "5000"))
            timings[f"sin_cambio_{enabled}"] = time.perf_counter() - t0
            t0 = time.perf_counter()
            _upsert_centralized(db_session, Charge, "uq_charge_source_external_id", _rows(n, "PAID", "5000"))
            timings[f"cambio_estado_{enabled}"] = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\n[perf status_events, {n} filas] " + ", ".join(f"{k}={v:.2f}s" for k, v in timings.items()))
    assert _count(db_session) == 2 * n  # altas + cambios de estado de la corrida con eventos (la apagada no emite)
    # Cota holgada (evita falsos rojos): el diff no puede multiplicar el costo de un upsert de ~20k filas.
    assert timings["sin_cambio_True"] < timings["sin_cambio_False"] * 4 + 2
    assert timings["cambio_estado_True"] < timings["cambio_estado_False"] * 5 + 3
    assert channel_consolidation._CHUNK == 2000
