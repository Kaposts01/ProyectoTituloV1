"""Calculo puro del plan de cambio de cobros (sin BD, sin proveedor)."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime

from app.services import billing_plan as bp
from app.services.billing_plan import (
    PlanCharge,
    PlanInput,
    build_amount_change_plan,
    build_date_change_plan,
    build_one_off_plan,
    build_renewal_plan,
    plan_to_preview_json,
)
from app.services.rejected_month import CHILE_TZ

SUB = "sub-1"
TODAY = date(2026, 11, 10)


def _inp(rt="change_amount", charges=(), **kw) -> PlanInput:
    base = {"request_type": rt, "subscription_external_id": SUB, "platform": "virtualpos1", "new_amount": 7000,
            "charges": tuple(charges), "charge_day": 15, "effective_month": "2026-11", "today": TODAY}
    base.update(kw)
    return PlanInput(**base)


def _auto(i, d, amount=5000, status="pendiente") -> PlanCharge:
    return PlanCharge(f"a{i}", status, d, amount)


def _manual(i, d, amount=5000, status="pendiente", crm=True) -> PlanCharge:
    return PlanCharge(f"m{i}", status, d, amount, internal_code=f"X-{i}", is_crm=crm)


def _autos_12(day=15, start=(2026, 11), amount=5000, n=12):
    out = []
    for i in range(n):
        y, m = bp._add_months(start, i)
        out.append(_auto(i, date(y, m, day), amount))
    return out


def test_cambio_de_monto_simple_12_meses_sin_cobros_previos() -> None:
    r = build_amount_change_plan(_inp())
    assert len(r.create) == 12 and not r.cancel and not r.noop
    assert r.create[0].month == "2026-11" and r.create[0].charge_date == date(2026, 11, 15)
    assert r.create[-1].month == "2027-10"
    assert r.create[0].internal_code == "sub-1-202611-7000"
    assert r.summary.horizon_end == "2027-10"


def test_automaticos_dentro_del_horizonte_se_cancelan_y_fuera_se_conservan() -> None:
    r = build_amount_change_plan(_inp(charges=_autos_12(n=15)))
    assert len(r.create) == 12 and len(r.cancel) == 12
    assert {c.charge_id for c in r.cancel} == {f"a{i}" for i in range(12)}
    assert [k.charge_id for k in r.kept_automatic_after_horizon] == ["a12", "a13", "a14"]


def test_mes_con_pagado_procesando_rechazado_queda_cubierto() -> None:
    ch = [_auto(0, date(2026, 11, 15), status="Pagado"), _auto(1, date(2026, 12, 15), status="procesando"),
          _auto(2, date(2027, 1, 15), status="rechazado"), _auto(3, date(2027, 2, 15))]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=4))
    assert [(c.month, c.reason) for c in r.covered] == [
        ("2026-11", "pagado"), ("2026-12", "procesando"), ("2027-01", "rechazado")]
    assert [a.month for a in r.create] == ["2027-02"] and [a.charge_id for a in r.cancel] == ["a3"]


def test_estado_desconocido_es_bloqueante_con_warning() -> None:
    r = build_amount_change_plan(_inp(charges=[_auto(0, date(2026, 11, 15), status="raro")], horizon_months=1))
    assert r.covered[0].reason == "unknown_status" and not r.create
    assert r.warnings[0].code == "unknown_status"


def test_ventana_31_vs_32_dias_y_fecha_de_manana() -> None:
    # charge_day 10 -> dia 10 de cada mes. Hoy 2026-11-10.
    # Oct 10 esta 31 dias atras (borde incluido); Sep 10 esta 61 dias atras.
    r = build_amount_change_plan(_inp(charge_day=10, effective_month="2026-10", horizon_months=1))
    assert r.create[0].charge_date == date(2026, 11, 11) and r.create[0].month == "2026-10"
    r32 = build_amount_change_plan(_inp(charge_day=9, effective_month="2026-10", horizon_months=1))
    assert not r32.create and r32.manual_review[0].days_overdue == 32 and r32.noop is False
    r31 = build_amount_change_plan(_inp(charge_day=10, effective_month="2026-10", horizon_months=1))
    assert not r31.manual_review
    # mes en revision manual: no se cancela su pendiente vencido
    stale = _auto(0, date(2026, 10, 9))
    rr = build_amount_change_plan(_inp(charge_day=9, effective_month="2026-10", horizon_months=1, charges=[stale]))
    assert rr.manual_review and not rr.cancel


def test_pendiente_vencido_dentro_de_ventana_se_reemplaza_y_cancela() -> None:
    r = build_amount_change_plan(_inp(charge_day=5, horizon_months=1, charges=[_auto(0, date(2026, 11, 5))]))
    assert r.create[0].charge_date == date(2026, 11, 11) and r.cancel[0].charge_id == "a0"


def test_hoy_en_hora_chile_cruce_de_medianoche_utc(monkeypatch) -> None:
    # 2026-11-11 01:00 UTC = 2026-11-10 22:00 en Chile (UTC-3): hoy sigue siendo el 10.
    monkeypatch.setattr(bp, "now_chile", lambda: datetime(2026, 11, 11, 1, 0, tzinfo=UTC).astimezone(CHILE_TZ))
    r = build_amount_change_plan(_inp(today=None, charge_day=5, horizon_months=1))
    assert r.create[0].charge_date == date(2026, 11, 11)  # manana en Chile, no el 12


def test_varios_meses_atrasados_se_espacian_un_dia() -> None:
    r = build_amount_change_plan(_inp(charge_day=10, effective_month="2026-10", horizon_months=2))
    assert [a.charge_date for a in r.create] == [date(2026, 11, 11), date(2026, 11, 12)]


def test_manual_preexistente_del_crm_se_cancela_y_ajeno_queda_intacto() -> None:
    ch = [_manual(1, date(2026, 11, 15), crm=True), _manual(2, date(2026, 12, 15), crm=False)]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=2))
    assert [a.charge_id for a in r.cancel] == ["m1"]
    assert "m2" not in {a.charge_id for a in r.cancel}
    assert any(w.code == "foreign_manual_kept" and w.month == "2026-12" for w in r.warnings)
    assert [a.month for a in r.create] == ["2026-11", "2026-12"]  # el ajeno no cuenta como reemplazo


def test_noop_cuando_ya_hay_un_pendiente_correcto_por_mes() -> None:
    r = build_amount_change_plan(_inp(charges=_autos_12(amount=7000)))
    assert r.noop and not r.create and not r.cancel and len(r.unchanged) == 12
    # idempotencia tras aplicar: crear 12 y reinyectarlos como manuales del CRM -> noop
    applied = [PlanCharge(f"n{i}", "pendiente", a.charge_date, a.amount, a.internal_code, True)
               for i, a in enumerate(build_amount_change_plan(_inp()).create)]
    assert build_amount_change_plan(_inp(charges=applied)).noop


def test_noop_cambio_de_fecha_requiere_misma_fecha() -> None:
    ch = _autos_12(day=20, amount=7000)
    assert build_date_change_plan(_inp("change_date", ch, new_charge_day=20)).noop
    assert not build_date_change_plan(_inp("change_date", ch, new_charge_day=25)).noop


def test_charge_day_31_en_febrero_y_bisiesto() -> None:
    r = build_amount_change_plan(_inp(charge_day=31, effective_month="2027-01", horizon_months=2, today=date(2026, 12, 1)))
    assert [a.charge_date for a in r.create] == [date(2027, 1, 31), date(2027, 2, 28)]
    r2 = build_amount_change_plan(_inp(charge_day=30, effective_month="2028-02", horizon_months=2, today=date(2026, 12, 1)))
    assert [a.charge_date for a in r2.create] == [date(2028, 2, 29), date(2028, 3, 30)]
    assert bp.month_date((2027, 4), 31) == date(2027, 4, 30)


def test_renovacion_desde_el_ultimo_mes_programado_por_el_crm() -> None:
    crm = [PlanCharge(f"c{i}", "pendiente", date(*bp._add_months((2026, 11), i), 15), 7000, f"X{i}", True)
           for i in range(12)]
    autos_after = _autos_12(start=(2027, 11), n=3)  # automaticos de VP posteriores (monto antiguo)
    r = build_renewal_plan(_inp("renew_calendar", crm + autos_after, new_amount=7000, effective_month=None))
    assert r.summary.horizon_start == "2027-11" and r.summary.horizon_end == "2028-10"
    assert len(r.create) == 12 and {c.charge_id for c in r.cancel} == {"a0", "a1", "a2"}
    err = build_renewal_plan(_inp("renew_calendar", _autos_12()))
    assert err.errors[0].code == "no_crm_calendar"


def test_cobro_puntual() -> None:
    r = build_one_off_plan(_inp("one_off", [_auto(0, date(2026, 12, 15))], one_off_date=date(2026, 12, 20), task_ref="42"))
    assert len(r.create) == 1 and not r.cancel
    assert r.create[0].internal_code == "sub-1-T42-20261220-7000"
    assert any(w.code == "pending_same_month" for w in r.warnings)
    again = build_one_off_plan(_inp("one_off", [PlanCharge("p", "pendiente", date(2026, 12, 20), 7000, r.create[0].internal_code, True)],
                                    one_off_date=date(2026, 12, 20), task_ref="42"))
    assert again.noop
    past = build_one_off_plan(_inp("one_off", one_off_date=TODAY))
    assert past.errors[0].code == "past_charge_date"


def test_cambio_de_fecha_reprograma_y_conserva_m0_futuro() -> None:
    # hoy 10; dia 25 -> 5. M0 (nov) conserva su cobro del 25; dic en adelante pasa al dia 5.
    ch = [_auto(0, date(2026, 11, 25), 7000), _auto(1, date(2026, 12, 25), 7000)]
    r = build_date_change_plan(_inp("change_date", ch, new_charge_day=5, horizon_months=2))
    assert r.unchanged == ("2026-11",)
    assert [(a.month, a.charge_date) for a in r.create] == [("2026-12", date(2026, 12, 5))]
    assert r.create[0].internal_code == "sub-1-202612-7000-d05"  # distinto al del cobro viejo
    assert [a.charge_id for a in r.cancel] == ["a1"]


def test_determinismo_y_serializacion() -> None:
    inp = _inp(charges=_autos_12(n=14))
    a, b = build_amount_change_plan(inp), build_amount_change_plan(replace(inp))
    assert a == b
    pa = plan_to_preview_json(a)
    assert pa == plan_to_preview_json(b)
    assert json.loads(json.dumps(pa)) == pa
    assert set(pa) >= {"create", "cancel", "covered", "manual_review"}


def test_cancel_depende_de_todos_los_create_y_van_despues() -> None:
    r = build_amount_change_plan(_inp(charges=_autos_12(), horizon_months=3))
    codes = tuple(a.internal_code for a in r.create)
    assert len(codes) == 3 and all(c.depends_on == codes for c in r.cancel)
    order = r.ordered_actions
    assert [a.kind for a in order] == ["create"] * 3 + ["cancel"] * 3


def test_doble_pendiente_en_un_mes_emite_warning() -> None:
    ch = [_auto(0, date(2026, 11, 15)), _manual(1, date(2026, 11, 20))]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=1))
    assert any(w.code == "multiple_pending" for w in r.warnings)
    assert {a.charge_id for a in r.cancel} == {"a0", "m1"}


def test_validaciones_tipadas() -> None:
    assert build_amount_change_plan(_inp(new_amount=0)).errors[0].code == "invalid_amount"
    assert build_amount_change_plan(_inp(new_amount=-5)).errors[0].code == "invalid_amount"
    assert build_amount_change_plan(_inp(charge_day=32)).errors[0].code == "invalid_charge_day"
    assert build_date_change_plan(_inp("change_date")).errors[0].code == "missing_charge_day"
    assert build_amount_change_plan(_inp(effective_month="2026-13")).errors[0].code == "invalid_effective_month"
    assert build_amount_change_plan(_inp(charge_day=None)).errors[0].code == "missing_charge_day"


def test_variation_pct_y_cobros_afectados() -> None:
    up = build_amount_change_plan(_inp(charges=_autos_12(), new_amount=7500, horizon_months=4))
    s = up.summary
    assert s.variation_pct == 50.0 and s.previous_amount == 5000 and s.amount_delta == 2500
    assert s.affected_charges == 8 and s.total_delta == 4 * 7500 - 4 * 5000
    down = build_amount_change_plan(_inp(charges=_autos_12(), new_amount=2000, horizon_months=2))
    assert down.summary.variation_pct == 60.0
    base = build_amount_change_plan(_inp(previous_amount=10000, new_amount=5000))
    assert base.summary.variation_pct == 50.0
    assert build_amount_change_plan(_inp()).summary.variation_pct is None  # sin base conocida
