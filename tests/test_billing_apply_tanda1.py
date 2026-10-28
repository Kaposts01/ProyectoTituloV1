# ruff: noqa: F811,F401  (fixtures importadas de test_billing_apply)
"""Tanda 1 (revision de la opcion A): defectos de aplicacion y guardianes. SOLO con fakes (ninguna llamada de red).

Cada test se escribio primero contra el codigo anterior (en rojo) y luego se arreglo el defecto.
"""

import asyncio
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from test_billing_apply import (
    CALLS,
    HORIZON,
    NOW,
    STATE,
    SUB,
    FakeVP,
    _api_error,
    _apply,
    _cleanup,
    _deleted,
    _env,
    _events,
    _make_request,
    _managed,
    _mark,
    _names,
    _pending_by_month,
    _route_client,
    _seed_user_sub,
    _setup,
    _status,
    db_session,
)

from app.db.session import engine
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import write_virtualpos as wv

PREVIEW = lambda db, req: asyncio.run(ba.preview_change(db, req, now=NOW))  # noqa: E731


def _paid(cid, d, amount=9900, code=None):
    row = {"id": cid, "charge_date": d, "amount": amount, "status": "pagado"}
    if code:
        row["internal_code"] = code
    return row


# ----------------------------- 3. dia de cobro -----------------------------


def _day_setup(db, paid, **over):
    STATE["charges"] = paid
    return _setup(db, previous_charge_day=None, **over)


def test_dia_31_con_pagados_31ene_y_28feb_calendario_del_31(db_session) -> None:
    _user, req = _day_setup(db_session, [_paid("p1", "2026-01-31"), _paid("p2", "2026-02-28")])
    plan = PREVIEW(db_session, req)
    dates = [a.charge_date for a in plan.create]
    assert dates[:3] == [date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31)]  # ajuste a fin de mes
    assert dates[3] == date(2027, 2, 28)


def test_dia_31_en_febrero_bisiesto(db_session) -> None:
    _user, req = _day_setup(db_session, [_paid("p1", "2026-01-31"), _paid("p2", "2026-02-28")],
                            horizon_start_month="2028-01", horizon_months=3)
    assert [a.charge_date for a in PREVIEW(db_session, req).create] == [
        date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)]


def test_marca_activa_gana_sobre_los_cobros(db_session) -> None:
    STATE["charges"] = [_paid("p1", "2026-01-28"), _paid("p2", "2026-02-28")]
    _user, req = _setup(db_session, previous_charge_day=None, horizon_months=2)
    db_session.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month="2027-10",
                                  last_scheduled_date=date(2027, 10, 20), scheduled_amount=9900, charge_day=20))
    db_session.flush()
    assert {a.charge_date.day for a in PREVIEW(db_session, req).create} == {20}
    db_session.scalar(select(VpCalendarMark)).is_active = False  # marca inactiva: no cuenta
    db_session.flush()
    assert {a.charge_date.day for a in PREVIEW(db_session, req).create} == {28}


def test_previous_charge_day_de_la_solicitud_gana_sobre_la_marca(db_session) -> None:
    STATE["charges"] = [_paid("p1", "2026-02-28")]
    _user, req = _setup(db_session, previous_charge_day=12, horizon_months=2)
    db_session.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month="2027-10",
                                  last_scheduled_date=date(2027, 10, 20), scheduled_amount=9900, charge_day=20))
    db_session.flush()
    assert {a.charge_date.day for a in PREVIEW(db_session, req).create} == {12}


def test_el_dia_no_cuenta_puntuales_ni_reemplazos_de_ventana(db_session) -> None:
    STATE["charges"] = [
        _paid("r1", "2026-06-10"), _paid("r2", "2026-07-10"),
        _paid("o1", "2026-08-25", code=f"{SUB}-T3-20260825-9900"), _paid("o2", "2026-09-25", code=f"{SUB}-20260925-9900-oneoff"),
    ]
    _user, req = _setup(db_session, previous_charge_day=None, horizon_months=2)
    assert {a.charge_date.day for a in PREVIEW(db_session, req).create} == {10}

    # reemplazos de ventana: cobros del CRM cuya fecha es el dia siguiente a su creacion
    STATE["charges"] = [_paid("r1", "2026-06-10"), _paid("r2", "2026-07-10"), _paid("w1", "2026-08-15"), _paid("w2", "2026-09-15")]
    for cid, d, created in (("w1", date(2026, 8, 15), datetime(2026, 8, 14, 15, tzinfo=UTC)),
                            ("w2", date(2026, 9, 15), datetime(2026, 9, 14, 15, tzinfo=UTC))):
        db_session.add(VpManagedCharge(platform="virtualpos1", charge_id=cid, subscription_external_id=SUB,
                                       internal_code=f"c-{cid}", month=d.strftime("%Y-%m"), charge_date=d, amount=9900,
                                       status="creado", created_at=created))
    db_session.flush()
    assert {a.charge_date.day for a in PREVIEW(db_session, req).create} == {10}


# ----------------------------- 2. puntuales (capa de aplicacion) -----------------------------


def test_puntual_del_crm_no_se_cancela_al_cambiar_el_monto(db_session) -> None:
    """Reconocido por la solicitud de origen (request_type='one_off_charge'), aunque su internal_code no tenga el patron."""
    user = _seed_user_sub(db_session)
    origin = BillingChangeRequest(
        request_type="one_off_charge", platform="virtualpos1", subscription_external_id=SUB, requested_by_user_id=user.id,
        status="ejecutada", new_amount=3000, new_charge_date=date(2026, 12, 20), rules_snapshot={}, plan_preview={})
    db_session.add(origin)
    db_session.flush()
    STATE["charges"].append({"id": "one-1", "charge_date": "2026-12-20", "amount": 3000, "status": "pendiente",
                             "internal_code": "codigo-libre"})
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="one-1", subscription_external_id=SUB,
                                   internal_code="codigo-libre", month="2026-12", charge_date=date(2026, 12, 20),
                                   amount=3000, request_id=origin.id, status="creado"))
    db_session.flush()
    req = _make_request(db_session, user)
    assert "one-1" not in {a.charge_id for a in PREVIEW(db_session, req).cancel}
    _apply(db_session, req, user)
    assert "one-1" not in _deleted()
    assert next(c for c in STATE["charges"] if c["id"] == "one-1")["status"] == "pendiente"
    assert len(_pending_by_month()["2026-12"]) == 2  # el regular nuevo + el puntual que convive


# ----------------------------- 4. cobro con fecha de hoy -----------------------------


def test_pendiente_de_hoy_se_conserva_y_la_verificacion_lo_acepta(db_session) -> None:
    STATE["charges"] = [c for c in STATE["charges"] if c["id"] != "paid-0"]
    STATE["charges"].append({"id": "today-1", "charge_date": "2026-10-28", "amount": 9900, "status": "pendiente"})
    _user, req = _setup(db_session, horizon_start_month="2026-10")
    result = _apply(db_session, req, _user)
    assert result.status == "ejecutada"
    assert "today-1" not in _deleted()
    assert next(c for c in STATE["charges"] if c["id"] == "today-1")["status"] == "pendiente"
    assert not [c for c in STATE["charges"] if c["id"].startswith("new-") and c["charge_date"].startswith("2026-10")]


# ----------------------------- 5. E-079 -----------------------------


class E079PaidVP(FakeVP):
    async def delete_charge(self, charge_id):
        if charge_id in STATE.get("e079_paid", set()):
            CALLS.append(("delete_charge", charge_id))
            self._by_id(charge_id)["status"] = "pagado"
            raise _api_error("E-079")
        return await super().delete_charge(charge_id)


def test_e079_sobre_antiguo_ya_pagado_cancela_el_nuevo_del_mes(monkeypatch, db_session) -> None:
    monkeypatch.setattr(wv, "VirtualPOSClient", E079PaidVP)
    STATE["e079_paid"] = {"auto-04"}  # 2027-02
    user, req = _setup(db_session)
    result = _apply(db_session, req, user)
    assert result.status == "ejecutada" and result.covered_late_months == ["2027-02"]
    feb = [c for c in STATE["charges"] if c["charge_date"].startswith("2027-02")]
    assert next(c for c in feb if c["id"] == "auto-04")["status"] == "pagado"
    assert [c["id"] for c in feb if c["status"] == "pendiente"] == []  # no queda 'pagado + pendiente nuevo'
    assert _managed(db_session, req)["new-4"].status == "cancelado"


def test_e079_con_antiguo_aun_pendiente_es_fallo(monkeypatch, db_session) -> None:
    class StillPending(FakeVP):
        async def delete_charge(self, charge_id):
            if charge_id == "auto-04":
                CALLS.append(("delete_charge", charge_id))
                raise _api_error("E-079")  # miente: sigue pendiente
            return await super().delete_charge(charge_id)

    monkeypatch.setattr(wv, "VirtualPOSClient", StillPending)
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    assert _status(db_session, req) == "requiere_conciliacion"


def test_verificacion_detecta_mes_cubierto_con_pendiente_creado_por_la_solicitud(db_session) -> None:
    STATE["e059"] = {"auto-04"}      # el antiguo de feb-2027 queda 'procesando'
    STATE["delete_noop"] = {"new-4"}  # y el DELETE del nuevo 'responde OK' sin cancelar
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError) as ei:
        _apply(db_session, req, user)
    assert "2027-02" in str(ei.value)
    assert _status(db_session, req) == "requiere_conciliacion"


# ----------------------------- 6. listado incompleto / cobros descartados -----------------------------


class RawVP(FakeVP):
    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", status))
        return STATE["raw"]


def _row(i, **over):
    row = {"id": f"x-{i}", "charge_date": "2027-01-05", "amount": 9900, "status": "pendiente"}
    row.update(over)
    return row


@pytest.mark.parametrize("raw", [
    {"charges": [_row(i) for i in range(100)]},                                   # 100 items sin pagination
    {"charges": [_row(i) for i in range(100)], "pagination": {"pages": "3"}},      # pages no entero
    {"charges": [_row(i) for i in range(100)], "pagination": {}},
    {"data": []},                                                                  # forma inesperada
    {"charges": "oops"},
    ["a", "b"],
    None,
    {"charges": [_row(1), "no-dict"], "pagination": {"pages": 1}},                 # item no dict
])
def test_listado_incompleto_o_inesperado_falla_cerrado(monkeypatch, raw) -> None:
    monkeypatch.setattr(wv, "VirtualPOSClient", RawVP)
    STATE["raw"] = raw
    with pytest.raises(ba.ProviderListingError):
        asyncio.run(ba._fetch_charges("virtualpos1", SUB))


def test_listado_corto_sin_pagination_es_una_sola_pagina(monkeypatch) -> None:
    monkeypatch.setattr(wv, "VirtualPOSClient", RawVP)
    STATE["raw"] = {"charges": [_row(i) for i in range(3)]}
    assert len(asyncio.run(ba._fetch_charges("virtualpos1", SUB))) == 3


@pytest.mark.parametrize("field,value", [("amount", "1000.5"), ("charge_date", "2027-13-45"), ("id", None), ("amount", None)])
def test_cobro_no_interpretable_aborta_el_plan_sin_escribir(monkeypatch, db_session, field, value) -> None:
    user, req = _setup(db_session)
    STATE["charges"].append(_row(99, **{field: value}))
    with pytest.raises(ba.UnparseableChargesError) as ei:
        _apply(db_session, req, user)
    msg = str(ei.value)
    assert "1" in msg and "pendiente" in msg and "1000.5" not in msg and "x-99" not in msg  # sin valores ni ids
    assert set(_names()) == {"list_charges"} and _status(db_session, req) == "aprobada"


def test_cobro_cancelado_no_interpretable_se_ignora(db_session) -> None:
    user, req = _setup(db_session)
    STATE["charges"].append(_row(98, amount="n/a", status="cancelado"))
    assert _apply(db_session, req, user).status == "ejecutada"


# ----------------------------- 7. solicitud atascada / cobro sin registro -----------------------------


def test_cancelled_error_tras_el_claim_deja_requiere_conciliacion(monkeypatch, db_session) -> None:
    user, req = _setup(db_session)

    async def boom(ctx, plan):
        raise asyncio.CancelledError

    monkeypatch.setattr(ba, "_create_all", boom)
    with pytest.raises(asyncio.CancelledError):
        _apply(db_session, req, user)
    assert _status(db_session, req) == "requiere_conciliacion"
    assert _events(db_session, req)[-1] == "requiere_conciliacion"
    assert db_session.get(WriteRun, req.write_run_id).status == "reconciliation_required"


def test_fallo_local_entre_post_exitoso_y_registro_se_reconoce_por_internal_code(monkeypatch, db_session) -> None:
    user, req = _setup(db_session)
    real = ba._upsert_managed
    calls = {"n": 0}

    def flaky(ctx, charge_id, action, status="creado"):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("commit local fallido")
        return real(ctx, charge_id, action, status)

    monkeypatch.setattr(ba, "_upsert_managed", flaky)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    assert "new-3" in {c["id"] for c in STATE["charges"]} and "new-3" not in _managed(db_session, req)  # cobro sin registro
    # el planificador lo reconoce como del CRM (por los internal_code de los create_charge de la solicitud)
    inp, _plan, _items = asyncio.run(ba._current_plan(db_session, ba._request_to_input(req, NOW.date()), exclude_own=None))
    assert next(c for c in inp.charges if c.charge_id == "new-3").is_crm
    # y la reaplicacion lo adopta sin duplicar
    monkeypatch.setattr(ba, "_upsert_managed", real)
    req.status = "aprobada"
    db_session.commit()
    assert _apply(db_session, req, user).status == "ejecutada"
    assert STATE["n_create"] == 12
    assert len([m for m in _managed(db_session, req).values() if m.status == "creado"]) == 12


def _stuck(db, req, minutes_ago):
    db.execute(update(BillingChangeRequest).where(BillingChangeRequest.id == req.id)
               .values(status="aplicando", updated_at=datetime.now(UTC) - timedelta(minutes=minutes_ago)))
    db.commit()
    db.refresh(req)


def test_sweep_stuck_applying(db_session) -> None:
    _user, req = _setup(db_session)
    _stuck(db_session, req, 120)
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="m-1", subscription_external_id=SUB, internal_code="c",
                                   month="2026-11", amount=1, request_id=req.id, status="creado"))
    db_session.commit()
    swept = ba.sweep_stuck_applying(db_session, older_than_minutes=30)
    assert swept == [req.id]
    assert _status(db_session, req) == "requiere_conciliacion"
    assert _events(db_session, req)[-1] == "requiere_conciliacion"
    assert db_session.scalar(select(VpManagedCharge.status).where(VpManagedCharge.charge_id == "m-1")) == "requiere_conciliacion"
    assert ba.sweep_stuck_applying(db_session, older_than_minutes=30) == []  # idempotente


def test_sweep_respeta_recientes_y_otros_estados(db_session) -> None:
    _user, req = _setup(db_session)
    _stuck(db_session, req, 5)
    assert ba.sweep_stuck_applying(db_session, older_than_minutes=30) == []
    assert _status(db_session, req) == "aplicando"


def test_sweep_no_toca_una_aplicacion_viva_con_el_lock_tomado(db_session) -> None:
    _user, req = _setup(db_session)
    _stuck(db_session, req, 120)
    with ba.subscription_lock(db_session, "virtualpos1", SUB):
        assert ba.sweep_stuck_applying(db_session, older_than_minutes=30) == []
    assert _status(db_session, req) == "aplicando"


# ----------------------------- 8. guardianes del flujo viejo -----------------------------


def test_delete_plural_bloqueado_con_cobros_vivos_aunque_no_haya_marca(db_session) -> None:
    _user, req = _setup(db_session)
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="m-1", subscription_external_id=SUB, internal_code="c",
                                   month="2026-11", amount=1, request_id=req.id, status="requiere_conciliacion"))
    db_session.commit()
    with pytest.raises(wv.PluralCancelForbiddenError):
        asyncio.run(wv.cancel_future_charges(db_session, SUB))
    assert "delete_plural" not in _names()


def _reassign(db, **kw):
    return asyncio.run(wv.reassign_subscription_amount(db, SUB, 12000, "2026-11-15", dry_run=False, **kw))


def test_reassign_viejo_rechazado_con_marca_activa(db_session) -> None:
    _seed_user_sub(db_session)
    _mark(db_session)
    with pytest.raises(wv.BillingFlowConflictError):
        _reassign(db_session)
    assert not [n for n in _names() if n in ("create_charge", "delete_charge")]


def test_reassign_viejo_rechazado_con_cobros_crm_vivos(db_session) -> None:
    _seed_user_sub(db_session)
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="m-1", subscription_external_id=SUB, internal_code="c",
                                   month="2026-11", amount=1, status="creado"))
    db_session.flush()
    with pytest.raises(wv.BillingFlowConflictError):
        _reassign(db_session)


def test_reassign_viejo_rechazado_con_solicitud_abierta(db_session) -> None:
    _setup(db_session)  # solicitud 'aprobada' abierta
    with pytest.raises(wv.BillingFlowConflictError):
        _reassign(db_session)
    assert not [n for n in _names() if n in ("create_charge", "delete_charge")]


def test_reassign_viejo_toma_el_lock_de_la_suscripcion(db_session) -> None:
    _seed_user_sub(db_session)
    other = engine.connect()
    other.begin()
    from sqlalchemy import text
    other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ba.lock_key("virtualpos1", SUB)})
    try:
        with pytest.raises(ba.SubscriptionBusyError):
            _reassign(db_session)
    finally:
        other.rollback()
        other.close()
    assert not [n for n in _names() if n in ("create_charge", "delete_charge")]


def test_reassign_viejo_sin_conflictos_sigue_funcionando(db_session) -> None:
    _seed_user_sub(db_session)
    res = _reassign(db_session)
    assert res["created_charge_id"]


def test_ruta_reassign_409_con_conflicto_del_flujo_nuevo(monkeypatch, db_session, _cleanup) -> None:
    from app.core.config import settings
    _seed_user_sub(db_session)
    _mark(db_session)
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.create", "virtualpos.charges.cancel"])
    url = f"/api/v1/writes/virtualpos/subscriptions/{SUB}/reassign-amount"
    body = {"new_amount": 12000, "effective_date": "2026-11-15"}
    for dry in ("true", "false"):
        r = client.post(f"{url}?dry_run={dry}", json=body, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 409, r.text
    assert not [n for n in _names() if n in ("create_charge", "delete_charge")]


def test_ruta_reassign_409_con_lock_ocupado(monkeypatch, db_session, _cleanup) -> None:
    from sqlalchemy import text
    _seed_user_sub(db_session)
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.create", "virtualpos.charges.cancel"])
    other = engine.connect()
    other.begin()
    other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ba.lock_key("virtualpos1", SUB)})
    try:
        r = client.post(f"/api/v1/writes/virtualpos/subscriptions/{SUB}/reassign-amount?dry_run=false",
                        json={"new_amount": 12000, "effective_date": "2026-11-15"}, headers={"X-CSRF-Token": csrf})
    finally:
        other.rollback()
        other.close()
    assert r.status_code == 409


# ----------------------------- 9. lock sin comprobacion -----------------------------


def test_lock_roto_antes_de_las_cancelaciones_aborta_la_fase(monkeypatch, db_session) -> None:
    real = ba.subscription_lock

    class BrokenConn:
        def execute(self, *a, **k):
            raise RuntimeError("terminating connection due to idle-in-transaction timeout")

    @contextmanager
    def broken_lock(db, platform, sub):
        with real(db, platform, sub):
            yield BrokenConn()

    monkeypatch.setattr(ba, "subscription_lock", broken_lock)
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    assert _deleted() == []  # no se cancelo nada
    assert STATE["n_create"] == 12  # los creates ya hechos quedan
    assert _status(db_session, req) == "requiere_conciliacion"
    assert {m.status for m in _managed(db_session, req).values()} == {"requiere_conciliacion"}


# ----------------------------- 10. menores -----------------------------


def test_estado_pendiente_se_normaliza_igual_en_todas_partes() -> None:
    class P:
        async def list_charges(self, sid, page=1, limit=100, status=None):
            return {"charges": [{"id": "a", "status": " Pendiente "}, {"id": "b", "status": "pending"},
                                {"id": "c", "status": "pagado"}], "pagination": {"pages": 1}}

    got = asyncio.run(wv._list_pending_charges(P(), SUB))
    assert [c["id"] for c in got] == ["a", "b"]


def test_find_por_internal_code_ignora_cancelados_en_las_4_variantes_y_no_adopta_no_pendientes() -> None:
    class P:
        def __init__(self, status):
            self.status = status

        async def list_charges(self, sid, page=1, limit=100, status=None):
            return {"charges": [{"id": "a", "internal_code": "k", "status": self.status}], "pagination": {"pages": 1}}

    for st in ("cancelado", "cancelada", "cancelled", "canceled", "Cancelled", "pagado", "procesando"):
        assert asyncio.run(wv._find_charge_by_internal_code(P(st), SUB, "k")) is None, st
    for st in ("pendiente", "Pending"):
        assert asyncio.run(wv._find_charge_by_internal_code(P(st), SUB, "k")) is not None, st


def test_huerfano_cancelado_en_variante_inglesa_no_se_adopta_al_fallar_un_create(monkeypatch, db_session) -> None:
    class Cancelled3(FakeVP):
        async def create_charge(self, data):
            STATE["n_create"] += 1
            n = STATE["n_create"]
            CALLS.append(("create_charge", data["internal_code"]))
            if n == 3:
                STATE["charges"].append({"id": "ghost", "charge_date": data["charge_date"], "amount": data["amount"],
                                         "status": "cancelled", "internal_code": data["internal_code"]})
                raise httpx.ReadTimeout("create timeout")
            charge = {"id": f"new-{n}", "charge_date": data["charge_date"], "amount": data["amount"],
                      "status": "pendiente", "internal_code": data["internal_code"]}
            STATE["charges"].append(charge)
            return {**charge, "suscription_id": data["suscription_id"]}

    monkeypatch.setattr(wv, "VirtualPOSClient", Cancelled3)
    user, req = _setup(db_session)
    with pytest.raises(ba.ApplyFailedError):
        _apply(db_session, req, user)
    assert "ghost" not in _managed(db_session, req)
    assert "ghost" not in _deleted()


def test_timeout_de_cancelacion_aplicado_anota_el_writerun_hijo(db_session) -> None:
    STATE["timeout_applied"] = {"auto-03"}
    user, req = _setup(db_session)
    assert _apply(db_session, req, user).status == "ejecutada"
    runs = [r for r in db_session.scalars(select(WriteRun).where(WriteRun.request_id == req.id, WriteRun.operation == "cancel_future_charges"))
            if (r.request_payload or {}).get("charge_ids") == ["auto-03"] and r.status == "failed"]
    assert len(runs) == 1
    assert (runs[0].response_payload or {}).get("applied_after_timeout") is True
