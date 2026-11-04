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


def test_replacement_that_falls_in_the_month_next_is_attributed_by_internal_code() -> None:
    """DEC-30 (BILL-18): hoy 31-oct, octubre atrasado: el reemplazo se fecha manana (1-nov) con el codigo de OCTUBRE;
    noviembre conserva su propio cobro y, tras aplicar, no hay duplicado en noviembre."""
    today = date(2026, 10, 31)
    ch = [_auto(0, date(2026, 10, 15)), _auto(1, date(2026, 11, 15))]
    r = build_amount_change_plan(_inp(charges=ch, today=today, effective_month="2026-10", horizon_months=2))
    assert not r.manual_review
    assert [(a.month, a.charge_date, a.internal_code) for a in r.create] == [
        ("2026-10", date(2026, 11, 1), "sub-1-202610-7000"), ("2026-11", date(2026, 11, 15), "sub-1-202611-7000")]
    assert [a.charge_id for a in r.cancel] == ["a0", "a1"]  # el vencido de octubre tambien se cancela (JB-08)
    # tras aplicar: el estado resultante es consistente (sin acciones nuevas, sin duplicado en noviembre)
    applied = [replace_status(ch[0]), replace_status(ch[1])] + [
        PlanCharge(f"n{i}", "pendiente", a.charge_date, 7000, a.internal_code, True) for i, a in enumerate(r.create)]
    again = build_amount_change_plan(_inp(charges=applied, today=today, effective_month="2026-10", horizon_months=2))
    assert not again.create and not again.cancel and again.unchanged == ("2026-10", "2026-11")


def replace_status(c: PlanCharge, status: str = "cancelado") -> PlanCharge:
    return PlanCharge(c.charge_id, status, c.charge_date, c.amount, c.internal_code, c.is_crm, c.is_one_off)


def test_varios_months_overdue_are_spaced_from_tomorrow() -> None:
    """Hoy 10-nov, dia 10: octubre (31 dias) se fecha manana; noviembre (vence hoy) pasado manana (JB-09)."""
    r = build_amount_change_plan(_inp(charge_day=10, effective_month="2026-10", horizon_months=3))
    assert not r.manual_review
    assert [(a.month, a.charge_date) for a in r.create] == [
        ("2026-10", date(2026, 11, 11)), ("2026-11", date(2026, 11, 12)), ("2026-12", date(2026, 12, 10))]
    assert [bp.code_month(a.internal_code, SUB) for a in r.create] == ["2026-10", "2026-11", "2026-12"]


def test_last_day_of_the_month_the_replacement_crosses_to_tomorrow() -> None:
    r = build_amount_change_plan(_inp(charge_day=30, today=date(2026, 11, 30), horizon_months=1,
                                      charges=[_auto(0, date(2026, 11, 30))]))
    # el pendiente de HOY no se toca (item 4)
    assert not r.create and not r.cancel
    # sin pendiente: el reemplazo se fecha manana (1-dic) y queda atribuido a noviembre por su internal_code
    r2 = build_amount_change_plan(_inp(charge_day=30, today=date(2026, 11, 30), horizon_months=1))
    assert not r2.manual_review
    assert [(a.month, a.charge_date, a.internal_code) for a in r2.create] == [
        ("2026-11", date(2026, 12, 1), "sub-1-202611-7000")]


# ----------------------------- 2. cobros puntuales -----------------------------


def test_one_off_pending_in_the_same_month_no_cancels() -> None:
    ch = [_auto(0, date(2026, 11, 15)), _one_off(7, date(2026, 11, 20))]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=1))
    assert [a.charge_id for a in r.cancel] == ["a0"]
    assert [a.month for a in r.create] == ["2026-11"]


def test_one_off_with_the_amount_new_no_replaces_on_regular() -> None:
    ch = [_auto(0, date(2026, 11, 15)), _one_off(7, date(2026, 11, 20), amount=7000)]
    r = build_amount_change_plan(_inp(charges=ch, horizon_months=1))
    assert [a.month for a in r.create] == ["2026-11"] and [a.charge_id for a in r.cancel] == ["a0"]
    assert not r.unchanged


def test_one_off_recognizes_by_pattern_of_internal_code_even_if_no_comes_the_flag() -> None:
    for code in (f"{SUB}-T42-20261120-5000", f"{SUB}-20261120-5000-oneoff"):
        c = PlanCharge("o1", "pendiente", date(2026, 11, 20), 5000, internal_code=code, is_crm=True)
        r = build_amount_change_plan(_inp(charges=[_auto(0, date(2026, 11, 15)), c], horizon_months=1))
        assert [a.charge_id for a in r.cancel] == ["a0"], code
    regular = PlanCharge("m1", "pendiente", date(2026, 11, 20), 5000, internal_code=f"{SUB}-202611-5000", is_crm=True)
    r = build_amount_change_plan(_inp(charges=[regular], horizon_months=1))
    assert [a.charge_id for a in r.cancel] == ["m1"]  # un manual regular del CRM si se cancela


def test_one_off_paid_keeps_covering_the_month() -> None:
    r = build_amount_change_plan(_inp(charges=[_one_off(7, date(2026, 11, 3), status="pagado")], horizon_months=1))
    assert [(c.month, c.reason) for c in r.covered] == [("2026-11", "pagado")] and not r.create


def test_renewal_no_skips_months_by_a_one_off_far() -> None:
    crm = [PlanCharge(f"c{i}", "pendiente", date(*bp._add_months((2026, 11), i), 15), 7000, f"X{i}", True)
           for i in range(12)]
    far = _one_off(9, date(2028, 3, 20))
    r = build_renewal_plan(_inp("renew_calendar", [*crm, far], effective_month=None))
    assert r.summary.horizon_start == "2027-11"
    only_one_off = build_renewal_plan(_inp("renew_calendar", [far], effective_month=None))
    assert only_one_off.errors[0].code == "no_crm_calendar"


def test_the_day_of_charge_no_deduced_of_a_one_off() -> None:
    ch = [_auto(0, date(2026, 10, 15), status="pagado"), _one_off(9, date(2026, 11, 3), status="pagado")]
    r = build_amount_change_plan(_inp(charges=ch, charge_day=None, effective_month="2026-12", horizon_months=1))
    assert r.create[0].charge_date == date(2026, 12, 15)


# ----------------------------- 4. cobro con fecha de hoy -----------------------------


def test_pending_dated_today_no_cancels_nor_replaces() -> None:
    today = date(2026, 11, 10)
    r = build_amount_change_plan(_inp(charge_day=10, horizon_months=2, today=today,
                                      charges=[_auto(0, today), _auto(1, date(2026, 12, 10))]))
    assert [a.month for a in r.create] == ["2026-12"] and [a.charge_id for a in r.cancel] == ["a1"]
    assert any(w.code == "due_today_kept" and w.month == "2026-11" for w in r.warnings)
    assert r.kept_due_today == ("2026-11",)
    assert plan_json_has_kept(r)


def plan_json_has_kept(r) -> bool:
    return bp.plan_to_preview_json(r)["kept_due_today"] == ["2026-11"]


def test_without_pending_of_today_the_month_overdue_keeps_the_logic_of_window() -> None:
    r = build_amount_change_plan(_inp(charge_day=10, horizon_months=1, charges=[_auto(0, date(2026, 11, 5))]))
    assert r.create[0].charge_date == date(2026, 11, 11) and [a.charge_id for a in r.cancel] == ["a0"]
    assert not r.kept_due_today
