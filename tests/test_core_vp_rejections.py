"""RJ-05: enriquecimiento de rechazos de VirtualPOS en core (forma de payload y UPDATE explícito).

Los payloads son sintéticos: `rejected_object` viene en el nivel superior de `GET /v3/payment/{uuid}`
(hermano de `payment`), no dentro de `order`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment
from app.models.vp import VpPayment
from app.services.core_vp_etl import (
    _enrich_charges_with_rejections,
    _enrich_payments_with_rejections,
    _extract_rejection,
)
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)


def _uid() -> str:
    return "rj05-" + uuid.uuid4().hex[:10]


def _detail(code_key: str = "code", code: str = "-3", message: str = "Excede monto") -> dict:
    """Forma del detalle de pago: rejected_object en el nivel superior, hermano de `payment`."""
    return {
        "status": "OK",
        "payment": {"order": {"uuid": "x", "status": "rechazado"}},
        "rejected_object": {code_key: code, "message": message},
    }


def _scenario(db: Session, payload: dict, *, link: bool = True, pay_date: str = "2026-10-01"):
    charge_ext, pay_ext = _uid(), _uid()
    db.add(VpPayment(external_id=pay_ext, platform="virtualpos1", status="rechazado", payment_date=pay_date,
                     charge_external_id=charge_ext if link else None, raw_payload=payload))
    charge = CoreCharge(source="virtualpos1", external_id=charge_ext)
    payment = CorePayment(source="virtualpos1", external_id=pay_ext, source_status="rechazado")
    db.add_all([charge, payment])
    db.flush()
    return charge, payment, charge_ext, pay_ext


def _reload(db: Session, obj):
    db.expire(obj)
    return obj


def test_extract_rejection_reads_top_level_code_error_code_and_legacy_nested() -> None:
    assert _extract_rejection(_detail()) == ("-3", "Excede monto")
    assert _extract_rejection(_detail("error_code", "-2122", "VIOLACION")) == ("-2122", "VIOLACION")
    nested = {"payment": {"order": {"rejected_object": {"code": "-8", "message": "Tarjeta expirada"}}}}
    assert _extract_rejection(nested) == ("-8", "Tarjeta expirada")
    assert _extract_rejection({"order": {"rejected_object": {"code": "-6"}}}) == ("-6", None)


def test_extract_rejection_ignores_success_empty_and_missing() -> None:
    assert _extract_rejection(_detail(code="0", message="Operación exitosa")) is None
    assert _extract_rejection({"rejected_object": {}}) is None
    assert _extract_rejection({"rejected_object": {"message": "sin codigo"}}) is None
    assert _extract_rejection({"payment": {"order": {}}}) is None
    assert _extract_rejection(None) is None
    assert _extract_rejection({"rejected_object": "texto"}) is None


def test_charge_is_updated_with_explicit_update_from_top_level_rejected_object(db_session: Session) -> None:  # noqa: F811
    charge, payment, *_ = _scenario(db_session, _detail())
    assert _enrich_charges_with_rejections(db_session) >= 1
    _reload(db_session, charge)
    assert charge.latest_rejection_code == "-3"
    assert charge.latest_rejection_reason == "Excede monto"
    assert charge.latest_rejection_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert charge.latest_rejection_payment_id == payment.id


def test_charge_with_error_code_key_and_legacy_nested_shape(db_session: Session) -> None:  # noqa: F811
    c1, *_ = _scenario(db_session, _detail("error_code", "-2122", "VIOLACION DE SEGURIDAD"))
    c2, *_ = _scenario(db_session, {"payment": {"order": {"rejected_object": {"code": "-8", "message": "Exp"}}}})
    _enrich_charges_with_rejections(db_session)
    assert _reload(db_session, c1).latest_rejection_code == "-2122"
    assert _reload(db_session, c2).latest_rejection_code == "-8"


def test_success_rejected_object_does_not_mark_the_charge(db_session: Session) -> None:  # noqa: F811
    charge, *_ = _scenario(db_session, _detail(code="0", message="Operación exitosa"))
    _enrich_charges_with_rejections(db_session)
    assert _reload(db_session, charge).latest_rejection_code is None


def test_null_charge_link_changes_nothing_but_explicit_links_are_accepted(db_session: Session) -> None:  # noqa: F811
    charge, payment, charge_ext, pay_ext = _scenario(db_session, _detail(), link=False)
    _enrich_charges_with_rejections(db_session)
    assert _reload(db_session, charge).latest_rejection_code is None  # sin vínculo no se inventa nada

    # RJ-06 / RJ-04 entregarán el vínculo pago -> cobro por esta vía.
    _enrich_charges_with_rejections(db_session, payment_charge_links={("virtualpos1", pay_ext): charge_ext})
    _reload(db_session, charge)
    assert charge.latest_rejection_code == "-3"
    assert charge.latest_rejection_payment_id == payment.id


def test_idempotent_and_never_replaces_a_newer_rejection_with_an_older_one(db_session: Session) -> None:  # noqa: F811
    charge, _payment, charge_ext, _pay_ext = _scenario(db_session, _detail(code="-3"), pay_date="2026-10-05")
    first = _enrich_charges_with_rejections(db_session)
    assert first >= 1
    assert _enrich_charges_with_rejections(db_session) == 0  # segunda corrida: nada cambia

    db_session.add(VpPayment(external_id=_uid(), platform="virtualpos1", status="rechazado", payment_date="2026-09-01",
                             charge_external_id=charge_ext, raw_payload=_detail(code="-6", message="Viejo")))
    db_session.flush()
    _enrich_charges_with_rejections(db_session)
    _reload(db_session, charge)
    assert charge.latest_rejection_code == "-3"  # el más reciente se conserva

    db_session.add(VpPayment(external_id=_uid(), platform="virtualpos1", status="rechazado", payment_date="2026-10-20",
                             charge_external_id=charge_ext, raw_payload=_detail(code="-10", message="Nuevo")))
    db_session.flush()
    _enrich_charges_with_rejections(db_session)
    assert _reload(db_session, charge).latest_rejection_code == "-10"


def test_payments_get_rejection_fields_without_needing_a_charge_link(db_session: Session) -> None:  # noqa: F811
    _charge, payment, *_ = _scenario(db_session, _detail("code", "-7", "Tarjeta bloqueada"), link=False)
    assert _enrich_payments_with_rejections(db_session) >= 1
    _reload(db_session, payment)
    assert payment.rejection_code == "-7"
    assert payment.rejection_reason == "Tarjeta bloqueada"
    assert payment.rejection_reported_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert _enrich_payments_with_rejections(db_session) == 0  # idempotente
    row = db_session.scalar(select(CorePayment).where(CorePayment.id == payment.id))
    assert row is not None and row.rejection_code == "-7"
