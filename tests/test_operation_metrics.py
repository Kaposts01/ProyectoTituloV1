"""MET-02: `scripts/diagnostics/operation_metrics.py`, metricas de operacion desde tablas existentes (solo lectura).

Datos sinteticos en una ventana del 2001 (lejos de cualquier fila de otros tests) dentro de una transaccion revertida.
Ninguna llamada de red; nunca se conecta a `crm`.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.auth import User
from app.models.billing import BillingChangeRequest, BillingChangeRequestEvent
from app.models.cancellation import (
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)
from app.models.etl_run import EtlRun
from app.models.export_job import ExportJob
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.write_run import WriteRun
from scripts.diagnostics import operation_metrics as om
from scripts.diagnostics import readonly_guard

# Ventana: 14 dias que terminan al cierre del 2001-03-14 (hora de Chile).
WINDOW = om.build_window(14, date(2001, 3, 14))
IN = WINDOW.end - timedelta(days=3)
BEFORE = WINDOW.start - timedelta(days=2)
SECRET_EXT = "SECRET-EXT-9f1c"
SECRET_TEXT = "rut 11.111.111-1 correo socio@example.test"


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


def _sync(source, status, start, seconds=60, records=10):
    return SyncRun(source=source, status=status, started_at=start, finished_at=start + timedelta(seconds=seconds),
                   records_processed=records, error_message=SECRET_TEXT if status == "failed" else None)


@pytest.fixture
def seeded(db_session):
    db = db_session
    user = User(username=f"met02-{uuid.uuid4().hex[:8]}", password_hash="x", is_active=True)
    db.add(user)
    db.flush()
    src = f"met02src{uuid.uuid4().hex[:6]}"
    db.add_all([
        _sync(src, "completed", IN, 60), _sync(src, "completed", IN + timedelta(hours=1), 120),
        _sync(src, "failed", IN + timedelta(hours=2), 30),
        _sync(src, "completed", BEFORE, 999),  # fuera de la ventana: no cuenta en sync_canales
        _sync("billing_met02_job", "completed", IN, 5),
        EtlRun(status="completed", started_at=IN, finished_at=IN + timedelta(seconds=300), records_upserted=7,
               channels_processed=["toku"], channels_failed=[]),
        EtlRun(status="completed", started_at=IN + timedelta(hours=1), finished_at=IN + timedelta(hours=1, seconds=100),
               records_upserted=3, channels_processed=["toku", "payku"], channels_failed=["payku"]),
        WriteRun(source="virtualpos1", resource_type="subscription", external_id=SECRET_EXT, operation="change_amount",
                 status="completed", request_payload={"rut": "11.111.111-1"}, error_message=None,
                 started_at=IN, finished_at=IN + timedelta(seconds=4)),
        WriteRun(source="virtualpos1", resource_type="subscription", external_id=SECRET_EXT, operation="change_amount",
                 status="failed", request_payload={}, error_message=SECRET_TEXT, started_at=IN, finished_at=IN),
        ExportJob(entity="members", status="completed", include_pii=False, rows_written=40, created_at=IN,
                  expires_at=IN + timedelta(days=1)),
        ExportJob(entity="members", status="completed", include_pii=True, rows_written=5, created_at=IN,
                  expires_at=IN + timedelta(days=1)),
    ])
    bcr = BillingChangeRequest(request_type="change_amount", platform="virtualpos1", subscription_external_id=SECRET_EXT,
                               status="ejecutada", requested_by_user_id=user.id, new_amount=9900, rules_snapshot={},
                               requester_comment=SECRET_TEXT, created_at=IN)
    scr = SubscriptionCancellationRequest(channel="toku", subscription_external_id=SECRET_EXT, status="completed",
                                          reason_code="member_request", reason_comment=SECRET_TEXT,
                                          requested_by_user_id=user.id, created_at=IN)
    db.add_all([bcr, scr])
    db.flush()
    db.add_all([
        BillingChangeRequestEvent(request_id=bcr.id, event_type="creada", created_at=IN),
        BillingChangeRequestEvent(request_id=bcr.id, event_type="aplicada", created_at=IN + timedelta(minutes=5)),
        SubscriptionCancellationRequestEvent(request_id=scr.id, event_type="created", created_at=IN),
        SubscriptionCancellationRequestEvent(request_id=scr.id, event_type="completed", created_at=IN),
        SourceRecord(source="alert_state", resource_type="condition", external_id="zzmet02:toku",
                     payload={"active": True, "since": IN.isoformat(), "last_sent_at": IN.isoformat()}),
        SourceRecord(source="alert_state", resource_type="condition", external_id="zzmet02:payku",
                     payload={"active": False, "last_resolved_at": (IN + timedelta(hours=1)).isoformat()}),
        SourceRecord(source="alert_state", resource_type="condition", external_id="zzmet02:tch",
                     payload={"active": True, "since": BEFORE.isoformat(), "last_sent_at": BEFORE.isoformat()}),
    ])
    db.flush()
    return db, src


def _by(rows, **match):
    found = [r for r in rows if all(r[k] == v for k, v in match.items())]
    assert len(found) == 1, (match, rows)
    return found[0]


def test_build_window_ends_at_chile_midnight_and_spans_days() -> None:
    assert WINDOW.end == datetime(2001, 3, 15, tzinfo=om.CHILE_TZ).astimezone(UTC)  # cierre del dia en Chile
    assert WINDOW.end - WINDOW.start == timedelta(days=14)
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    assert om.build_window(7, now=now).end == now
    with pytest.raises(ValueError):
        om.build_window(0)


def test_sync_sections_count_status_duration_and_freshness(seeded) -> None:
    db, src = seeded
    report = om.collect(db, WINDOW, "crm_test")
    ok = _by(report.sections["sync_canales"], fuente=src, estado="completed")
    assert (ok["corridas"], ok["duracion_media_s"], ok["duracion_max_s"], ok["registros"]) == (2, 90.0, 120.0, 20)
    assert _by(report.sections["sync_canales"], fuente=src, estado="failed")["corridas"] == 1
    assert not [r for r in report.sections["sync_canales"] if r["fuente"].startswith("billing_")]
    assert _by(report.sections["jobs"], fuente="billing_met02_job", estado="completed")["corridas"] == 1
    fresh = _by(report.sections["sync_frescura"], fuente=src)
    last_ok = IN + timedelta(hours=1, seconds=120)
    assert fresh["horas_desde_ultimo_ok"] == round((WINDOW.end - last_ok).total_seconds() / 3600, 1)
    assert fresh["fallidas_en_ventana"] == 1


def test_etl_writes_exports_and_requests(seeded) -> None:
    db, _ = seeded
    s = om.collect(db, WINDOW, "crm_test").sections
    etl = _by(s["etl_runs"], estado="completed")
    assert (etl["corridas"], etl["duracion_media_s"], etl["con_canal_fallido"], etl["registros_upsert"]) == (2, 200.0, 1, 10)
    assert _by(s["escrituras"], fuente="virtualpos1", operacion="change_amount", estado="completed")["duracion_media_s"] == 4.0
    assert _by(s["escrituras"], fuente="virtualpos1", operacion="change_amount", estado="failed")["cantidad"] == 1
    assert _by(s["exportaciones"], entidad="members", con_datos_personales=True)["filas"] == 5
    assert _by(s["exportaciones"], entidad="members", con_datos_personales=False)["filas"] == 40
    assert _by(s["cambios_cobro"], tipo="change_amount", plataforma="virtualpos1", estado="ejecutada")["cantidad"] == 1
    assert {r["evento"]: r["cantidad"] for r in s["cambios_cobro_eventos"]} == {"aplicada": 1, "creada": 1}
    assert _by(s["bajas"], canal="toku", motivo="member_request", estado="completed")["cantidad"] == 1
    assert {r["evento"]: r["cantidad"] for r in s["bajas_eventos"]} == {"completed": 1, "created": 1}


def test_alerts_use_only_the_condition_kind_and_window(seeded) -> None:
    db, _ = seeded
    row = _by(om.collect(db, WINDOW, "crm_test").sections["alertas"], condicion="zzmet02")
    assert row == {"condicion": "zzmet02", "avisadas_en_ventana": 1, "recuperadas_en_ventana": 1, "activas_al_cierre": 2}


def test_output_has_no_personal_data_and_declares_limitations(seeded) -> None:
    db, _ = seeded
    report = om.collect(db, WINDOW, "crm_test")
    for text_out in (om.format_text(report), om.format_text(report, markdown=True), om.format_json(report)):
        assert SECRET_EXT not in text_out
        assert "11.111.111-1" not in text_out
        assert "socio@example.test" not in text_out
        assert "zzmet02:toku" not in text_out  # solo el tipo de condicion
        assert "sesion" in text_out  # limitacion declarada: no hay auditoria de acceso
    payload = json.loads(om.format_json(report))
    assert set(payload["sections"]) == {name for name, _ in om.SECTIONS}


def test_database_is_required() -> None:
    with pytest.raises(SystemExit) as exc:
        om.parse_args([])
    assert exc.value.code == 2


@pytest.mark.parametrize("name", ["crm", "crm_sandbox"])
def test_non_test_database_is_rejected_without_read_only(name, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(om, "open_readonly_session", lambda db: opened.append(db))
    with pytest.raises(readonly_guard.UnsafeDatabaseError) as exc:
        om.main(["--database", name])
    assert exc.value.code == 2
    assert opened == []  # aborta antes de abrir cualquier conexion


def test_main_runs_read_only_against_the_test_database(capsys) -> None:
    test_db = engine.url.database
    assert test_db.endswith("_test")
    assert om.main(["--database", test_db, "--until", "2001-03-14", "--format", "markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Metricas de operacion")
    assert f"Base: {test_db}" in out
    assert "## limitaciones" in out


def test_readonly_session_rejects_writes() -> None:
    db = om.open_readonly_session(engine.url.database)
    try:
        with pytest.raises(readonly_guard.ReadOnlyViolation):
            db.execute(SyncRun.__table__.delete().where(SyncRun.source == "nada"))
    finally:
        db.rollback()
        bind = db.get_bind()
        db.close()
        bind.dispose()
