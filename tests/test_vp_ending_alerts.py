"""d189: alerta de suscripciones de VirtualPOS que terminan en los proximos N dias (apagada por defecto).

Datos sinteticos en la base de test (`crm_test`, transaccion revertida) y SMTP falso en memoria de `test_alerts`:
nunca se abre un socket ni se envia un correo real. Los datos personales ficticios sirven para comprobar que NINGUNA
salida (condicion ni correo) los incluye.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import test_alerts
from sqlalchemy import delete
from test_alerts import PII_MAIL, PII_RUT, _subjects, _text

from app.core.config import settings
from app.models.vp import VpCharge, VpPlan, VpSubscription
from app.services import alerts, vp_ending_alerts

_alerts_db_session = test_alerts.db_session
_alerts_smtp = test_alerts.smtp

NOW = datetime(2099, 6, 1, 15, 0, tzinfo=UTC)  # 11:00 en Chile: hoy = 2099-06-01
TODAY = date(2099, 6, 1)
KIND = vp_ending_alerts.KIND
PII_NAME = "Juanita Pérez Soto"
SUB_PREFIX = "sub-pii-"


@pytest.fixture
def db_session(_alerts_db_session):
    session = _alerts_db_session
    session.execute(delete(VpCharge))
    session.execute(delete(VpSubscription))
    session.execute(delete(VpPlan))
    session.flush()
    return session


@pytest.fixture
def smtp(_alerts_smtp):
    return _alerts_smtp


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "alert_vp_ending_soon_enabled", True)
    monkeypatch.setattr(settings, "alert_vp_ending_soon_days", 60)


def _plan(db, platform="virtualpos1", plan_type="MONTO_FIJO", num_charges=12, frequency="mensual") -> str:
    external_id = f"plan-{uuid.uuid4().hex[:8]}"
    db.add(VpPlan(platform=platform, external_id=external_id, name=f"Plan de {PII_NAME}", plan_type=plan_type,
                  raw_payload={"num_charges": str(num_charges), "frequency_type": frequency}))
    db.flush()
    return external_id


def _sub(db, plan, *, platform="virtualpos1", status="ACTIVA", renewal="F", charges=(), start=None, removed=False):
    external_id = f"{SUB_PREFIX}{uuid.uuid4().hex[:8]}"
    db.add(VpSubscription(
        platform=platform, external_id=external_id, plan_external_id=plan, status=status, automatic_renewal=renewal,
        client_external_id=f"cli-{PII_RUT}", client_social_id=f"{PII_RUT}-{external_id[-4:]}", suscription_date=start,
        raw_payload={"email": PII_MAIL, "name": PII_NAME},
        removed_at=NOW if removed else None))
    for when in charges:
        db.add(VpCharge(platform=platform, external_id=f"chg-{uuid.uuid4().hex[:8]}", subscription_external_id=external_id,
                        client_external_id=f"cli-{PII_RUT}", charge_date=when, status="PENDIENTE",
                        raw_payload={"email": PII_MAIL}))
    db.flush()
    return external_id


def _conds(db):
    return {c.key: c for c in alerts.evaluate_conditions(db, NOW) if c.key.startswith(KIND)}


def _seed(db):
    plan1 = _plan(db)
    plan2 = _plan(db, platform="virtualpos2")
    variable = _plan(db, plan_type="MONTO_VARIABLE")
    # Dentro de la ventana (hoy .. hoy + 60 dias)
    _sub(db, plan1, charges=(TODAY - timedelta(days=30), TODAY + timedelta(days=10)))       # 2099-06
    _sub(db, plan1, charges=(TODAY + timedelta(days=40),))                                     # 2099-07
    _sub(db, plan2, platform="virtualpos2", charges=(TODAY + timedelta(days=60),))             # 2099-07 (borde)
    _sub(db, plan1, start=datetime(2098, 7, 15, tzinfo=UTC).replace(tzinfo=None), charges=())  # sin cargos: 12 x mensual -> 2099-07-15
    # Fuera de la ventana
    _sub(db, plan1, charges=(TODAY + timedelta(days=61),))
    _sub(db, plan1, charges=(TODAY + timedelta(days=400),))
    # Ya paso pero sigue ACTIVA
    _sub(db, plan1, charges=(date(2099, 4, 20),))
    _sub(db, plan2, platform="virtualpos2", charges=(TODAY - timedelta(days=1),))              # 2099-05
    # No cuentan
    _sub(db, plan1, status="CANCELADA", charges=(TODAY + timedelta(days=5),))
    _sub(db, plan1, renewal="T", charges=(TODAY + timedelta(days=5),))
    _sub(db, plan1, removed=True, charges=(TODAY + timedelta(days=5),))
    _sub(db, variable, charges=(TODAY + timedelta(days=5),))
    _sub(db, _plan(db, num_charges=0, frequency=""), charges=())  # sin fecha estimable


def test_flag_off_by_default_generates_nothing(db_session, smtp):
    assert settings.alert_vp_ending_soon_enabled is False  # valor por defecto (el .env no la enciende)
    assert KIND not in alerts.active_kinds()
    _seed(db_session)
    assert _conds(db_session) == {}
    test_alerts._check(db_session, at=NOW)
    assert not [s for s in _subjects() if "VirtualPOS" in s]


def test_alerts_enabled_off_sends_nothing_even_with_the_flag(db_session, smtp, enabled, monkeypatch):
    monkeypatch.setattr(settings, "alerts_enabled", False)
    _seed(db_session)
    result = test_alerts._check(db_session, at=NOW)
    assert result.skipped == "disabled" and smtp.messages == []


def test_upcoming_counts_by_platform_and_month_inside_the_window(db_session, smtp, enabled):
    _seed(db_session)
    grouped = vp_ending_alerts.counts(db_session, NOW)
    assert grouped["upcoming"] == [("virtualpos1", "2099-06", 1), ("virtualpos1", "2099-07", 2),
                                   ("virtualpos2", "2099-07", 1)]
    cond = _conds(db_session)[f"{KIND}:upcoming"]
    assert cond.text.startswith("4 suscripción(es) activa(s)") and "próximos 60 días" in cond.text
    assert "virtualpos1 · 2099-07: 2" in cond.details
    assert any("TER-01" in d and "automatic_renewal = F" in d for d in cond.details)


def test_window_parameter_changes_the_range(db_session, smtp, enabled, monkeypatch):
    monkeypatch.setattr(settings, "alert_vp_ending_soon_days", 15)
    _seed(db_session)
    assert vp_ending_alerts.counts(db_session, NOW)["upcoming"] == [("virtualpos1", "2099-06", 1)]


def test_past_end_group_is_active_subscriptions_whose_last_charge_already_passed(db_session, smtp, enabled):
    _seed(db_session)
    assert vp_ending_alerts.counts(db_session, NOW)["past_end"] == [("virtualpos1", "2099-04", 1),
                                                                    ("virtualpos2", "2099-05", 1)]
    cond = _conds(db_session)[f"{KIND}:past_end"]
    assert cond.text.startswith("2 suscripción(es)") and "desfase de la sincronización" in cond.text


def test_nothing_in_range_means_no_condition(db_session, smtp, enabled):
    plan = _plan(db_session)
    _sub(db_session, plan, charges=(TODAY + timedelta(days=200),))
    assert _conds(db_session) == {}


def test_no_output_contains_personal_data(db_session, smtp, enabled):
    _seed(db_session)
    conds = _conds(db_session)
    assert set(conds) == {f"{KIND}:upcoming", f"{KIND}:past_end"}
    result = test_alerts._check(db_session, at=NOW)
    assert result.sent >= 2
    mails = [m for m in smtp.messages if "VirtualPOS" in m["Subject"]]
    assert len(mails) == 2
    outputs = [m["Subject"] + "\n" + _text(m) for m in mails]
    outputs += [" ".join((c.key, c.title, c.text, *c.details)) for c in conds.values()]
    for out in outputs:
        for secret in (PII_MAIL, PII_RUT, PII_NAME, SUB_PREFIX, "plan-", "cli-", "chg-"):
            assert secret not in out
        assert "@" not in out.replace("@example.test", "")


def test_recovery_notice_when_the_flag_is_turned_off(db_session, smtp, enabled, monkeypatch):
    _seed(db_session)
    test_alerts._check(db_session, at=NOW)
    monkeypatch.setattr(settings, "alert_vp_ending_soon_enabled", False)
    smtp.messages.clear()
    test_alerts._check(db_session, at=NOW + timedelta(minutes=15))
    recovered = [s for s in _subjects() if s.startswith("[SynkmetriX") and "Recuperado" in s and "VirtualPOS" in s]
    assert len(recovered) == 2
