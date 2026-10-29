"""VP-PAR-02 (parte 3) / RJ-04: carga idempotente de los reportes PAT de VirtualPOS. CSV sinteticos."""

import os
import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from vp_reports_support import (
    PEPPER,
    PII_SENTINELS,
    charge_id,
    payment_row,
    rejected_payment_row,
    sub_id,
    subscription_row,
    uuid_of,
    write_report,
)

from app.core.config import settings
from app.db.session import engine
from app.models.core import CoreCharge, CorePayment
from app.models.rejection import PaymentRejectionDetail
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent
from app.models.vp import VpCharge, VpPayment, VpSubscription
from app.models.vp_report import VpReportFile, VpReportPayment, VpReportSubscription
from app.services import vp_report_import as imp
from app.services.vp_report_import import ReportImportError, import_report

P1, P2 = "virtualpos1", "virtualpos2"
EPOCH_OLD, EPOCH_NEW = 1792000000, 1792500000


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


@pytest.fixture(autouse=True)
def pepper(monkeypatch):
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)


def _csv(tmp_path, kind, rows, epoch=EPOCH_NEW, name=None, **kw):
    prefix = "TransaccionesPAT" if kind == "transacciones" else "SuscriptoresPAT"
    return write_report(tmp_path / (name or f"{prefix}-VirtualPOS-{epoch}.csv"), kind, rows, **kw)


def _import(db, path):
    return import_report(db, path, filename=path.name, uploaded_by_user_id=None)


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def _seed_vp(db, n, platform=P1, *, charge=True, sub=False, payment=False):
    if charge:
        db.add(VpCharge(platform=platform, external_id=charge_id(n), subscription_external_id=sub_id(n), status="rechazado"))
    if sub:
        db.add(VpSubscription(platform=platform, external_id=sub_id(n), status="ACTIVA"))
    if payment:
        db.add(VpPayment(platform=platform, external_id=uuid_of(n), status="rechazado"))
    db.flush()


def _detail(db, n):
    return db.scalar(select(PaymentRejectionDetail).where(PaymentRejectionDetail.charge_external_id == charge_id(n)))


def _all_report_text(db) -> str:
    parts = []
    for table in ("vp_report_files", "vp_report_payments", "vp_report_subscriptions", "payment_rejection_details"):
        parts += [r[0] for r in db.execute(text(f"SELECT to_jsonb(t)::text FROM {table} t"))]
    return "\n".join(parts)


# ---- carga basica ----------------------------------------------------------------------------------------


def test_import_payments_counts_content_and_no_pii(db_session, tmp_path):
    rows = [payment_row(1), rejected_payment_row(2), payment_row(3, **{"Monto de cargo": "abc"})]
    path = _csv(tmp_path, "transacciones", rows)
    s = _import(db_session, path)
    assert s.report_type == "transacciones" and not s.already_loaded and s.status == "completed"
    assert (s.rows_total, s.rows_new, s.rows_updated, s.rows_skipped) == (3, 2, 0, 1)
    assert s.skip_reasons == {"invalid_amount": 1}
    f = db_session.scalar(select(VpReportFile))
    assert f.status == "completed" and f.filename == path.name and len(f.file_sha256) == 64
    assert f.generated_at == datetime.fromtimestamp(EPOCH_NEW, tz=UTC)
    assert (str(f.window_start), str(f.window_end)) == ("2026-10-05", "2026-10-05")
    assert (f.rows_total, f.rows_new, f.rows_skipped) == (3, 2, 1) and f.finished_at is not None
    paid = db_session.scalar(select(VpReportPayment).where(VpReportPayment.charge_external_id == charge_id(1)))
    assert paid.amount == Decimal("9990.00") and paid.payment_medium == "Débito" and paid.card_last4 == "1234"
    assert paid.platform is None and paid.platform_status == "unresolved" and paid.last_file_id == f.id
    assert len(paid.seller_code_hash) == 64
    assert not any(sentinel in _all_report_text(db_session) for sentinel in PII_SENTINELS)


def test_import_subscriptions(db_session, tmp_path):
    _seed_vp(db_session, 1, P2, charge=False, sub=True)
    rows = [subscription_row(1), subscription_row(2, **{"Estado de suscripción": "SUSCRIPCION_FALLIDA", "Motivo de rechazo": "Rechazo general"})]
    s = _import(db_session, _csv(tmp_path, "suscriptores", rows))
    assert (s.rows_new, s.rows_skipped) == (2, 0) and s.platforms == {"resolved": 1, "ambiguous": 0, "unresolved": 1}
    a = db_session.scalar(select(VpReportSubscription).where(VpReportSubscription.subscription_external_id == sub_id(1)))
    b = db_session.scalar(select(VpReportSubscription).where(VpReportSubscription.subscription_external_id == sub_id(2)))
    assert (a.platform, a.platform_status) == (P2, "resolved") and a.card_last4 == "1234" and a.card_type == "TD"
    assert (b.platform, b.platform_status, b.rejection_reason) == (None, "unresolved", "Rechazo general")
    assert not any(sentinel in _all_report_text(db_session) for sentinel in PII_SENTINELS)


def test_missing_pepper_still_loads_without_seller_hash(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vp_report_hash_pepper", "")
    s = _import(db_session, _csv(tmp_path, "transacciones", [payment_row(1)]))
    assert "seller_hash_skipped_no_pepper" in s.warnings
    assert db_session.scalar(select(VpReportPayment.seller_code_hash)) is None


def test_format_errors_do_not_register_a_file(db_session, tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(imp.ReportFormatError):
        _import(db_session, bad)
    assert _count(db_session, VpReportFile) == 0


# ---- idempotencia y hash ---------------------------------------------------------------------------------


def test_same_file_twice_is_rejected_by_sha256_even_if_renamed(db_session, tmp_path):
    path = _csv(tmp_path, "transacciones", [payment_row(1), payment_row(2)])
    first = _import(db_session, path)
    copy = tmp_path / "otro-nombre.csv"
    copy.write_bytes(path.read_bytes())
    second = import_report(db_session, copy, filename=copy.name, uploaded_by_user_id=None)
    assert second.already_loaded and second.status == "already_loaded" and second.file_id == first.file_id
    assert _count(db_session, VpReportFile) == 1 and _count(db_session, VpReportPayment) == 2


def test_reimport_with_different_bytes_is_an_idempotent_upsert(db_session, tmp_path):
    rows = [payment_row(1), payment_row(2)]
    _import(db_session, _csv(tmp_path, "transacciones", rows, epoch=EPOCH_OLD))
    s = _import(db_session, _csv(tmp_path, "transacciones", [*rows, payment_row(3)], epoch=EPOCH_NEW))
    assert (s.rows_new, s.rows_updated) == (1, 2) and _count(db_session, VpReportPayment) == 3
    assert _count(db_session, VpReportFile) == 2


def test_running_file_blocks_a_concurrent_load_and_failed_is_retried(db_session, tmp_path):
    path = _csv(tmp_path, "transacciones", [payment_row(1)])
    _import(db_session, path)
    f = db_session.scalar(select(VpReportFile))
    f.status = "running"
    db_session.commit()
    with pytest.raises(ReportImportError) as err:
        _import(db_session, path)
    assert err.value.label == "carga_en_curso"
    f.status = "failed"
    db_session.commit()
    assert _import(db_session, path).status == "completed"
    assert _count(db_session, VpReportFile) == 1


# ---- frescura --------------------------------------------------------------------------------------------


def test_older_file_never_overwrites_newer_data_in_any_order(db_session, tmp_path):
    new_rows = [payment_row(1, **{"Monto de cargo": "20000", "Alias POS": "NUEVO"})]
    old_rows = [payment_row(1, **{"Monto de cargo": "10000", "Alias POS": "VIEJO"}), payment_row(2)]
    new_path = _csv(tmp_path, "transacciones", new_rows, epoch=EPOCH_NEW)
    old_path = _csv(tmp_path, "transacciones", old_rows, epoch=EPOCH_OLD)

    def final_state():
        rows = db_session.execute(
            select(VpReportPayment.charge_external_id, VpReportPayment.amount, VpReportPayment.pos_alias).order_by(VpReportPayment.charge_external_id)
        ).all()
        return [tuple(r) for r in rows]

    _import(db_session, new_path)
    s = _import(db_session, old_path)
    assert (s.rows_new, s.rows_stale) == (1, 1)
    forward = final_state()
    db_session.execute(text("DELETE FROM vp_report_payments"))
    db_session.execute(text("DELETE FROM vp_report_files"))
    db_session.commit()
    _import(db_session, old_path)
    _import(db_session, new_path)
    assert final_state() == forward
    assert forward[0] == (charge_id(1), Decimal("20000.00"), "NUEVO")


# ---- resolucion de plataforma ----------------------------------------------------------------------------


def test_platform_resolution_uses_best_signal_and_never_forces_ambiguity(db_session, tmp_path):
    _seed_vp(db_session, 1, P1)  # por cobro
    _seed_vp(db_session, 2, P2, charge=False, payment=True)  # solo por el UUID del pago
    _seed_vp(db_session, 3, P1, charge=True)  # cobro en VP1 ...
    db_session.add(VpSubscription(platform=P2, external_id=sub_id(3), status="ACTIVA"))  # ... suscripcion en VP2
    _seed_vp(db_session, 5, P1, charge=False, sub=True)  # solo por la suscripcion
    db_session.flush()
    rows = [rejected_payment_row(n) for n in (1, 2, 3, 4, 5)]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    got = {
        r.charge_external_id: (r.platform, r.platform_status)
        for r in db_session.scalars(select(VpReportPayment))
    }
    assert got[charge_id(1)] == (P1, "resolved") and got[charge_id(2)] == (P2, "resolved")
    assert got[charge_id(3)] == (None, "ambiguous") and got[charge_id(4)] == (None, "unresolved")
    assert got[charge_id(5)] == (P1, "resolved")
    assert s.platforms == {"resolved": 3, "ambiguous": 1, "unresolved": 1}
    # solo las filas resueltas escriben glosa; las ambiguas/sin resolver quedan marcadas y sin forzar
    sources = {d.charge_external_id: d.source for d in db_session.scalars(select(PaymentRejectionDetail))}
    assert sources == {charge_id(1): P1, charge_id(2): P2, charge_id(5): P1}


def test_late_resolution_completes_pending_rows_idempotently(db_session, tmp_path):
    _import(db_session, _csv(tmp_path, "transacciones", [rejected_payment_row(1)]))
    assert _count(db_session, PaymentRejectionDetail) == 0
    _seed_vp(db_session, 1, P2)  # el sync trae el cobro despues
    first = imp.reconcile(db_session)
    again = imp.reconcile(db_session)
    assert first["platform_changes"]["resolved"] == 1 and first["rejections"]["inserted"] == 1
    assert again["platform_changes"]["resolved"] == 0 and again["rejections"]["inserted"] == 0
    assert _detail(db_session, 1).source == P2 and _count(db_session, PaymentRejectionDetail) == 1


# ---- glosa de rechazo (RJ-04) ----------------------------------------------------------------------------


def test_rejection_details_use_report_pat_and_core_fields(db_session, tmp_path):
    for n in (1, 2, 3, 4):
        _seed_vp(db_session, n, P1)
    rows = [
        rejected_payment_row(1, "-11", "Excede límite de reintentos de rechazo"),
        rejected_payment_row(2, "-2119", "Excede saldo maximo"),
        rejected_payment_row(3, "", ""),
        payment_row(4),  # pagado: nunca genera glosa
    ]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    assert s.rejections == {"inserted": 3, "markers_replaced": 0, "reasons_new": 2}
    d1, d2, d3 = (_detail(db_session, n) for n in (1, 2, 3))
    assert (d1.source, d1.code, d1.reason, d1.capture_source) == (P1, "-11", "Excede límite de reintentos de rechazo", "report_pat")
    assert d1.payment_external_id == uuid_of(1) and d1.subscription_external_id == sub_id(1)
    assert d1.amount == Decimal("9990.00") and d1.acquirer_code is None
    assert d1.rejected_at == datetime(2026, 10, 5, 3, 0, tzinfo=UTC)  # fecha programada a las 00:00 de Chile (UTC-3)
    assert d2.acquirer_code == "-2119" and d2.code == "-2119"
    assert (d3.code, d3.reason) == ("", None)  # marcador: rechazado sin glosa
    assert _detail(db_session, 4) is None


def test_existing_api_detail_wins_and_markers_are_replaced(db_session, tmp_path):
    for n in (1, 2):
        _seed_vp(db_session, n, P1)
    db_session.add_all([
        PaymentRejectionDetail(source=P1, charge_external_id=charge_id(1), payment_external_id=None, code="-3",
                               reason="glosa api", capture_source="api_charges"),
        PaymentRejectionDetail(source=P1, charge_external_id=charge_id(2), code="", capture_source="api_charges"),
    ])
    db_session.commit()
    rows = [rejected_payment_row(1, "-3", "glosa del reporte"), rejected_payment_row(2, "-6", "Rechazo general")]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    d1 = _detail(db_session, 1)
    assert (d1.capture_source, d1.reason) == ("api_charges", "glosa api")  # la API manda: no se duplica
    d2s = db_session.scalars(select(PaymentRejectionDetail).where(PaymentRejectionDetail.charge_external_id == charge_id(2))).all()
    assert [(d.code, d.capture_source) for d in d2s] == [("-6", "report_pat")]  # el marcador se reemplaza
    assert s.rejections["inserted"] == 1 and s.rejections["markers_replaced"] == 1


def test_catalog_and_reason_changed_events_like_rj06(db_session, tmp_path):
    for n in (1, 2, 3):
        _seed_vp(db_session, n, P1)
    rows = [rejected_payment_row(n, "-3", "Excede monto máximo") for n in (1, 2)] + [rejected_payment_row(3, "-6", "Rechazo general")]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    assert s.rejections["reasons_new"] == 2
    catalog = {(c.code, c.reason): c.occurrences for c in db_session.scalars(select(RejectionReasonCatalog).where(RejectionReasonCatalog.source == P1))}
    assert catalog == {("-3", "Excede monto máximo"): 2, ("-6", "Rechazo general"): 1}
    kinds = db_session.scalars(select(StatusChangeEvent.event_kind).where(StatusChangeEvent.source == P1)).all()
    assert kinds.count("reason_changed") == 2
    imp.reconcile(db_session)  # idempotente: ni ocurrencias ni eventos nuevos
    assert db_session.scalars(select(StatusChangeEvent.event_kind).where(StatusChangeEvent.source == P1)).all().count("reason_changed") == 2


# ---- vinculo pago -> cobro -------------------------------------------------------------------------------


def _core(db, n, platform=P1, *, charge=True, payment=True, linked=False):
    cc = CoreCharge(source=platform, external_id=charge_id(n)) if charge else None
    if cc:
        db.add(cc)
        db.flush()
    if payment:
        db.add(CorePayment(source=platform, external_id=uuid_of(n), charge_id=cc.id if (cc and linked) else None))
    db.flush()
    return cc


def test_payment_charge_link_fills_only_nulls_and_is_idempotent(db_session, tmp_path):
    for n in (1, 2, 3):
        _seed_vp(db_session, n, P1, payment=True)
        _core(db_session, n)
    db_session.add(VpPayment(platform=P1, external_id="U-preexistente", charge_external_id="cid_otro"))
    db_session.flush()
    rows = [payment_row(1), rejected_payment_row(2), payment_row(3, **{"UUID transacción": "U-preexistente"})]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    assert s.links == {"vp_payments": 2, "core_payments": 2}
    vp = {p.external_id: p.charge_external_id for p in db_session.scalars(select(VpPayment))}
    assert vp[uuid_of(1)] == charge_id(1) and vp[uuid_of(2)] == charge_id(2)
    assert vp["U-preexistente"] == "cid_otro"  # nunca pisa un vinculo existente
    cp = {p.external_id: p.charge_id for p in db_session.scalars(select(CorePayment))}
    ids = {c.external_id: c.id for c in db_session.scalars(select(CoreCharge))}
    assert cp[uuid_of(1)] == ids[charge_id(1)] and cp[uuid_of(2)] == ids[charge_id(2)] and cp[uuid_of(3)] is None
    assert imp.reconcile(db_session)["links"] == {"vp_payments": 0, "core_payments": 0}


def test_uuid_shared_by_two_charges_is_never_linked(db_session, tmp_path):
    _seed_vp(db_session, 1, P1, payment=True)
    _seed_vp(db_session, 2, P1)
    rows = [payment_row(1), payment_row(2, **{"UUID transacción": uuid_of(1)})]
    s = _import(db_session, _csv(tmp_path, "transacciones", rows))
    assert s.links["vp_payments"] == 0
    assert db_session.scalar(select(VpPayment.charge_external_id)) is None


# ---- atomicidad y errores sin PII ------------------------------------------------------------------------


def test_failure_rolls_back_the_whole_file_and_labels_without_pii(db_session, tmp_path, monkeypatch, caplog):
    _seed_vp(db_session, 1, P1)
    path = _csv(tmp_path, "transacciones", [rejected_payment_row(1), payment_row(2)])

    def boom(*_a, **_k):
        raise RuntimeError("SENTINELA-NOMBRE 00.000.001-K")

    monkeypatch.setattr(imp, "_apply_rejection_details", boom)
    with caplog.at_level("DEBUG"), pytest.raises(ReportImportError) as err:
        _import(db_session, path)
    assert err.value.label == "rejections:RuntimeError"
    assert _count(db_session, VpReportPayment) == 0 and _count(db_session, PaymentRejectionDetail) == 0
    f = db_session.scalar(select(VpReportFile))
    assert f.status == "failed" and f.error_label == "rejections:RuntimeError"
    text_out = str(err.value) + (err.value.detail or "") + caplog.text
    assert "SENTINELA" not in text_out and "00.000.001-K" not in text_out
    monkeypatch.undo()
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)
    assert _import(db_session, path).status == "completed"  # el fallido se reutiliza
    assert _count(db_session, VpReportFile) == 1 and _count(db_session, VpReportPayment) == 2


# ---- volumen ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("VP_PERF_TEST") != "1", reason="prueba de rendimiento: VP_PERF_TEST=1")
def test_performance_about_90k_synthetic_rows(db_session, tmp_path):
    n_pay, n_sub = 81_000, 9_000
    for n in range(1, 3001):  # una parte con senales para ejercitar resolucion, glosa y vinculo
        db_session.add(VpCharge(platform=P1 if n % 2 else P2, external_id=charge_id(n), subscription_external_id=sub_id(n), status="rechazado"))
        db_session.add(VpPayment(platform=P1 if n % 2 else P2, external_id=uuid_of(n)))
    db_session.commit()
    pay_rows = [rejected_payment_row(n, "-11", "Excede límite") if n % 3 == 0 else payment_row(n) for n in range(1, n_pay + 1)]
    sub_rows = [subscription_row(n) for n in range(1, n_sub + 1)]
    p1 = _csv(tmp_path, "transacciones", pay_rows)
    p2 = _csv(tmp_path, "suscriptores", sub_rows)
    t0 = time.perf_counter()
    s1 = _import(db_session, p1)
    t1 = time.perf_counter()
    s2 = _import(db_session, p2)
    t2 = time.perf_counter()
    changed = [payment_row(1, **{"Alias POS": "OTRO"}), *pay_rows[1:]]  # otro contenido: otro sha256
    again = _import(db_session, _csv(tmp_path, "transacciones", changed, epoch=EPOCH_NEW + 1))
    t3 = time.perf_counter()
    imp.reconcile(db_session)  # pasada idempotente sobre todo lo cargado
    t4 = time.perf_counter()
    print(
        f"\nVP_PERF payments={s1.rows_total} in {t1 - t0:.1f}s; subs={s2.rows_total} in {t2 - t1:.1f}s; "
        f"reimport={again.rows_updated} in {t3 - t2:.1f}s; reconcile={t4 - t3:.1f}s"
    )
    assert s1.rows_new == n_pay and s2.rows_new == n_sub and again.rows_updated == n_pay
    assert (t1 - t0) < 120 and (t2 - t1) < 60 and (t3 - t2) < 120
