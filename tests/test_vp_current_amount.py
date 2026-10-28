"""Monto vigente VP: ultimo monto cobrado (helper, ETL, KPI MRR, recuperador). Todo en transaccion con rollback."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import recovery, staging
from app.models.crm import Charge as CCharge
from app.models.crm import Subscription as CSub
from app.models.vp import VpCharge, VpPlan, VpSubscription
from app.services import channel_consolidation as cc
from app.services import vp_current_amount
from app.services.rejected_month import now_chile
from app.services.vp_current_amount import load_monto_vigente, pick_monto_vigente
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

P = "virtualpos1"
CHILE = ZoneInfo("America/Santiago")
TODAY = now_chile().date()  # 'hoy' en hora Chile, igual que el servicio (evita tests intermitentes)


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _vp_charge(ext: str, sub: str, status: str, days: int, amount: str | None) -> VpCharge:
    return VpCharge(platform=P, external_id=ext, subscription_external_id=sub, status=status, charge_date=_d(days), amount=amount)


def _vp_sub(ext: str, amount: str | None = "5000", plan: str | None = None, status: str = "ACTIVA") -> VpSubscription:
    return VpSubscription(platform=P, external_id=ext, status=status, amount=amount, plan_external_id=plan)


def test_helper_ultimo_pagado_procesando_futuros_plan_y_desempate(db_session: Session) -> None:  # noqa: F811
    db_session.add_all([
        # a: el ultimo cargo pagado/procesando (<= hoy) manda; rechazado y futuro se ignoran
        _vp_sub("vca-a", "5000"),
        _vp_charge("vca-a1", "vca-a", "pagado", -60, "5000"),
        _vp_charge("vca-a2", "vca-a", "pagado", -30, "6000"),
        _vp_charge("vca-a3", "vca-a", "rechazado", -5, "9999"),
        _vp_charge("vca-a4", "vca-a", "pagado", 400, "8888"),
        # b: procesando mas reciente que el pagado
        _vp_sub("vca-b", "5000"),
        _vp_charge("vca-b1", "vca-b", "pagado", -40, "5500"),
        _vp_charge("vca-b2", "vca-b", "Procesando", -2, "5700"),
        # c: solo cargos futuros/rechazados -> monto de la suscripcion
        _vp_sub("vca-c", "4000"),
        _vp_charge("vca-c1", "vca-c", "pagado", 30, "1"),
        _vp_charge("vca-c2", "vca-c", "rechazado", -3, "2"),
        # d: sin monto de suscripcion -> monto del plan
        _vp_sub("vca-d", None, plan="vca-plan"),
        VpPlan(platform=P, external_id="vca-plan", amount="3500"),
        # e: misma fecha -> desempate determinista por external_id mayor
        _vp_sub("vca-e", "100"),
        _vp_charge("vca-e1", "vca-e", "pagado", -10, "7000"),
        _vp_charge("vca-e2", "vca-e", "pagado", -10, "7100"),
        # f: cargo mas reciente con monto no numerico se descarta
        _vp_sub("vca-f", "100"),
        _vp_charge("vca-f1", "vca-f", "pagado", -20, "2500"),
        _vp_charge("vca-f2", "vca-f", "pagado", -1, "n/a"),
    ])
    db_session.flush()

    result = load_monto_vigente(db_session, family="vp", sources=[P])
    assert result[(P, "vca-a")] == Decimal("6000")
    assert result[(P, "vca-b")] == Decimal("5700")
    assert result[(P, "vca-c")] == Decimal("4000")
    assert result[(P, "vca-d")] == Decimal("3500")
    assert result[(P, "vca-e")] == Decimal("7100")
    assert result[(P, "vca-f")] == Decimal("2500")


def test_helper_una_sola_consulta_de_cargos_sin_n_mas_1(db_session: Session) -> None:  # noqa: F811
    db_session.add_all([_vp_sub(f"vcn-{i}") for i in range(5)] + [_vp_charge(f"vcn-c{i}", f"vcn-{i}", "pagado", -1, "1000") for i in range(5)])
    db_session.flush()
    statements: list[str] = []
    from sqlalchemy import event

    conn = db_session.connection()
    listener = lambda _c, _cur, stmt, *_a: statements.append(stmt)  # noqa: E731
    event.listen(conn, "before_cursor_execute", listener)
    try:
        load_monto_vigente(db_session, family="vp", sources=[P])
    finally:
        event.remove(conn, "before_cursor_execute", listener)
    assert len(statements) == 3  # cargos (DISTINCT ON) + planes + suscripciones


def test_pick_monto_vigente_pura() -> None:
    rows = [
        ("c1", "pagado", _d(-30), "100"),
        ("c2", "procesando", _d(-3), "250"),
        ("c3", "pagado", _d(90), "999"),
        ("c4", "rechazado", _d(-1), "777"),
    ]
    assert pick_monto_vigente(rows, fallback="50") == Decimal("250")
    assert pick_monto_vigente([rows[2], rows[3]], fallback="50") == Decimal("50")
    assert pick_monto_vigente([], fallback=None) is None


# -- 'Hoy' en hora Chile (no UTC) ----------------------------------------------

def _fake_chile(monkeypatch, *args: int) -> datetime:
    fake = datetime(*args, tzinfo=CHILE)
    monkeypatch.setattr(vp_current_amount, "now_chile", lambda: fake)
    return fake


def test_pick_borde_chile_31_enero_noche_utc_ya_es_febrero(monkeypatch) -> None:
    # Chile 2099-01-31 22:00 (verano, UTC-3) == UTC 2099-02-01 01:00
    fake = _fake_chile(monkeypatch, 2099, 1, 31, 22, 0)
    assert fake.astimezone(ZoneInfo("UTC")).date() == date(2099, 2, 1)
    rows = [("c1", "pagado", "2099-01-31", "100"), ("c2", "pagado", "2099-02-01", "200")]
    assert pick_monto_vigente(rows, fallback="50") == Decimal("100")
    assert pick_monto_vigente([rows[1]], fallback="50") == Decimal("50")


def test_pick_borde_chile_1_febrero_madrugada_utc_aun_es_enero(monkeypatch) -> None:
    # Chile siempre va detras de UTC, asi que "UTC aun en enero con Chile en febrero" no existe; este caso
    # fija el limite inferior: Chile 2099-02-01 00:30 ya cuenta como 'hoy' = 02-01 y el cargo del 01-31 sigue vigente.
    fake = _fake_chile(monkeypatch, 2099, 2, 1, 0, 30)
    rows = [("c1", "pagado", "2099-01-31", "100"), ("c2", "pagado", "2099-02-01", "200")]
    assert fake.date() == date(2099, 2, 1)
    assert pick_monto_vigente(rows, fallback="50") == Decimal("200")


def test_pick_cargo_con_fecha_igual_a_hoy_se_incluye(monkeypatch) -> None:
    _fake_chile(monkeypatch, 2099, 6, 15, 12, 0)
    rows = [("c1", "pagado", "2099-06-14", "100"), ("c2", "procesando", "2099-06-15", "300"), ("c3", "pagado", "2099-06-16", "999")]
    assert pick_monto_vigente(rows) == Decimal("300")


def test_pick_charge_date_con_timestamp_iso(monkeypatch) -> None:
    _fake_chile(monkeypatch, 2099, 1, 31, 22, 0)
    rows = [("c1", "pagado", "2099-01-30T10:00:00", "100"), ("c2", "pagado", "2099-01-31T23:30:00", "250"),
            ("c3", "pagado", "2099-02-01T00:10:00", "999")]
    assert pick_monto_vigente(rows) == Decimal("250")


def test_pick_today_explicito_gana_sobre_now_chile(monkeypatch) -> None:
    _fake_chile(monkeypatch, 2099, 1, 31, 22, 0)
    rows = [("c1", "pagado", "2099-01-31", "100"), ("c2", "pagado", "2099-02-01", "200")]
    assert pick_monto_vigente(rows, today=date(2099, 2, 1)) == Decimal("200")
    assert pick_monto_vigente(rows, today=date(2099, 1, 30)) is None


def test_load_today_explicito_gana_sobre_now_chile(db_session: Session, monkeypatch) -> None:  # noqa: F811
    _fake_chile(monkeypatch, 2099, 1, 31, 22, 0)
    db_session.add_all([_vp_sub("vtd-1", None), VpCharge(platform=P, external_id="vtd-c1", subscription_external_id="vtd-1",
                                                        status="pagado", charge_date="2099-02-01", amount="200")])
    db_session.flush()
    assert (P, "vtd-1") not in load_monto_vigente(db_session, family="vp", sources=[P])
    assert load_monto_vigente(db_session, family="vp", sources=[P], today=date(2099, 2, 1))[(P, "vtd-1")] == Decimal("200")


def test_paridad_pick_y_load_con_mismo_now_chile(db_session: Session, monkeypatch) -> None:  # noqa: F811
    charges = [
        ("vpp-c1", "pagado", "2099-01-30", "100"),
        ("vpp-c2", "procesando", "2099-01-31T23:30:00", "250"),
        ("vpp-c3", "pagado", "2099-02-01", "999"),
        ("vpp-c4", "rechazado", "2099-01-31", "777"),
    ]
    db_session.add_all([_vp_sub("vpp-1", "50")] + [
        VpCharge(platform=P, external_id=e, subscription_external_id="vpp-1", status=s, charge_date=d, amount=a)
        for e, s, d, a in charges
    ])
    db_session.flush()
    for moment, expected in [((2099, 1, 31, 22, 0), Decimal("250")), ((2099, 1, 30, 22, 0), Decimal("100")),
                             ((2099, 2, 1, 0, 30), Decimal("999")), ((2099, 1, 29, 12, 0), Decimal("50"))]:
        _fake_chile(monkeypatch, *moment)
        pick = pick_monto_vigente(charges, fallback="50")
        load = load_monto_vigente(db_session, family="vp", sources=[P])[(P, "vpp-1")]
        assert pick == load == expected, moment


def test_kpi_mrr_sigue_el_ultimo_cobro_no_el_plan() -> None:
    def kpis(payloads: list[dict]) -> dict:
        records = [SimpleNamespace(resource_type="subscription", payload=p) for p in payloads]
        return staging._vp_extended_data(records)["kpis"]

    plan_only = kpis([{"status": "ACTIVA", "amount": "5000", "suscription_date": _d(-10)}])
    assert plan_only["mrr"] == 5000
    vigente = kpis([{"status": "ACTIVA", "amount": "5000", "monto_vigente": 6200.0, "suscription_date": _d(-10)}])
    assert vigente["mrr"] == 6200
    assert vigente["arpu"] == 6200
    # solo las ACTIVAS suman al MRR; una cancelada con monto_vigente no cambia nada
    mixed = kpis([
        {"status": "ACTIVA", "amount": "5000", "monto_vigente": 6200.0},
        {"status": "CANCELADA", "amount": "5000", "monto_vigente": 9000.0},
    ])
    assert mixed["mrr"] == 6200


def test_etl_consolidacion_usa_monto_vigente_e_idempotente(db_session: Session, monkeypatch) -> None:  # noqa: F811
    db_session.add_all([
        _vp_sub("vce-1", "5000"),
        _vp_charge("vce-c1", "vce-1", "pagado", -20, "5000"),
        _vp_charge("vce-c2", "vce-1", "pagado", -2, "6500"),
        _vp_sub("vce-2", "3000"),  # sin cargos -> conserva el monto de la suscripcion
    ])
    db_session.flush()
    original = cc._vp_records
    monkeypatch.setattr(
        cc, "_vp_records",
        lambda db, model: [r for r in original(db, model) if str(r.external_id).startswith("vce-")],
    )

    cc._consolidate_vp_subscriptions(db_session)
    cc._consolidate_vp_subscriptions(db_session)  # idempotente (ON CONFLICT)

    rows = {s.external_id: s for s in db_session.scalars(select(CSub).where(CSub.source == P, CSub.external_id.like("vce-%")))}
    assert len(rows) == 2
    assert rows["vce-1"].amount == "6500"
    assert rows["vce-2"].amount == "3000"


def test_recuperador_monto_vigente_pagado_o_procesando_hasta_hoy(db_session: Session) -> None:  # noqa: F811
    db_session.add_all([
        CSub(source=P, external_id="vcr-sub", status="activa", amount="5000", suscription_date="2098-01-01"),
        CCharge(source=P, external_id="vcr-p1", subscription_external_id="vcr-sub", status="pagado", charge_date=_d(-60), amount="5000"),
        CCharge(source=P, external_id="vcr-p2", subscription_external_id="vcr-sub", status="procesando", charge_date=_d(-3), amount="6100"),
        CCharge(source=P, external_id="vcr-p3", subscription_external_id="vcr-sub", status="pagado", charge_date=_d(300), amount="9999"),
        CCharge(source=P, external_id="vcr-rej", subscription_external_id="vcr-sub", status="rechazado", charge_date="2099-03-10", amount="100",
                raw_payload={"rejected_object": {"code": "-2"}}),
        # sin cargos cobrados -> monto de la suscripcion
        CSub(source=P, external_id="vcr-sub2", status="activa", amount="4200", suscription_date="2098-01-01"),
        CCharge(source=P, external_id="vcr-rej2", subscription_external_id="vcr-sub2", status="rechazado", charge_date="2099-03-11", amount="50",
                raw_payload={"rejected_object": {"code": "-2"}}),
    ])
    db_session.flush()
    rows = {r["external_id"]: r for r in recovery._rejected_rows(db_session, None, None, "retry")}
    assert rows["vcr-rej"]["monto_vigente"] == 6100.0
    assert rows["vcr-rej"]["monto"] == 100.0
    assert rows["vcr-rej2"]["monto_vigente"] == 4200.0
