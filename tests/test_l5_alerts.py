"""L5-ALERTAS (d137-d140): paquete minimo, primer fallo de configuracion, etl_run fallido, heartbeat, alertas de negocio,
reportes viejos, escrituras fallidas, varios destinatarios y scripts de mantenimiento.

SOLO con el servidor SMTP falso en memoria de `test_alerts` (nunca se abre un socket ni se envia un correo real);
destinatarios ficticios `@example.test`.
"""

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta

import pytest
import test_alerts
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_alerts import (
    NOW,
    PII_MAIL,
    PII_RUT,
    TO,
    FakeSMTP,
    _check,
    _run,
    _subjects,
    _text,
)

from app.api.v1.routes import etl as etl_routes
from app.api.v1.routes import health as health_routes
from app.api.v1.routes import staging
from app.core.channel_errors import CONFIG_ERROR_PREFIX, is_config_or_credential_error
from app.core.config import settings
from app.main import app
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.models.tch import TchFileLoad
from app.models.toku_report import TkReportFile
from app.models.write_run import WriteRun
from app.services import alerts, business_alerts

# Fixtures compartidas de test_alerts (base en transaccion revertida y SMTP falso), registradas con otro nombre.
_alerts_db_session = test_alerts.db_session
_alerts_smtp = test_alerts.smtp


@pytest.fixture
def db_session(_alerts_db_session):
    return _alerts_db_session


@pytest.fixture
def smtp(_alerts_smtp):
    return _alerts_smtp


MINIMAL_PACKAGE = {"sync_fail", "core_lag", "cancellation_stuck", "billing_stuck", "billing_reconciliation"}


class _NoClose:
    """Envuelve la sesion de prueba para codigo que hace `SessionLocal()` ... `close()`."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


# ============================== d138: paquete minimo ==============================


def test_minimal_package_is_what_stays_active_with_only_alerts_enabled(smtp, monkeypatch):
    for flag in ("webhook_processor_enabled", "sync_removal_detection_enabled", "alert_business_enabled",
                 "alert_report_age_enabled", "alert_write_failed_enabled"):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "alert_webhook_silence_hours", 0)
    assert set(alerts.active_kinds()) == MINIMAL_PACKAGE
    registered = set(alerts.registered_kinds())
    assert {"webhook_failed", "webhook_lag", "webhook_silence", "removal_aborted", "report_stale", "write_failed",
            *business_alerts.KINDS} <= registered - MINIMAL_PACKAGE


def test_each_flag_turns_on_only_its_kinds(smtp, monkeypatch):
    monkeypatch.setattr(settings, "webhook_processor_enabled", True)
    monkeypatch.setattr(settings, "sync_removal_detection_enabled", True)
    monkeypatch.setattr(settings, "alert_business_enabled", True)
    monkeypatch.setattr(settings, "alert_report_age_enabled", True)
    monkeypatch.setattr(settings, "alert_write_failed_enabled", True)
    assert set(alerts.active_kinds()) == set(alerts.registered_kinds())


def test_failed_webhooks_do_not_alert_with_the_processor_off(db_session, smtp, monkeypatch):
    from test_alerts import _webhook

    monkeypatch.setattr(settings, "webhook_processor_enabled", False)
    _webhook(db_session, "failed", 2)
    assert _check(db_session).sent == 0


# ============================== d139a: primer fallo de configuracion o credencial ==============================


@pytest.mark.parametrize("message", [
    f"{CONFIG_ERROR_PREFIX}: VirtualPOS virtualpos2 (faltan: VIRTUALPOS2_API_KEY)",
    "VirtualPOS virtualpos2 is not configured",
    "Illegal header value b'Bearer '",
    "Client error '401 Unauthorized' for url 'https://api.example.test/v1'",
    "HTTP 403 al listar suscripciones",
])
def test_config_or_credential_errors_are_recognized(message):
    assert is_config_or_credential_error(message)


@pytest.mark.parametrize("message", [None, "", "ReadTimeout", "getaddrinfo failed", "procesados 401 registros",
                                     "CardinalityViolation"])
def test_other_errors_are_not_config_errors(message):
    assert not is_config_or_credential_error(message)


@pytest.mark.parametrize(("source", "error"), [
    ("virtualpos2", "VirtualPOS virtualpos2 is not configured"),
    ("payku", "Illegal header value b'Bearer '"),
    ("toku", "Client error '401 Unauthorized' for url 'https://api.example.test'"),
])
def test_first_config_failure_alerts_immediately(db_session, smtp, source, error):
    _run(db_session, 1, source=source, status="failed", error=f"{error} {PII_MAIL}")
    result = _check(db_session)
    assert result.sent == 1
    body = _text(smtp.messages[0])
    assert "configuración o credencial" in body and source in body
    assert PII_MAIL not in body and "Bearer" not in body and "Unauthorized" not in body  # nunca el texto del error


def test_a_single_non_config_failure_still_waits_for_the_second(db_session, smtp):
    _run(db_session, 1, source="toku", status="failed", error="ReadTimeout")
    assert _check(db_session).sent == 0
    _run(db_session, 0.5, source="toku", status="failed", error="ReadTimeout")
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 1


def test_config_failure_recovers_when_the_next_run_succeeds(db_session, smtp):
    _run(db_session, 2, source="payku", status="failed", error="Illegal header value b'Bearer '")
    assert _check(db_session).sent == 1
    _run(db_session, 0, source="payku", status="completed")
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 1
    assert _subjects()[-1].split("] ")[1].startswith("Recuperado")


# ============================== d139b: etl_run fallido ==============================


def test_full_sync_status_never_completed_when_a_channel_fails():
    assert etl_routes.full_sync_status(["toku"], [], []) == "completed"
    assert etl_routes.full_sync_status(["toku"], ["payku"], []) == "partial"
    assert etl_routes.full_sync_status([], ["payku"], []) == "failed"
    assert etl_routes.full_sync_status(["toku"], [], ["toku.charges"]) == "partial"


def test_full_sync_background_marks_the_run_partial_or_failed(db_session, monkeypatch):
    async def ok(db, *a, **k):
        return SyncRun(source="toku", status="completed", records_processed=3)

    async def broken(db, *a, **k):
        raise RuntimeError("Illegal header value b'Bearer '")

    monkeypatch.setattr(etl_routes, "SessionLocal", lambda: _NoClose(db_session))
    monkeypatch.setattr(etl_routes, "_SYNC_FN", {"toku": ok, "payku": broken})
    monkeypatch.setattr(etl_routes, "consolidate_to_centralized", lambda db, providers, failures: 0)
    monkeypatch.setattr(type(settings), "channel_enabled", lambda self, c: True)
    for providers, expected in ((["toku", "payku"], "partial"), (["payku"], "failed"), (["toku"], "completed")):
        run = EtlRun(status="running", records_upserted=0)
        db_session.add(run)
        db_session.flush()
        asyncio.run(etl_routes._run_full_sync_background(run.id, providers))
        db_session.refresh(run)
        assert run.status == expected, providers
        assert (run.channels_failed or []) == (["payku"] if "payku" in providers else [])
        assert "toku" not in (run.channels_failed or [])
        if expected != "completed":
            assert "payku" in run.error_message and "Bearer" not in run.error_message


# ============================== d139c: heartbeat ==============================


def _heartbeat(db_session, monkeypatch):
    monkeypatch.setattr(health_routes, "SessionLocal", lambda: _NoClose(db_session))
    return TestClient(app, base_url="https://testserver").get("/api/v1/health/heartbeat")


def test_heartbeat_needs_no_session_and_has_no_personal_data(db_session, monkeypatch):
    from datetime import UTC, datetime

    recent = datetime.now(UTC) - timedelta(hours=2)
    db_session.add(SyncRun(source="virtualpos1", status="completed", started_at=recent, finished_at=recent,
                           error_message=f"{PII_MAIL} {PII_RUT}"))
    db_session.add(SyncRun(source="payku", status="failed", started_at=recent, finished_at=recent,
                           error_message=PII_MAIL))
    db_session.flush()
    monkeypatch.setattr(health_routes, "_scheduler_expected", lambda: False)
    r = _heartbeat(db_session, monkeypatch)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["sync"]["channels"]["virtualpos"] is not None and body["sync"]["channels"]["payku"] is None
    assert set(body["scheduler"]) == {"expected", "running", "last_job_success_at", "last_etl_run_success_at"}
    raw = r.text
    assert PII_MAIL not in raw and PII_RUT not in raw and "error_message" not in raw


def test_heartbeat_is_degraded_with_an_old_sync_or_a_stopped_scheduler(db_session, monkeypatch):
    monkeypatch.setattr(health_routes, "_scheduler_expected", lambda: True)
    monkeypatch.setattr(health_routes.engine, "scheduler_running", lambda: False)
    body = _heartbeat(db_session, monkeypatch).json()
    assert body["status"] == "degraded"
    assert set(body["problems"]) == {"sync_stale", "scheduler_stopped"}


def test_heartbeat_returns_503_without_database(monkeypatch):
    class Broken:
        def execute(self, *a, **k):
            raise OSError("db caida")

        def close(self):
            pass

    monkeypatch.setattr(health_routes, "SessionLocal", Broken)
    r = TestClient(app, base_url="https://testserver").get("/api/v1/health/heartbeat")
    assert r.status_code == 503 and r.json() == {
        "status": "error", "checked_at": r.json()["checked_at"], "environment": settings.env_mode, "database": "error"}


def test_scheduler_listener_records_the_last_successful_job():
    from types import SimpleNamespace

    from app.scheduler import engine

    before = engine.last_job_success_at()
    engine._on_job_executed(SimpleNamespace(exception=RuntimeError("x")))
    assert engine.last_job_success_at() == before
    engine._on_job_executed(SimpleNamespace(exception=None))
    assert engine.last_job_success_at() is not None


def _heartbeat_args(tmp_path, **kw):
    import argparse

    values = {"url": "http://localhost:9", "timeout": 1.0, "state_file": str(tmp_path / "hb.json"),
              "alert_on_degraded": False, "dry_run": False, **kw}
    return argparse.Namespace(**values)


def test_heartbeat_check_alerts_once_reminds_and_recovers(smtp, monkeypatch, tmp_path):
    from scripts.maintenance import heartbeat_check as hb

    state = {"outcome": ("down", None, "ConnectionRefusedError")}
    monkeypatch.setattr(hb, "probe", lambda url, timeout: state["outcome"])
    args = _heartbeat_args(tmp_path)
    assert hb.run(args, now=NOW) == hb.EXIT_DOWN
    assert len(smtp.messages) == 1 and "Alerta" in smtp.messages[0]["Subject"]
    assert "no responde" in _text(smtp.messages[0])
    assert hb.run(args, now=NOW + timedelta(minutes=15)) == hb.EXIT_DOWN
    assert len(smtp.messages) == 1  # deduplicado
    hb.run(args, now=NOW + timedelta(hours=6))
    assert len(smtp.messages) == 2 and "Recordatorio" in smtp.messages[1]["Subject"]
    state["outcome"] = ("ok", {"status": "ok"}, "ok")
    assert hb.run(args, now=NOW + timedelta(hours=7)) == hb.EXIT_OK
    assert len(smtp.messages) == 3 and "Recuperado" in smtp.messages[2]["Subject"]
    assert hb.run(args, now=NOW + timedelta(hours=8)) == hb.EXIT_OK and len(smtp.messages) == 3
    assert json.loads((tmp_path / "hb.json").read_text(encoding="utf-8"))["active"] is False


def test_heartbeat_check_dry_run_and_degraded_rules(smtp, monkeypatch, tmp_path, capsys):
    from scripts.maintenance import heartbeat_check as hb

    monkeypatch.setattr(hb, "probe", lambda url, timeout: ("down", None, "TimeoutError"))
    hb.run(_heartbeat_args(tmp_path, dry_run=True), now=NOW)
    assert smtp.messages == [] and not (tmp_path / "hb.json").exists()
    assert "DRY-RUN" in capsys.readouterr().out
    monkeypatch.setattr(hb, "probe", lambda url, timeout: ("degraded", {"status": "degraded"}, "sync_stale"))
    assert hb.run(_heartbeat_args(tmp_path), now=NOW) == hb.EXIT_DEGRADED and smtp.messages == []
    hb.run(_heartbeat_args(tmp_path, alert_on_degraded=True), now=NOW)
    assert len(smtp.messages) == 1 and "degradado" in _text(smtp.messages[0])


def test_heartbeat_check_probe_reports_a_dead_backend():
    from scripts.maintenance import heartbeat_check as hb

    outcome, body, reason = hb.probe("http://127.0.0.1:9", timeout=0.5)  # puerto 9 (discard): nadie escucha
    assert outcome == "down" and body is None and reason


def test_heartbeat_check_respects_alerts_enabled(smtp, monkeypatch, tmp_path):
    from scripts.maintenance import heartbeat_check as hb

    monkeypatch.setattr(settings, "alerts_enabled", False)
    monkeypatch.setattr(hb, "probe", lambda url, timeout: ("down", None, "x"))
    hb.run(_heartbeat_args(tmp_path), now=NOW)
    assert smtp.messages == [] and FakeSMTP.instances == []


# ============================== d137: script de correo de prueba ==============================


def test_send_test_alert_refuses_outside_sandbox(smtp, monkeypatch):
    from scripts.maintenance import send_test_alert

    monkeypatch.setattr(settings, "app_env", "production")
    assert send_test_alert.main(["--send"]) == 2
    assert FakeSMTP.instances == []


def test_send_test_alert_is_dry_run_by_default(smtp, monkeypatch, capsys):
    from scripts.maintenance import send_test_alert

    monkeypatch.setattr(settings, "app_env", "sandbox")
    assert send_test_alert.main([]) == 0
    out = capsys.readouterr().out
    assert FakeSMTP.instances == [] and "DRY-RUN" in out and TO not in out  # nunca imprime destinatarios


def test_send_test_alert_sends_through_the_alert_pipeline(smtp, monkeypatch):
    from scripts.maintenance import send_test_alert

    monkeypatch.setattr(settings, "app_env", "sandbox")
    assert send_test_alert.main(["--send"]) == 0
    assert len(smtp.messages) == 1 and smtp.messages[0]["To"] == TO
    assert smtp.messages[0]["Subject"].startswith("[SynkmetriX · sandbox] Alerta: correo de prueba")


def test_send_test_alert_can_be_forced_outside_sandbox(smtp, monkeypatch):
    from scripts.maintenance import send_test_alert

    monkeypatch.setattr(settings, "app_env", "production")
    assert send_test_alert.main(["--allow-non-sandbox"]) == 0  # sigue en dry-run
    assert FakeSMTP.instances == []


# ============================== d139d: alertas de negocio ==============================


@pytest.fixture
def business(monkeypatch):
    business_alerts.reset_cache()
    monkeypatch.setattr(settings, "alert_business_enabled", True)
    boards = {"general": [], "virtualpos": [], "toku": [], "payku": []}
    calls = {"n": 0}

    def make(name):
        def build(db):
            calls["n"] += 1
            value = boards[name]
            if isinstance(value, Exception):
                raise value
            return {"alerts": list(value)}
        return build

    monkeypatch.setattr(business_alerts, "_boards", lambda: {name: make(name) for name in boards})
    yield boards, calls
    business_alerts.reset_cache()


def _month(offset=0):
    first = NOW.date().replace(day=1)
    for _ in range(offset):
        first = (first - timedelta(days=1)).replace(day=1)
    return first.strftime("%Y-%m")


def test_business_alerts_send_only_high_severity_with_one_kind_per_type(db_session, smtp, business):
    boards, _ = business
    boards["general"] = [
        {"sev": "alta", "tipo": "Tasa de rechazo global elevada", "canal": "Consolidado", "detalle": "45% de 100"},
        {"sev": "alta", "tipo": "Alta tasa de rechazo", "canal": "Toku", "periodo": _month(), "detalle": "60%"},
        {"sev": "alta", "tipo": "Alta tasa de rechazo", "canal": "Toku", "periodo": "2020-01", "detalle": "viejo"},
        {"sev": "media", "tipo": "Alta tasa de rechazo", "canal": "Payku", "periodo": _month(), "detalle": "35%"},
        {"sev": "media", "tipo": "Canal en declive", "canal": "TCH", "detalle": "x"},
    ]
    boards["virtualpos"] = [
        {"sev": "alta", "tipo": "Churn rate elevado", "canal": "VirtualPOS", "detalle": "25%"},
        {"sev": "alta", "tipo": "Racha de rechazos", "canal": "VirtualPOS", "detalle": "30 suscripciones"},
        {"sev": "alta", "tipo": "Sin cobro reciente", "canal": "VirtualPOS", "detalle": "50 (45%)"},
        {"sev": "baja", "tipo": "Múltiples suscripciones activas", "canal": "VirtualPOS", "detalle": "x"},
    ]
    active = {c.key for c in alerts.evaluate_conditions(db_session, NOW) if c.key.startswith("business_")}
    assert active == {
        "business_rejection_rate:consolidado", f"business_rejection_rate:toku:{_month()}",
        "business_churn:virtualpos", "business_rejection_streak:virtualpos", "business_no_recent_charge:virtualpos",
    }
    assert _check(db_session).sent == 5
    assert all("severidad alta" in _text(m) for m in smtp.messages)


def test_business_alerts_reuse_the_panel_calculations(db_session):
    """Sin duplicar logica: la condicion sale de lo que devuelven las mismas funciones del panel (staging.py)."""
    today = NOW.date()
    rows = [{"channel": "Toku", "date": today.replace(day=1).isoformat(), "status": "rechazado", "count": 70},
            {"channel": "Toku", "date": today.replace(day=1).isoformat(), "status": "pagado", "count": 30}]
    panel = staging._rejection_alerts(rows, today)
    keys = {c.key for c in (business_alerts.to_condition(a, NOW) for a in panel) if c}
    assert f"business_rejection_rate:toku:{today.strftime('%Y-%m')}" in keys
    churn = staging._channel_alerts([], [], [], {"churn_rate": 25.0, "churn_window_label": "mes"}, "Payku")
    assert {business_alerts.to_condition(a, NOW).key for a in churn} == {"business_churn:payku"}


def test_business_alerts_are_cached_and_a_broken_board_keeps_its_last_conditions(db_session, smtp, business):
    boards, calls = business
    boards["toku"] = [{"sev": "alta", "tipo": "Churn rate elevado", "canal": "Toku", "detalle": "22%"}]
    assert _check(db_session).sent == 1
    first_calls = calls["n"]
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 0
    assert calls["n"] == first_calls  # dentro de ALERT_BUSINESS_EVAL_MINUTES no se recalcula
    boards["toku"] = RuntimeError("tablero roto")
    assert _check(db_session, NOW + timedelta(hours=2)).sent == 0  # sin «Recuperado» falso
    boards["toku"] = []
    assert _check(db_session, NOW + timedelta(hours=3)).sent == 1
    assert "Recuperado" in _subjects()[-1]


def test_business_alerts_off_by_default(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_business_enabled", False)
    called = []
    monkeypatch.setattr(business_alerts, "_boards", lambda: called.append(1) or {})
    _check(db_session)
    assert called == []


def test_real_boards_are_wired_and_compute(db_session):
    boards = business_alerts._boards()
    assert set(boards) == {"general", "virtualpos", "toku", "payku"}
    staging.invalidate_dashboard_cache()
    for name, build in boards.items():
        assert isinstance(business_alerts._board_alerts(db_session, name, build), list), name  # None = fallo
    staging.invalidate_dashboard_cache()


# ============================== d139e: reportes viejos ==============================


@pytest.fixture
def reports(db_session, monkeypatch):
    monkeypatch.setattr(settings, "alert_report_age_enabled", True)
    db_session.execute(delete(TkReportFile))
    db_session.execute(delete(TchFileLoad))
    db_session.flush()
    return db_session


def _toku_report(db, days_old, report_type="intentos"):
    moment = NOW - timedelta(days=days_old)
    db.add(TkReportFile(report_type=report_type, file_sha256=uuid.uuid4().hex * 2, filename=f"{PII_RUT}.xlsx",
                        generated_at=moment, status="completed", started_at=moment, finished_at=moment))
    db.flush()


def _tch_report(db, days_old):
    db.add(TchFileLoad(file_sha256=uuid.uuid4().hex * 2, file_name=f"{PII_MAIL}.xlsx",
                       loaded_at=NOW - timedelta(days=days_old)))
    db.flush()


def test_no_report_loaded_alerts_both_channels(reports, smtp):
    keys = {c.key for c in alerts.evaluate_conditions(reports, NOW) if c.key.startswith("report_stale")}
    assert keys == {"report_stale:toku", "report_stale:tch"}


def test_old_reports_alert_and_fresh_ones_recover(reports, smtp):
    _toku_report(reports, 10)
    _tch_report(reports, 9)
    assert _check(reports).sent == 2
    bodies = " ".join(_text(m) for m in smtp.messages)
    assert "intentos: datos de hace 10 días" in bodies and "hace 9 días" in bodies
    assert PII_RUT not in bodies and PII_MAIL not in bodies  # nunca nombres de archivo
    _toku_report(reports, 1)
    _tch_report(reports, 0)
    assert _check(reports, NOW + timedelta(minutes=15)).sent == 2
    assert all("Recuperado" in s for s in _subjects()[-2:])


def test_fresh_load_with_one_stale_type_still_alerts_toku(reports, smtp):
    _toku_report(reports, 1, "pagos")
    _toku_report(reports, 8, "intentos")
    _tch_report(reports, 1)
    conds = [c for c in alerts.evaluate_conditions(reports, NOW) if c.key.startswith("report_stale")]
    assert [c.key for c in conds] == ["report_stale:toku"]
    assert conds[0].details == ("intentos: datos de hace 8 días",)


def test_report_age_off_by_default(reports, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_report_age_enabled", False)
    assert not [c for c in alerts.evaluate_conditions(reports, NOW) if c.key.startswith("report_stale")]


# ============================== d139f: escrituras fallidas ==============================


def _write(db, status, hours_ago, source="virtualpos1", operation="update_amount"):
    moment = NOW - timedelta(hours=hours_ago)
    db.add(WriteRun(source=source, resource_type="subscription", external_id=f"sub-{PII_RUT}", operation=operation,
                    status=status, request_payload={"email": PII_MAIL}, error_message=f"fallo {PII_MAIL}",
                    started_at=moment, finished_at=moment))
    db.flush()


def test_failed_write_runs_alert_with_counts_only(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_write_failed_enabled", True)
    db_session.execute(delete(WriteRun).where(WriteRun.status == "failed"))
    _write(db_session, "failed", 2)
    _write(db_session, "failed", 3, source="toku", operation="cancel")
    _write(db_session, "reconciliation_required", 1)  # ya en la cola de conciliacion: no cuenta aqui
    _write(db_session, "failed", 30)  # fuera de la ventana de 24 h
    conds = [c for c in alerts.evaluate_conditions(db_session, NOW) if c.key == "write_failed"]
    assert len(conds) == 1 and conds[0].text.startswith("2 escritura")
    assert set(conds[0].details) == {"toku · cancel: 1", "virtualpos1 · update_amount: 1"}
    _check(db_session)
    msg = next(m for m in smtp.messages if "escrituras fallidas" in m["Subject"])
    assert PII_MAIL not in _text(msg) and PII_RUT not in _text(msg)


def test_failed_write_runs_off_by_default(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_write_failed_enabled", False)
    _write(db_session, "failed", 1)
    assert not [c for c in alerts.evaluate_conditions(db_session, NOW) if c.key == "write_failed"]


# ============================== d140: varios destinatarios ==============================


def test_recipient_list_accepts_spaces_and_is_validated():
    valid, invalid = alerts.parse_recipients(
        " ops@example.test ,jefa@example.test,,  no-es-correo , OPS@example.test, x@y ,ok.dos@example.test ")
    assert valid == ["ops@example.test", "jefa@example.test", "ok.dos@example.test"]
    assert invalid == 2
    assert alerts.parse_recipients("") == ([], 0)
    assert alerts.parse_recipients(None) == ([], 0)


def test_every_valid_recipient_gets_every_alert(db_session, smtp, monkeypatch, caplog):
    monkeypatch.setattr(settings, "alert_email_to", "a@example.test , b@example.test,malo")
    _run(db_session, 1, source="payku", status="failed", error="Illegal header value b'Bearer '")
    with caplog.at_level(logging.WARNING, logger="app.services.alerts"):
        assert _check(db_session).sent == 1
    assert smtp.messages[0]["To"] == "a@example.test, b@example.test"
    assert "1 destinatario" in caplog.text and "malo" not in caplog.text


def test_only_invalid_recipients_send_nothing(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_to", "malo, tampoco")
    _run(db_session, 1, source="payku", status="failed", error="Illegal header value b'Bearer '")
    result = _check(db_session)
    assert result.sent == 0 and result.skipped == "no_recipient"


def test_today_is_a_date():  # guarda: el modulo de negocio usa fechas de Chile
    assert isinstance(business_alerts._recent_periods(NOW), set) and all(len(p) == 7 for p in
                                                                         business_alerts._recent_periods(NOW))
    assert date.fromisoformat(_month() + "-01")


def test_debug_smtp_server_receives_the_test_alert_without_relaying(monkeypatch, tmp_path, capsys):
    """d137: el SMTP de depuracion local (solo biblioteca estandar) recibe el correo de prueba real de alerts.py."""
    import threading

    from scripts.maintenance import send_test_alert
    from scripts.maintenance.debug_smtp_server import DebugSMTPServer

    with DebugSMTPServer(("127.0.0.1", 0), out_dir=tmp_path, quiet=True) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setattr(settings, "app_env", "sandbox")
            monkeypatch.setattr(settings, "alert_email_to", f"{TO}, otro@example.test")
            monkeypatch.setattr(settings, "alert_email_from", "crm@example.test")
            monkeypatch.setattr(settings, "alert_smtp_host", "127.0.0.1")
            monkeypatch.setattr(settings, "alert_smtp_port", server.server_address[1])
            monkeypatch.setattr(settings, "alert_smtp_starttls", False)
            monkeypatch.setattr(settings, "alert_smtp_user", "")
            monkeypatch.setattr(settings, "alert_smtp_password", "")
            assert send_test_alert.main(["--send"]) == 0
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert len(server.messages) == 1
    assert "correo de prueba" in server.messages[0]["Subject"]
    assert len(list(tmp_path.glob("*.eml"))) == 1
