"""Fechas de alta TCH y VirtualPOS (fix/fechas-alta-tch-vp). Datos sinteticos, sin datos personales.

- TCH: la columna «Ingreso» (ANTECEDENTES Y ESTADO MANDATOS) se carga en `fecha_ingreso` y es el ultimo respaldo de
  la fecha de alta; las bajas anteriores al alta se marcan (no se corrigen).
- VirtualPOS: sin `suscription_date`, la fecha de alta es la del primer cobro (estimada).
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import tch
from app.db.session import engine
from app.models.crm import Subscription
from app.models.tch import TchSubscription
from app.models.vp import VpCharge
from app.services.dashboard_general import _subscription_histograms
from scripts import etl_tch
from tests.tch_synthetic import write_report

INGRESO = ("ANTECEDENTES Y ESTADO MANDATOS", "Ingreso")


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class _NoClose:  # la ruta cierra su sesion al terminar: aqui se comparte la de la prueba
        def __getattr__(self, name):
            return getattr(session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(tch, "_get_db", lambda: _NoClose())
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


# ── ETL: mapeo de «Ingreso» ──────────────────────────────────────────────────────────────────────────────


def _row(extra: dict) -> dict:
    frame = pd.DataFrame({
        ("Ficha DUES", "Ficha DUES"): [101],
        ("SOCIO", "Rut"): ["12345678-9"],
        ("MANDATO ACTUAL", "Monto Vigente"): [10000],
        **{key: [value] for key, value in extra.items()},
    })
    return etl_tch._transform_subscriptions(frame, "VIGENTE")[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (pd.Timestamp("2019-03-05"), "2019-03-05"),
        (datetime(2019, 3, 5, 14, 30), "2019-03-05"),  # noqa: DTZ001 - celda de Excel: fecha sin zona
        (date(2019, 3, 5), "2019-03-05"),
        ("05/03/2019", "2019-03-05"),
        ("5/3/2019", "2019-03-05"),
        ("05-03-2019", "2019-03-05"),
        ("05.03.2019", "2019-03-05"),
        ("2019-03-05", "2019-03-05"),
        ("2019-03-05 00:00:00", "2019-03-05"),
        (" 05/03/2019 ", "2019-03-05"),
        ("31/02/2019", None),  # fecha imposible: no se guarda un ISO invalido
        ("sin dato", None),
        ("", None),
        (None, None),
    ],
)
def test_ingreso_is_mapped_to_fecha_ingreso_in_any_excel_format(value, expected) -> None:
    assert _row({INGRESO: value})["fecha_ingreso"] == expected


def test_ingreso_matches_the_exact_label_not_a_partial_one() -> None:
    row = _row({("APORTES ACUMULADOS", "Ingreso Total"): "01/01/2020", INGRESO: "02/02/2021"})
    assert row["fecha_ingreso"] == "2021-02-02"
    assert _row({("APORTES ACUMULADOS", "Ingreso Total"): "01/01/2020"})["fecha_ingreso"] is None


def test_report_without_ingreso_column_leaves_it_empty() -> None:
    assert _row({})["fecha_ingreso"] is None


def test_fecha_ingreso_reaches_the_database_and_a_later_report_without_it_keeps_it(db_session, tmp_path) -> None:
    first = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[{"ficha": 948001, "rut": "12345678-9", "extra": {INGRESO: datetime(2018, 7, 9)}}],  # noqa: DTZ001
        eliminados=[{"ficha": 948002, "rut": "11111111-1", "extra": {INGRESO: "15/01/2017"}}],
        extra_headers=[INGRESO],
    )
    etl_tch._process_file(first, db_session)
    dates = dict(db_session.execute(
        select(TchSubscription.file_number, TchSubscription.entry_date)
        .where(TchSubscription.file_number.in_((948001, 948002)))
    ).all())
    assert dates == {948001: "2018-07-09", 948002: "2017-01-15"}

    second = write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        active=[{"ficha": 948001, "rut": "12345678-9", "monto": 12000}],
        eliminados=[{"ficha": 948002, "rut": "11111111-1"}],
    )
    etl_tch._process_file(second, db_session)
    db_session.expire_all()
    sub = db_session.scalars(select(TchSubscription).where(TchSubscription.file_number == 948001)).one()
    assert sub.entry_date == "2018-07-09" and sub.amount == "12000"


# ── TCH: cadena de respaldo de la fecha de alta ──────────────────────────────────────────────────────────


def _sub(file_number: int, status: str = "VIGENTE", **dates) -> TchSubscription:
    return TchSubscription(file_number=file_number, status=status, peso_equivalent="10000", **dates)


def test_ingreso_is_the_last_fallback_and_never_moves_a_dated_activation(db_session) -> None:
    db_session.add_all([
        _sub(948101, activation_date="2025-03-10", entry_date="2024-12-01"),  # manda la activacion
        _sub(948102, first_charge_date="2025-09-05", entry_date="2025-06-01"),  # manda el primer cobro
        _sub(948103, bank_delivery_date="2025-10-01", entry_date="2025-07-01"),  # manda la entrega al banco
        _sub(948104, entry_date="2025-05-20"),  # solo ingreso: ahora es alta
        _sub(948105, entry_date="no-es-fecha"),  # sin fecha valida: no es alta
    ])
    db_session.flush()

    summary = tch.tch_summary()

    altas = {(e["year"], e["month"]): e["count"] for e in summary["activaciones_mensuales"]}
    assert altas[(2025, 3)] == 1 and altas[(2025, 9)] == 1 and altas[(2025, 10)] == 1 and altas[(2025, 5)] == 1
    assert (2024, 12) not in altas and (2025, 6) not in altas and (2025, 7) not in altas
    fuente = summary["activaciones_fuente"]
    assert (
        fuente["fecha_activacion"], fuente["fecha_primer_cobro"], fuente["fecha_entrega_banco"], fuente["fecha_ingreso"],
        fuente["sin_fecha"],
    ) == (1, 1, 1, 1, 1)
    assert "ingreso del mandato" in fuente["nota"]


def test_serialized_subscription_exposes_effective_date_and_flags_cancellation_before_signup() -> None:
    inconsistent = _sub(1, "ELIMINADA", entry_date="2024-05-01", deletion_date="2024-03-31")
    consistent = _sub(2, "ELIMINADA", activation_date="2024-01-10", entry_date="2023-12-01", deletion_date="2024-03-31")
    undated = _sub(3, "ELIMINADA", deletion_date="2024-03-31")

    first = tch._serialize_subscription(inconsistent)
    assert (first["fecha_ingreso"], first["fecha_alta_efectiva"], first["baja_antes_del_alta"]) == (
        "2024-05-01", "2024-05-01", True,
    )
    second = tch._serialize_subscription(consistent)
    assert (second["fecha_alta_efectiva"], second["baja_antes_del_alta"]) == ("2024-01-10", False)
    third = tch._serialize_subscription(undated)
    assert (third["fecha_alta_efectiva"], third["baja_antes_del_alta"]) == (None, False)
    # Se marca, no se corrige: las fechas de la ficha no cambian.
    assert (inconsistent.deletion_date, inconsistent.entry_date) == ("2024-03-31", "2024-05-01")


# ── Alerta de calidad del dashboard general ──────────────────────────────────────────────────────────────


def _quality(db: Session, channels: list[str]) -> dict[str, int]:
    return _subscription_histograms(db, channels)[2]


def test_tch_alert_counts_fewer_undated_signups_once_ingreso_is_loaded(db_session) -> None:
    before = _quality(db_session, ["tch"])
    undated = _sub(948201, "VIGENTE")
    cancelled_undated = _sub(948202, "ELIMINADA", deletion_date="2025-08-31")
    db_session.add_all([undated, cancelled_undated])
    db_session.flush()
    without_ingreso = _quality(db_session, ["tch"])
    assert without_ingreso["altas_sin_fecha"] - before["altas_sin_fecha"] == 2
    assert without_ingreso["bajas_sin_fecha"] - before["bajas_sin_fecha"] == 1

    undated.entry_date = "2025-02-01"
    cancelled_undated.entry_date = "2025-01-15"
    db_session.flush()
    with_ingreso = _quality(db_session, ["tch"])
    assert with_ingreso["altas_sin_fecha"] == before["altas_sin_fecha"]
    assert with_ingreso["bajas_sin_fecha"] == before["bajas_sin_fecha"]


def test_tch_cancellation_before_signup_is_flagged_for_review(db_session) -> None:
    before = _quality(db_session, ["tch"])
    db_session.add(_sub(948301, "ELIMINADA", entry_date="2025-06-01", deletion_date="2025-04-30"))
    db_session.flush()
    after = _quality(db_session, ["tch"])
    assert after["bajas_antes_del_alta"] - before["bajas_antes_del_alta"] == 1
    assert after["bajas_sin_fecha"] - before["bajas_sin_fecha"] == 1  # sigue sin poder ubicarse en un mes


def _vp_sub(ext: str, signup: str | None, status: str = "ACTIVA") -> Subscription:
    return Subscription(source="virtualpos1", external_id=ext, status=status, suscription_date=signup, raw_payload={})


def _vp_charge(ext: str, subscription: str, day: date) -> VpCharge:
    return VpCharge(platform="virtualpos1", external_id=ext, subscription_external_id=subscription, charge_date=day)


def test_vp_signup_falls_back_to_first_charge_and_is_counted_as_estimated(db_session) -> None:
    before_signups, _, before = _subscription_histograms(db_session, ["virtualpos"])
    db_session.add_all([
        _vp_sub("fx-vp-1", None),  # payload sin fecha, con cobros: alta estimada = primer cobro
        _vp_charge("fx-vp-c1", "fx-vp-1", date(2026, 3, 5)),
        _vp_charge("fx-vp-c2", "fx-vp-1", date(2026, 2, 5)),
        _vp_charge("fx-vp-c3", "fx-vp-1", date(2026, 4, 5)),
        _vp_sub("fx-vp-2", "2026-01-10"),  # fecha del payload: manda aunque haya un cobro anterior
        _vp_charge("fx-vp-c4", "fx-vp-2", date(2025, 12, 20)),
        _vp_sub("fx-vp-3", None),  # sin fecha y sin cobros: sigue en la alerta
    ])
    db_session.flush()

    signups, _, after = _subscription_histograms(db_session, ["virtualpos"])
    added = {m: signups["virtualpos"][m] - before_signups["virtualpos"].get(m, 0) for m in signups["virtualpos"]}
    assert added.get("2026-02") == 1 and added.get("2026-01") == 1
    assert not added.get("2026-03") and not added.get("2025-12")
    assert after["altas_fecha_estimada"] - before["altas_fecha_estimada"] == 1
    assert after["altas_sin_fecha"] - before["altas_sin_fecha"] == 1  # solo la que no tiene cobros


def test_vp_first_charge_fallback_does_not_apply_to_other_channels(db_session) -> None:
    before = _quality(db_session, ["toku"])
    db_session.add_all([
        Subscription(source="toku", external_id="fx-vp-1", status="ACTIVE", suscription_date=None, raw_payload={}),
        _vp_charge("fx-vp-c9", "fx-vp-1", date(2026, 2, 5)),  # mismo id externo, otra plataforma: no cuenta
    ])
    db_session.flush()
    after = _quality(db_session, ["toku"])
    assert after["altas_sin_fecha"] - before["altas_sin_fecha"] == 1
    assert after["altas_fecha_estimada"] == before["altas_fecha_estimada"]
