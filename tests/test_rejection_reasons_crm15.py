"""CRM-15A/15C: motivos de rechazo que salian vacios o «No informado».

* 15A (VirtualPOS): el recuperador toma la glosa del reporte PAT (`vp_report_payments`) aunque el ETL Core no la haya
  proyectado a `core_charges`, y el PAT manda sobre la glosa de la API.
* 15C (Payku): `gateway_response.message` (codigo `-N`) se mapea a `core_payments.rejection_code` cuando el payload lo
  trae; la vista de rechazos ya no muestra $0 ni periodo vacio.

Datos sinteticos (sin PII, sin llamadas a proveedores); cada test corre en una transaccion que se revierte.
"""

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import recovery
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.vp_report import VpReportFile, VpReportPayment
from app.services import core_payku_etl, recovery_payku
from app.services.payku_rejection_codes import payku_gateway_rejection
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

NOW = datetime(2095, 6, 1, tzinfo=UTC)


# ----------------------------------------------------------------------------- 15C: forma del gateway_response


@pytest.mark.parametrize(
    ("gateway", "expected"),
    [
        ({"status": "rejected", "message": "-11 "}, ("-11", None)),
        ({"status": "rejected", "message": " -3"}, ("-3", None)),
        ({"status": "rejected", "message": "Rubro no autorizado."}, (None, "Rubro no autorizado.")),
        ({"status": "success", "message": "successful transaction"}, (None, None)),
        ({"status": "rejected", "message": "  "}, (None, None)),
        ({"status": "rejected"}, (None, None)),
        (None, (None, None)),
        ("-11", (None, None)),
    ],
)
def test_payku_gateway_rejection_shapes(gateway, expected) -> None:
    assert payku_gateway_rejection(gateway) == expected


def _payku_sub(db: Session, tag: str, amount: int | None = 5000) -> CoreSubscription:
    ext = f"pk-sub-{tag}"
    db.add(PaykuSubscription(external_id=ext, status="suspended", status_normalized="suspended"))
    sub = CoreSubscription(source="payku", external_id=ext, status="suspended", amount=amount, currency="CLP")
    db.add(sub)
    db.flush()
    return sub


def test_payku_etl_maps_gateway_code_and_never_clears_it(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    sub = _payku_sub(db_session, tag)
    tx_new, tx_old, tx_plain = f"tx-new-{tag}", f"tx-old-{tag}", f"tx-plain-{tag}"
    gateway = {"status": "rejected", "message": "-11 "}
    for ext, payload in ((tx_new, {"gateway_response": gateway}), (tx_old, {"gateway_response": gateway}),
                         (tx_plain, {"amount": 0, "status": "rejected"})):
        db_session.add(PaykuTransaction(external_id=ext, subscription_id=sub.external_id, status="rejected",
                                        amount="0", created_at_api="2095-02-10 10:00:00", raw_payload=payload))
    # pago ya cargado antes de que existiera el dato (el insert del ETL es on_conflict_do_nothing)
    db_session.add(CorePayment(source="payku", external_id=tx_old, subscription_id=sub.id, source_status="rejected"))
    # pago con motivo ya guardado y sin gateway en el payload: no se toca
    db_session.add(CorePayment(source="payku", external_id=tx_plain, subscription_id=sub.id, source_status="rejected",
                               rejection_reason="maximum attempt limit"))
    db_session.flush()

    core_payku_etl._materialize_payments(db_session)
    db_session.flush()
    db_session.expire_all()

    got = {p.external_id: (p.rejection_code, p.rejection_reason) for p in db_session.scalars(
        select(CorePayment).where(CorePayment.external_id.in_([tx_new, tx_old, tx_plain])))}
    assert got[tx_new] == ("-11", None)
    assert got[tx_old] == ("-11", None)
    assert got[tx_plain] == (None, "maximum attempt limit")

    # idempotente: una segunda corrida no cambia nada
    assert core_payku_etl._refresh_payment_rejections(db_session, {tx_old: ("-11", None)}) == 0
    # un dato nulo nunca borra el codigo ya guardado
    assert core_payku_etl._refresh_payment_rejections(db_session, {tx_old: (None, None)}) == 0


# ----------------------------------------------------------------------------- 15C: vista de rechazos de Payku


def test_payku_rejected_view_fills_amount_and_period(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    sub = _payku_sub(db_session, tag, amount=7000)
    rows = [
        # monto 0 (como lo entrega Payku) y sin ciclo: monto de la suscripcion y mes del intento EN CHILE
        (f"z-{tag}", Decimal("0"), datetime(2095, 3, 1, 2, 0, tzinfo=UTC), None),
        # monto real del intento
        (f"r-{tag}", Decimal("6500"), datetime(2095, 4, 15, 12, 0, tzinfo=UTC), "-11"),
    ]
    for ext, amount, when, code in rows:
        db_session.add(PaykuTransaction(external_id=ext, subscription_id=sub.external_id, status="rejected",
                                        status_normalized="rejected"))
        db_session.add(CorePayment(source="payku", external_id=ext, subscription_id=sub.id, source_status="rejected",
                                   occurred_at=when, amount=amount, currency="CLP", rejection_code=code))
    db_session.flush()

    result = recovery_payku.rejected(db_session, date(2095, 1, 1), date(2095, 12, 31), 0, 50)
    mine = {r["charge_id"]: r for r in result["items"] if r["charge_id"].endswith(tag)}
    zero, real = mine[f"z-{tag}"], mine[f"r-{tag}"]
    assert (zero["amount"], zero["amount_source"]) == (7000.0, "subscription")
    assert (zero["period"], zero["period_source"]) == ("2095-02", "attempt")  # 02:00 UTC del 1/3 es 28/2 en Chile
    assert zero["rejection_reason"] == "No informado por Payku"
    assert (real["amount"], real["amount_source"]) == (6500.0, "transaction")
    assert real["period"] == "2095-04" and real["rejection_code"] == "-11"
    assert real["rejection_reason"] == "-11"  # Payku no documenta la glosa del codigo: se muestra tal cual (d120)


def test_payku_rejected_view_without_any_amount_is_empty_not_zero(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    sub = _payku_sub(db_session, tag, amount=None)
    db_session.add(PaykuTransaction(external_id=f"n-{tag}", subscription_id=sub.external_id, status="rejected",
                                    status_normalized="rejected"))
    db_session.add(CorePayment(source="payku", external_id=f"n-{tag}", subscription_id=sub.id, source_status="rejected",
                               occurred_at=datetime(2095, 5, 5, tzinfo=UTC), amount=0, currency="CLP"))
    db_session.flush()
    result = recovery_payku.rejected(db_session, date(2095, 1, 1), date(2095, 12, 31), 0, 50)
    row = next(r for r in result["items"] if r["charge_id"] == f"n-{tag}")
    assert row["amount"] is None and row["amount_source"] is None


# ----------------------------------------------------------------------------- 15A: glosa del PAT en el recuperador VP


def _pat(db: Session, tag: str, charge: str, code: str, text: str, *, platform_status: str = "resolved",
         status: str = "rechazado") -> None:
    f = VpReportFile(report_type="transacciones", file_sha256=hashlib.sha256(f"{tag}{charge}".encode()).hexdigest(),
                     filename=f"TransaccionesPAT-{tag}.csv", status="completed")
    db.add(f)
    db.flush()
    db.add(VpReportPayment(charge_external_id=charge, platform="virtualpos1" if platform_status == "resolved" else None,
                           platform_status=platform_status, charge_status=status, response_code=code,
                           response_text=text, scheduled_date=date(2095, 3, 5), source_generated_at=NOW,
                           last_file_id=f.id))


def test_vp_recovery_reads_pat_glosa_without_core_etl(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    only_pat, both, unresolved = f"pat-{tag}", f"both-{tag}", f"unres-{tag}"
    _pat(db_session, tag, only_pat, "-11", "Excede límite de reintentos de rechazo")
    _pat(db_session, tag, both, "-3", "Excede monto máximo")
    _pat(db_session, tag, unresolved, "-6", "Rechazo general", platform_status="unresolved")
    db_session.add(CoreCharge(source="virtualpos1", external_id=both, latest_rejection_code="-10",
                              latest_rejection_reason="Glosa de la API", latest_rejection_at=NOW))
    db_session.flush()

    found = recovery._core_rejections(db_session)

    pat = found[("virtualpos1", only_pat)]
    assert (pat.latest_rejection_code, pat.latest_rejection_reason) == ("-11", "Excede límite de reintentos de rechazo")
    assert pat.latest_rejection_at.date() == date(2095, 3, 5)
    # el PAT manda sobre la glosa de la API (D4/D5); la fecha del ultimo rechazo se conserva
    mixed = found[("virtualpos1", both)]
    assert (mixed.latest_rejection_code, mixed.latest_rejection_reason) == ("-3", "Excede monto máximo")
    assert mixed.latest_rejection_at == NOW
    # sin cuenta resuelta no se usa
    assert not any(key[1] == unresolved for key in found)


def test_vp_recovery_rejection_fields_use_pat_text(db_session: Session) -> None:  # noqa: F811
    from app.models.crm import Charge

    tag = uuid.uuid4().hex[:8]
    _pat(db_session, tag, f"c-{tag}", "-2119", "Excede saldo maximo")
    db_session.flush()
    core = recovery._core_rejections(db_session)[("virtualpos1", f"c-{tag}")]
    charge = Charge(source="virtualpos1", external_id=f"c-{tag}", charge_date="2095-03-05", status="rechazado")
    fields = recovery._rejection_fields(charge, core)
    assert fields["rejection_code"] == "-2119"
    assert fields["rejection_reason"] == "Excede saldo maximo"  # codigo sin catalogo: glosa del reporte (d120)
    assert fields["rejection_at"] == "2095-03-05"
