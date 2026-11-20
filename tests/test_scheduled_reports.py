"""REP-02: armado de los reportes por correo (sin SMTP real; destinatarios ficticios `persona@ejemplo.org`).

Cubre: periodos en America/Santiago con cambio de hora, minimo de agregacion («<5»), CSV, estado de sincronizaciones,
envio con SMTP simulado y, sobre todo, que ni el HTML ni el CSV ni el texto lleven datos personales.
"""

import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import ClassVar

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge, Client, Subscription
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.services import alerts, scheduled_reports

TO = "persona@ejemplo.org"
NOW = datetime(2099, 6, 17, 11, 0, tzinfo=UTC)  # miercoles; el periodo se calcula con las funciones del modulo

PEOPLE = [
    ("Zacarías", "Quispe Mamani", "17.654.321-4", "zacarias.quispe@ejemplo.org", "+56 9 8765 4321"),
    ("Hortensia", "Valdivieso Orrego", "9.876.543-K", "hortensia.valdivieso@ejemplo.org", "+56 2 2345 6789"),
    ("Evaristo", "Tapia Cuevas", "21.345.678-9", "evaristo.tapia@ejemplo.org", "+56 9 5555 1234"),
    ("Querubina", "Ñancupil Reyes", "12.222.333-5", "querubina.nancupil@ejemplo.org", "+56 9 4444 9876"),
    ("Baltazar", "Oyarzún Lagos", "15.111.222-1", "baltazar.oyarzun@ejemplo.org", "+56 9 3333 6789"),
    ("Filomena", "Gutiérrez Pino", "8.765.432-3", "filomena.gutierrez@ejemplo.org", "+56 9 2222 1357"),
]
RUT_RE = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b|\b\d{7,8}-[\dkK]\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


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


def _seed(db, source: str, count: int, day: date, tag: str) -> None:
    """`count` socios con datos personales reconocibles, cada uno con una suscripcion activa y un cobro pagado."""
    for i in range(count):
        first, last, rut, mail, phone = PEOPLE[i % len(PEOPLE)]
        ext = f"{tag}-{i}"
        db.add(Client(source=source, external_id=ext, first_name=first, last_name=last, email=mail, phone_number=phone,
                      social_id=rut, status="activa", raw_payload={}))
        db.add(Subscription(source=source, external_id=ext, client_external_id=ext, client_social_id=rut, status="activa",
                            suscription_date=day.isoformat(), amount="10000", raw_payload={}))
        db.add(Charge(source=source, external_id=ext, client_external_id=ext, subscription_external_id=ext,
                      status="pagado", amount="10000", charge_date=day.isoformat(), raw_payload={}))
    db.flush()


# ----------------------------- periodos -----------------------------


def test_weekly_period_is_the_last_complete_monday_to_sunday() -> None:
    start, end = scheduled_reports.weekly_period(datetime(2026, 11, 23, 10, 30, tzinfo=UTC))  # lunes
    assert (start, end) == (date(2026, 11, 16), date(2026, 11, 22))
    assert start.weekday() == 0 and end.weekday() == 6
    assert scheduled_reports.weekly_key(start) == "weekly:2026-W47"
    # un miercoles de la misma semana reporta lo mismo
    assert scheduled_reports.weekly_period(datetime(2026, 11, 25, 10, 0, tzinfo=UTC)) == (start, end)


def test_weekly_boundary_uses_chile_time_after_dst_starts() -> None:
    # 07-sep-2026 03:30 UTC: con horario de verano (UTC-3) ya es lunes 00:30 en Chile
    assert scheduled_reports.weekly_period(datetime(2026, 9, 7, 3, 30, tzinfo=UTC)) == (date(2026, 8, 31), date(2026, 9, 6))


def test_weekly_boundary_uses_chile_time_after_dst_ends() -> None:
    # 06-abr-2026 03:30 UTC: con horario de invierno (UTC-4) todavia es domingo 23:30 en Chile
    assert scheduled_reports.weekly_period(datetime(2026, 4, 6, 3, 30, tzinfo=UTC)) == (date(2026, 3, 23), date(2026, 3, 29))


def test_monthly_period_is_the_previous_calendar_month_in_chile() -> None:
    assert scheduled_reports.monthly_period(datetime(2026, 11, 2, 10, 45, tzinfo=UTC)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert scheduled_reports.monthly_key(date(2026, 10, 1)) == "monthly:2026-10"
    # 01-nov 02:30 UTC es 31-oct 23:30 en Chile: el mes en curso sigue siendo octubre
    assert scheduled_reports.monthly_period(datetime(2026, 11, 1, 2, 30, tzinfo=UTC)) == (date(2026, 9, 1), date(2026, 9, 30))
    # enero cierra diciembre del anio anterior
    assert scheduled_reports.monthly_period(datetime(2027, 1, 4, 11, 0, tzinfo=UTC)) == (date(2026, 12, 1), date(2026, 12, 31))


# ----------------------------- minimo de agregacion -----------------------------


def _fig(**over):
    base = {"activas": 120, "activas_inicio": 118, "altas": 10, "bajas": 6, "cobros_aprobados": 100,
            "cobros_rechazados": 8, "churn": 5.08, "recuperacion": 7}
    return {**base, **over}


def _figures(**by_channel):
    figs = {ch: _fig() for ch in scheduled_reports.CHANNELS}
    figs.update(by_channel)
    figs["total"] = {k: sum(figs[ch][k] for ch in scheduled_reports.CHANNELS) for k in figs["toku"]}
    figs["total"]["churn"] = 4.2
    return figs


def test_small_channel_figures_are_masked_and_total_cannot_be_subtracted() -> None:
    rows = {r["canal"]: r for r in scheduled_reports.display_rows("2099-06", _figures(tch=_fig(altas=3, bajas=0, recuperacion=1)))}
    assert rows["tch"]["altas"] == "<5"
    assert rows["tch"]["bajas"] == "0"  # el cero se muestra tal cual
    assert rows["tch"]["recuperacion"] == "<5"
    assert rows["toku"]["altas"] == "10"
    assert rows["total"]["altas"] == "—" and rows["total"]["recuperacion"] == "—"
    # altas oculta => activas del canal tambien (activas(t) - activas(t-1) = altas - bajas), y el total de activas no sale
    assert rows["tch"]["activas"] == "<5" and rows["total"]["activas"] == "—"
    assert rows["toku"]["activas"] == "120"
    assert rows["total"]["cobros_aprobados"] == "400"  # columna sin enmascarar: total visible


def _unknowns(prev_row, row) -> int:
    """Cuantas de las 4 cifras de activas(t) - activas(t-1) = altas(t) - bajas(t) no se pueden leer (no numericas)."""
    return sum(not r[c].isdigit() for r, c in ((prev_row, "activas"), (row, "activas"), (row, "altas"), (row, "bajas")))


def test_hidden_figure_cannot_be_reconstructed_from_two_adjacent_periods() -> None:
    # Toku: activas 40 -> 42, bajas 0, altas 2 (oculta). Restando periodos se despejaria altas = 2.
    prev = scheduled_reports.display_rows("w1", _figures(toku=_fig(activas=40, activas_inicio=40, altas=1, bajas=0)))
    cur = scheduled_reports.display_rows("w2", _figures(toku=_fig(activas=42, activas_inicio=40, altas=2, bajas=0)))
    scheduled_reports.protect_series(prev, cur)
    for a, b in zip(prev, cur, strict=True):
        assert _unknowns(a, b) != 1, (a, b)
    toku_prev = next(r for r in prev if r["canal"] == "toku")
    toku_cur = next(r for r in cur if r["canal"] == "toku")
    assert toku_cur["altas"] == "<5" and toku_cur["bajas"] == "0"
    assert toku_prev["activas"] == "<5" and toku_cur["activas"] == "<5"  # ambos periodos
    assert next(r for r in cur if r["canal"] == "total")["activas"] == "—"
    # un canal sin cifras pequenas conserva sus activas
    assert next(r for r in cur if r["canal"] == "payku")["activas"] == "120"


def test_small_activas_in_one_period_hides_the_series_even_with_visible_flows() -> None:
    # activas pequena (3) con altas y bajas visibles: se despejaria desde el periodo vecino.
    periods = [
        scheduled_reports.display_rows(f"m{i}", _figures(tch=_fig(activas=a, activas_inicio=a, altas=10, bajas=6)))
        for i, a in enumerate((120, 3, 120))
    ]
    scheduled_reports.protect_series(*periods)
    assert {next(r for r in p if r["canal"] == "tch")["activas"] for p in periods} == {"<5"}
    for prev, cur in pairwise(periods):
        for a, b in zip(prev, cur, strict=True):
            assert _unknowns(a, b) != 1


def test_five_is_the_threshold() -> None:
    rows = {r["canal"]: r for r in scheduled_reports.display_rows("x", _figures(tch=_fig(altas=4, bajas=5)))}
    assert rows["tch"]["altas"] == "<5" and rows["tch"]["bajas"] == "5"


def test_churn_and_mrr_are_masked_with_small_inputs() -> None:
    mrr = {"virtualpos": (5_000_000.0, 500), "toku": (40_000.0, 3), "payku": (0.0, 0), "tch": (900_000.0, 90)}
    rows = {r["canal"]: r for r in scheduled_reports.display_rows("x", _figures(payku=_fig(bajas=2)), mrr)}
    assert rows["payku"]["churn"] == "—"
    assert rows["toku"]["mrr"] == "<5"
    assert rows["virtualpos"]["mrr"] == "5000000"
    assert rows["total"]["mrr"] == "—"
    assert rows["total"]["churn"] == "—"


def test_rows_without_mrr_leave_the_column_empty() -> None:
    assert {r["mrr"] for r in scheduled_reports.display_rows("x", _figures())} == {""}


# ----------------------------- armado completo, sin datos personales -----------------------------


def _assert_no_personal_data(*documents: str) -> None:
    for doc in documents:
        for first, last, rut, mail, phone in PEOPLE:
            for secret in (first, last, rut, rut.replace(".", ""), mail, phone, phone.replace(" ", "")):
                assert secret not in doc
        assert not RUT_RE.search(doc)
        assert not EMAIL_RE.search(doc)
        lowered = doc.lower()
        assert "<script" not in lowered and "javascript:" not in lowered
        assert "http://" not in lowered and "https://" not in lowered and "//" not in lowered
        assert "<img" not in lowered and "href=" not in lowered and "src=" not in lowered


def test_weekly_report_has_only_aggregate_figures(db_session) -> None:
    start, _ = scheduled_reports.weekly_period(NOW)
    _seed(db_session, "virtualpos1", 6, start, "w-vp")
    _seed(db_session, "toku", 3, start, "w-tk")
    built = scheduled_reports.build_weekly(db_session, NOW)
    assert built.kind == "weekly" and built.period_key == scheduled_reports.weekly_key(start)
    _assert_no_personal_data(built.html, built.csv_text, built.text, built.subject)
    rows = list(csv.DictReader(io.StringIO(built.csv_text)))
    assert list(rows[0]) == list(scheduled_reports.CSV_COLUMNS)
    assert len(rows) == 10  # 2 semanas x (4 canales + total)
    current = {r["canal"]: r for r in rows[5:]}
    assert current["VirtualPOS"]["altas"] == "6" and current["VirtualPOS"]["cobros_aprobados"] == "6"
    assert current["Toku"]["altas"] == "<5" and current["Toku"]["cobros_aprobados"] == "<5"
    assert current["Total"]["altas"] == "—"
    assert "&lt;5" in built.html and "Sincronizaciones" in built.html
    assert built.subject.startswith(f"[SynkmetriX · {scheduled_reports._env_label()}]")
    assert "Resumen semanal" in built.subject and built.csv_name.endswith(".csv")


def test_monthly_report_has_only_aggregate_figures_and_13_months(db_session) -> None:
    first, _ = scheduled_reports.monthly_period(NOW)
    _seed(db_session, "virtualpos1", 6, first + timedelta(days=3), "m-vp")
    _seed(db_session, "payku", 2, first + timedelta(days=3), "m-pk")
    built = scheduled_reports.build_monthly(db_session, NOW)
    assert built.period_key == scheduled_reports.monthly_key(first)
    _assert_no_personal_data(built.html, built.csv_text, built.text, built.subject)
    rows = list(csv.DictReader(io.StringIO(built.csv_text)))
    assert len(rows) == 13 * 5
    assert [r["periodo"] for r in rows[::5]] == sorted({r["periodo"] for r in rows})
    assert rows[-1]["periodo"] == f"{first:%Y-%m}"
    assert rows[-1]["canal"] == "Total" and rows[-1]["altas"] == "—"
    assert all(r["mrr"] == "" for r in rows[:-5])  # no hay MRR historico: solo el ultimo periodo
    assert "Cierre mensual" in built.subject


def test_building_does_not_write_sync_or_etl_runs(db_session) -> None:
    before = (db_session.scalar(select(func.count()).select_from(SyncRun)), db_session.scalar(select(func.count()).select_from(EtlRun)))
    scheduled_reports.build_weekly(db_session, NOW)
    after = (db_session.scalar(select(func.count()).select_from(SyncRun)), db_session.scalar(select(func.count()).select_from(EtlRun)))
    assert before == after


def test_sync_status_has_no_error_messages(db_session) -> None:
    db_session.add(SyncRun(source="toku", status="failed", started_at=NOW - timedelta(hours=1), finished_at=NOW,
                           error_message="falla con persona@ejemplo.org y 12.345.678-5"))
    db_session.flush()
    built = scheduled_reports.build_weekly(db_session, NOW)
    assert "persona@ejemplo.org" not in built.html and "12.345.678-5" not in built.html


# ----------------------------- envio con SMTP simulado -----------------------------


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []
    messages: ClassVar[list] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, host, port=0, timeout=None, **kw):
        self.host, self.port, self.timeout = host, port, timeout
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, **kw):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg, **kw):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        FakeSMTP.messages.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.messages, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "alert_email_from", "crm@ejemplo.test")
    monkeypatch.setattr(settings, "alert_smtp_host", "smtp.ejemplo.test")
    monkeypatch.setattr(settings, "alert_smtp_port", 587)
    monkeypatch.setattr(settings, "alert_smtp_user", "")
    monkeypatch.setattr(settings, "alert_smtp_password", "")
    monkeypatch.setattr(settings, "alert_smtp_starttls", True)
    return FakeSMTP


def test_send_report_builds_html_with_csv_attachment(smtp, db_session) -> None:
    built = scheduled_reports.build_weekly(db_session, NOW)
    ok, error = alerts.send_report(built.subject, built.text, built.html, [TO], ((built.csv_name, built.csv_text),))
    assert (ok, error) == (True, None)
    msg = smtp.messages[0]
    assert msg["To"] == TO and msg["Subject"] == built.subject
    assert msg.get_body(preferencelist=("html",)) is not None
    names = [part.get_filename() for part in msg.iter_attachments()]
    assert names == [built.csv_name]


def test_send_report_failure_returns_only_the_class_name(smtp, caplog) -> None:
    smtp.fail_with = OSError("smtp caido con persona@ejemplo.org")
    with caplog.at_level("WARNING"):
        ok, error = alerts.send_report("Asunto", "texto", "<p>html</p>", [TO])
    assert (ok, error) == (False, "OSError")
    assert "persona@ejemplo.org" not in caplog.text and TO not in caplog.text


def test_send_report_without_recipients_or_host_sends_nothing(smtp, monkeypatch) -> None:
    assert alerts.send_report("A", "t", "<p>h</p>", [])[0] is False
    monkeypatch.setattr(settings, "alert_smtp_host", "")
    assert alerts.send_report("A", "t", "<p>h</p>", [TO])[0] is False
    assert smtp.instances == [] and smtp.messages == []


def test_report_recipients_use_the_alert_parser(monkeypatch) -> None:
    monkeypatch.setattr(settings, "report_email_to", f" {TO} , {TO.upper()}, sin-arroba, ")
    assert alerts.report_recipients() == [TO]
    monkeypatch.setattr(settings, "report_email_to", "")
    assert alerts.report_recipients() == []

