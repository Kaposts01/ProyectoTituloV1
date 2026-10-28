"""Tanda 1 (revision de la opcion A): defectos del planificador puro, reproducidos primero en rojo."""

from datetime import date

from app.services import billing_plan as bp
from app.services.billing_plan import (
    PlanCharge,
    PlanInput,
    build_amount_change_plan,
    build_renewal_plan,
)

SUB = "sub-1"


def _inp(rt="change_amount", charges=(), **kw) -> PlanInput:
    base = {"request_type": rt, "subscription_external_id": SUB, "platform": "virtualpos1", "new_amount": 7000,
            "charges": tuple(charges), "charge_day": 15, "effective_month": "2026-11", "today": date(2026, 11, 10)}
    base.update(kw)
    return PlanInput(**base)


def _auto(i, d, amount=5000, status="pendiente") -> PlanCharge:
    return PlanCharge(f"a{i}", status, d, amount)


def _one_off(i, d, amount=5000, status="pendiente", code=None) -> PlanCharge:
    code = code or f"{SUB}-T{i}-{d:%Y%m%d}-{amount}"
    return PlanCharge(f"o{i}", status, d, amount, internal_code=code, is_crm=True, is_one_off=True)


# ----------------------------- 1. reemplazo de mes atrasado -----------------------------


def _month_of(a) -> str:
    return a.charge_date.strftime("%Y-%m")


def test_reemplazo_que_cae_en_el_mes_siguiente_va_a_revision_manual() -> None:
    """Hoy 31-oct, octubre atrasado: 'manana' (1-nov) ya es noviembre -> octubre a revision, noviembre sin duplicado."""
    today = date(2026, 10, 31)
    ch = [_auto(0, date(2026, 10, 15)), _auto(1, date(2026, 11, 15))]
    r = build_amount_change_plan(_inp(charges=ch, today=today, effective_month="2026-10", horizon_months=2))
    assert [m.month for m in r.manual_review] == ["2026-10"]
    assert [a.month for a in r.create] == ["2026-11"]
    assert all(_month_of(a) == a.month for a in r.create)  # ninguna fecha cruza de mes
    assert [a.charge_id for a in r.cancel] == ["a1"]  # el pendiente de octubre no se toca
    # tras aplicar: el estado resultante es consistente (sin acciones nuevas, sin duplicado en noviembre)
    applied = [ch[0], PlanCharge("n1", "pendiente", r.create[0].charge_date, 7000, r.create[0].internal_code, True)]
    again = build_amount_change_plan(_inp(charges=applied, today=today, effective_month="2026-10", horizon_months=2))
    assert not again.create and not again.cancel and again.unchanged == ("2026-11",)


def test_varios_meses_atrasados_solo_el_del_mes_actual_se_reemplaza() -> None:
    """Hoy 10-nov, dia 10: octubre (ya cerrado) a revision; noviembre se reemplaza dentro de noviembre."""
    r = build_amount_change_plan(_inp(charge_day=10, effective_month="2026-10", horizon_months=3))
    assert [m.month for m in r.manual_review] == ["2026-10"]
    assert [(a.month, a.charge_date) for a in r.create] == [("2026-11", date(2026, 11, 11)), ("2026-12", date(2026, 12, 10))]
    assert all(_month_of(a) == a.month for a in r.create)


def test_ultimo_dia_del_mes_el_reemplazo_no_cruza_a_otro_mes() -> None:
    r = build_amount_change_plan(_inp(charge_day=30, today=date(2026, 11, 30), horizon_months=1,
                                      charges=[_auto(0, date(2026, 11, 30))]))
    # el pendiente de HOY no se toca (item 4); sin pendiente, el reemplazo (1-dic) cruzaria de mes -> revision
    assert not r.create and not r.cancel
    r2 = build_amount_change_plan(_inp(charge_day=30, today=date(2026, 11, 30), horizon_months=1))
    assert [m.month for m in r2.manual_review] == ["2026-11"] and not r2.create


# ----------------------------- 2. cobros puntuales -----------------------------


def test_puntual_pendiente_en_el_mismo_mes_no_se_cancela() -> None:
    ch = [_auto(0, date(2026, 11, 15)), _one_off(7, date(2026, 11, 20))]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=1))
    assert [a.charge_id for a in r.cancel] == ["a0"]
    assert [a.month for a in r.create] == ["2026-11"]


def test_puntual_con_el_monto_nuevo_no_sustituye_al_regular() -> None:
    ch = [_auto(0, date(2026, 11, 15)), _one_off(7, date(2026, 11, 20), amount=7000)]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=1))
    assert [a.month for a in r.create] == ["2026-11"] and [a.charge_id for a in r.cancel] == ["a0"]
    assert not r.unchanged


def test_puntual_se_reconoce_por_patron_de_internal_code_aunque_no_venga_la_bandera() -> None:
    for code in (f"{SUB}-T42-20261120-5000", f"{SUB}-20261120-5000-oneoff"):
        c = PlanCharge("o1", "pendiente", date(2026, 11, 20), 5000, internal_code=code, is_crm=True)
        r = build_amount_change_plan(_inp(charges=[_auto(0, date(2026, 11, 15)), c], horizon_months=1))
        assert [a.charge_id for a in r.cancel] == ["a0"], code
    regular = PlanCharge("m1", "pendiente", date(2026, 11, 20), 5000, internal_code=f"{SUB}-202611-5000", is_crm=True)
    r = build_amount_change_plan(_inp(charges=[regular], horizon_months=1))
    assert [a.charge_id for a in r.cancel] == ["m1"]  # un manual regular del CRM si se cancela


def test_puntual_pagado_sigue_cubriendo_el_mes() -> None:
    r = build_amount_change_plan(_inp(charges=[_one_off(7, date(2026, 11, 3), status="pagado")], horizon_months=1))
    assert [(c.month, c.reason) for c in r.covered] == [("2026-11", "pagado")] and not r.create


def test_renovacion_no_salta_meses_por_un_puntual_lejano() -> None:
    crm = [PlanCharge(f"c{i}", "pendiente", date(*bp._add_months((2026, 11), i), 15), 7000, f"X{i}", True)
           for i in range(12)]
    far = _one_off(9, date(2028, 3, 20))
    r = build_renewal_plan(_inp("renew_calendar", [*crm, far], effective_month=None))
    assert r.summary.horizon_start == "2027-11"
    only_one_off = build_renewal_plan(_inp("renew_calendar", [far], effective_month=None))
    assert only_one_off.errors[0].code == "no_crm_calendar"


def test_el_dia_de_cobro_no_se_deduce_de_un_puntual() -> None:
    ch = [_auto(0, date(2026, 10, 15), status="pagado"), _one_off(9, date(2026, 11, 3), status="pagado")]
    r = build_amount_change_plan(_inp(charges=ch, charge_day=None, effective_month="2026-12", horizon_months=1))
    assert r.create[0].charge_date == date(2026, 12, 15)


# ----------------------------- 4. cobro con fecha de hoy -----------------------------


def test_pendiente_fechado_hoy_no_se_cancela_ni_se_reemplaza() -> None:
    today = date(2026, 11, 10)
    r = build_amount_change_plan(_inp(charge_day=10, horizon_months=2, today=today,
                                      charges=[_auto(0, today), _auto(1, date(2026, 12, 10))]))
    assert [a.month for a in r.create] == ["2026-12"] and [a.charge_id for a in r.cancel] == ["a1"]
    assert any(w.code == "due_today_kept" and w.month == "2026-11" for w in r.warnings)
    assert r.kept_due_today == ("2026-11",)
    assert plan_json_has_kept(r)


def plan_json_has_kept(r) -> bool:
    return bp.plan_to_preview_json(r)["kept_due_today"] == ["2026-11"]


def test_sin_pendiente_de_hoy_el_mes_atrasado_sigue_la_logica_de_ventana() -> None:
    r = build_amount_change_plan(_inp(charge_day=10, horizon_months=1, charges=[_auto(0, date(2026, 11, 5))]))
    assert r.create[0].charge_date == date(2026, 11, 11) and [a.charge_id for a in r.cancel] == ["a0"]
    assert not r.kept_due_today
