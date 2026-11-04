"""RJ-06: captura diaria de la glosa de rechazo de VirtualPOS (`GET /v3/suscription/{id}/charges?status=rechazado`).

Todo con un FakeVP sintetico y payloads con la forma medida en produccion el 2026-10-29 (sin datos personales):
cada cobro rechazado trae `rejected_object {code,message,doc_url}` y `payment.order.uuid`; `order.amount` es
str en los cobros; el `message` puede traer acentos.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment
from app.models.rejection import PaymentRejectionDetail
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent
from app.models.vp import VpCharge, VpPayment
from app.services import status_events
from app.services.core_vp_etl import (
    _enrich_charges_with_rejections,
    _enrich_payments_with_rejections,
)
from app.services.vp_rejection_capture import (
    capture_vp_rejections,
    fix_text,
    link_payments_to_charges,
    normalize_amount,
    parse_rejected_charge,
)
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

PLATFORM = "virtualpos1"


def _uid(prefix: str = "rj06") -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:10]


def _item(charge_id: str, payment_uuid: str | None, *, code: str | None = "-3", message: str = "Excede monto máximo",
          amount: int = 5000, order_amount: str | int = "5000", charge_date: str = "2026-10-05") -> dict:
    """Cobro rechazado con la forma medida de `/suscription/{id}/charges?status=rechazado`."""
    item: dict = {
        "id": charge_id, "charge_date": charge_date, "amount": amount, "status": "rechazado",
        "description": "Cuota", "created_at": "2026-09-01 10:00:00", "internal_code": None,
    }
    if payment_uuid:
        item["payment"] = {
            "commerce": {"commerce_id": "c1", "name": "Comercio"},
            "order": {
                "uuid": payment_uuid, "status": "rechazado", "created_at": "2026-10-05 08:30:00",
                "authorized_at": None, "auth_code": None, "payment_type_code": None,
                "amount": order_amount, "deposits": [],
            },
        }
    if code is not None:
        item["rejected_object"] = {
            "code": code, "message": message, "doc_url": "https://virtualpos.readme.io/reference/objeto-rechazo",
        }
    return item


class FakeVP:
    """Cliente falso: `plan[sub]` es una lista de respuestas (items) o una lista de excepciones/respuestas por llamada."""

    def __init__(self, plan: dict[str, object]) -> None:
        self.plan = plan
        self.calls: list[tuple[str, int, str | None]] = []

    async def list_charges(self, subscription_id: str, page: int = 1, limit: int = 100, status: str | None = None):
        self.calls.append((subscription_id, page, status))
        planned = self.plan.get(subscription_id, [])
        if isinstance(planned, list) and planned and isinstance(planned[0], Exception):
            queue = [p for p in planned]
            outcome = queue[min(len([c for c in self.calls if c[0] == subscription_id]) - 1, len(queue) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            planned = outcome
        if isinstance(planned, Exception):
            raise planned
        return {"status": "OK", "code": 200, "suscription_id": subscription_id, "charges": planned,
                "pagination": {"limit": limit, "page": page, "pages": 1, "total": len(planned)}}


def _http_error(status: int, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://vp.invalid/v3/suscription/x/charges")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request, headers=headers))


async def _no_sleep(_seconds: float) -> None:
    return None


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _run(db: Session, client: FakeVP, **kw) -> dict:
    kw.setdefault("pause_seconds", 0.0)
    kw.setdefault("sleep", _no_sleep)
    return asyncio.run(capture_vp_rejections(db, PLATFORM, client, **kw))


def _seed_rejected(db: Session, sub: str, charge_ids: list[str], *, status: str = "RECHAZADO",
                   charge_date: str = "2026-10-05") -> None:
    for cid in charge_ids:
        db.add(VpCharge(external_id=cid, platform=PLATFORM, subscription_external_id=sub, status=status,
                        charge_date=charge_date, amount="5000"))
    db.flush()


def _details(db: Session, charge_id: str) -> list[PaymentRejectionDetail]:
    return list(db.scalars(select(PaymentRejectionDetail).where(
        PaymentRejectionDetail.source == PLATFORM, PaymentRejectionDetail.charge_external_id == charge_id)))


# -- piezas puras -------------------------------------------------------------------------------------------------

def test_normalize_amount_accepts_str_and_int_and_rejects_garbage() -> None:
    assert normalize_amount("5000") == Decimal("5000.00")
    assert normalize_amount(5000) == Decimal("5000.00")
    assert normalize_amount(" 1250.5 ") == Decimal("1250.50")
    assert normalize_amount("1.234,5") is None  # formato local no soportado: mejor sin dato que un monto errado
    assert normalize_amount(None) is None and normalize_amount("") is None and normalize_amount("abc") is None
    assert normalize_amount(True) is None


def test_fix_text_repairs_utf8_read_as_latin1_and_keeps_good_text() -> None:
    assert fix_text("Excede lÃ­mite de reintentos") == "Excede límite de reintentos"
    assert fix_text("OperaciÃ³n rechazada") == "Operación rechazada"
    assert fix_text("Excede monto máximo") == "Excede monto máximo"
    assert fix_text("Ñandú") == "Ñandú"
    assert fix_text(None) is None


def test_fix_text_strips_control_chars_and_card_like_digit_runs() -> None:
    assert fix_text("Rechazo\x00 con 4111111111111111 fin") == "Rechazo con [redacted] fin"


def test_parse_rejected_charge_reads_the_measured_shape() -> None:
    parsed = parse_rejected_charge(_item("ch1", "pay1", code="-3", message="Excede monto máximo"))
    assert parsed is not None
    assert parsed["charge_external_id"] == "ch1" and parsed["payment_external_id"] == "pay1"
    assert parsed["code"] == "-3" and parsed["reason"] == "Excede monto máximo"
    assert parsed["amount"] == Decimal("5000.00")  # order.amount llega como str
    assert parsed["doc_url"].endswith("objeto-rechazo")
    assert parsed["rejected_at"] == datetime(2026, 10, 5, 8, 30, tzinfo=UTC)
    assert parsed["acquirer_code"] is None


def test_parse_rejected_charge_int_amount_and_acquirer_code() -> None:
    parsed = parse_rejected_charge(_item("ch1", "pay1", code="-2122", order_amount=7000))
    assert parsed is not None
    assert parsed["amount"] == Decimal("7000.00") and parsed["acquirer_code"] == "-2122"


def test_parse_rejected_charge_without_payment_or_object() -> None:
    no_payment = parse_rejected_charge(_item("ch1", None))
    assert no_payment is not None and no_payment["payment_external_id"] is None and no_payment["code"] == "-3"
    assert no_payment["rejected_at"] == datetime(2026, 10, 5, tzinfo=UTC)  # cae a charge_date
    no_object = parse_rejected_charge(_item("ch2", "pay2", code=None))
    assert no_object is not None and no_object["code"] == "" and no_object["reason"] is None
    ok_code = parse_rejected_charge(_item("ch3", "pay3", code="0", message="Operación exitosa"))
    assert ok_code is not None and ok_code["code"] == ""  # el codigo 0 no es un rechazo
    assert parse_rejected_charge({"status": "rechazado"}) is None  # sin id de cobro
    assert parse_rejected_charge(_item("ch4", "pay4") | {"status": "pagado"}) is None  # el filtro no se respeto
    assert parse_rejected_charge("texto") is None  # type: ignore[arg-type]


def test_parse_accepts_error_code_key() -> None:
    item = _item("ch1", "pay1", code=None)
    item["rejected_object"] = {"error_code": "-8", "message": "Tarjeta expirada"}
    parsed = parse_rejected_charge(item)
    assert parsed is not None and parsed["code"] == "-8"


# -- captura ------------------------------------------------------------------------------------------------------

def test_one_request_per_subscription_and_details_are_stored(db_session: Session) -> None:  # noqa: F811
    sub, ch1, ch2, pay1 = _uid("sub"), _uid("ch"), _uid("ch"), _uid("pay")
    _seed_rejected(db_session, sub, [ch1, ch2])
    reason = f"Glosa {_uid()}"
    client = FakeVP({sub: [_item(ch1, pay1, message=reason), _item(ch2, _uid("pay"), code="-11", message=reason + "b")]})
    stats = _run(db_session, client)
    assert client.calls == [(sub, 1, "rechazado")]  # una sola peticion para la suscripcion
    assert stats["subscriptions_checked"] == 1 and stats["details_new"] == 2 and stats["subscriptions_failed"] == 0
    [d1] = _details(db_session, ch1)
    assert (d1.code, d1.reason, d1.payment_external_id, d1.subscription_external_id) == ("-3", reason, pay1, sub)
    assert d1.capture_source == "api_charges" and d1.amount == Decimal("5000.00") and d1.checked_at is not None


def test_message_with_accents_is_kept_as_utf8_and_mojibake_is_repaired(db_session: Session) -> None:  # noqa: F811
    sub, ch1, ch2 = _uid("sub"), _uid("ch"), _uid("ch")
    _seed_rejected(db_session, sub, [ch1, ch2])
    client = FakeVP({sub: [_item(ch1, _uid("pay"), message="Excede límite de reintentos"),
                           _item(ch2, _uid("pay"), code="-11", message="Excede lÃ­mite de reintentos")]})
    _run(db_session, client)
    assert _details(db_session, ch1)[0].reason == "Excede límite de reintentos"
    assert _details(db_session, ch2)[0].reason == "Excede límite de reintentos"


def test_second_run_makes_no_requests_and_creates_no_rows(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    client = FakeVP({sub: [_item(ch, _uid("pay"))]})
    _run(db_session, client)
    before = db_session.scalar(select(func.count()).select_from(PaymentRejectionDetail))
    again = FakeVP({sub: [_item(ch, _uid("pay"))]})
    stats = _run(db_session, again)
    assert again.calls == [] and stats["subscriptions_checked"] == 0
    assert db_session.scalar(select(func.count()).select_from(PaymentRejectionDetail)) == before


def test_cap_per_run_and_the_rest_waits_for_the_next_run(db_session: Session) -> None:  # noqa: F811
    subs = [(_uid("sub"), _uid("ch")) for _ in range(3)]
    for i, (sub, ch) in enumerate(subs):
        _seed_rejected(db_session, sub, [ch], charge_date=f"2026-10-0{i + 1}")
    plan = {sub: [_item(ch, _uid("pay"))] for sub, ch in subs}
    first = FakeVP(plan)
    stats = _run(db_session, first, max_subscriptions=2)
    assert len(first.calls) == 2 and stats["capped"] is True and stats["subscriptions_pending"] >= 3
    assert stats["subscriptions_checked"] == 2
    # Las mas recientes primero: se proceso lo de octubre 3 y 2.
    assert {c[0] for c in first.calls} == {subs[2][0], subs[1][0]}
    second = FakeVP(plan)
    _run(db_session, second, max_subscriptions=2)
    assert [c[0] for c in second.calls][:1] == [subs[0][0]] or subs[0][0] in {c[0] for c in second.calls}
    assert all(_details(db_session, ch) for _, ch in subs)


def test_rejection_without_associated_payment(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    core = CoreCharge(source=PLATFORM, external_id=ch)
    db_session.add(core)
    db_session.flush()
    _run(db_session, FakeVP({sub: [_item(ch, None, code="-6", message="Tarjeta bloqueada")]}))
    [row] = _details(db_session, ch)
    assert row.payment_external_id is None and row.code == "-6"
    # El ETL de core alimenta el cobro aunque no haya pago ni vinculo.
    assert _enrich_charges_with_rejections(db_session) >= 1
    db_session.expire(core)
    assert core.latest_rejection_code == "-6" and core.latest_rejection_reason == "Tarjeta bloqueada"
    assert core.latest_rejection_payment_id is None
    # Idempotente: no duplica la fila al volver a capturar.
    _run(db_session, FakeVP({sub: [_item(ch, None, code="-6", message="Tarjeta bloqueada")]}), recheck_days=0)
    assert len(_details(db_session, ch)) == 1


def test_links_vp_payments_and_core_payments_to_the_charge(db_session: Session) -> None:  # noqa: F811
    sub, ch, pay = _uid("sub"), _uid("ch"), _uid("pay")
    _seed_rejected(db_session, sub, [ch])
    db_session.add(VpPayment(external_id=pay, platform=PLATFORM, status="rechazado", payment_date="2026-10-05"))
    core_charge = CoreCharge(source=PLATFORM, external_id=ch)
    core_payment = CorePayment(source=PLATFORM, external_id=pay, source_status="rechazado")
    db_session.add_all([core_charge, core_payment])
    db_session.flush()
    stats = _run(db_session, FakeVP({sub: [_item(ch, pay, code="-3", message="Excede monto")]}))
    assert stats["payments_linked"] >= 1
    vp_payment = db_session.scalar(select(VpPayment).where(VpPayment.external_id == pay))
    db_session.refresh(vp_payment)
    assert vp_payment.charge_external_id == ch
    db_session.refresh(core_payment)
    assert core_payment.charge_id == core_charge.id
    # Alimenta core_payments.rejection_* y core_charges.latest_rejection_*.
    assert _enrich_payments_with_rejections(db_session) >= 1
    assert _enrich_charges_with_rejections(db_session) >= 1
    db_session.refresh(core_payment)
    db_session.refresh(core_charge)
    assert (core_payment.rejection_code, core_payment.rejection_reason) == ("-3", "Excede monto")
    assert core_charge.latest_rejection_code == "-3" and core_charge.latest_rejection_payment_id == core_payment.id
    # Idempotente.
    assert link_payments_to_charges(db_session, PLATFORM) == {"vp_payments": 0, "core_payments": 0}
    assert _enrich_charges_with_rejections(db_session) == 0 and _enrich_payments_with_rejections(db_session) == 0


def test_link_restores_the_nightly_wipe_of_vp_payments_charge_link(db_session: Session) -> None:  # noqa: F811
    """El sync nocturno reescribe vp_payments.charge_external_id a NULL: el vinculo se rehace desde los detalles."""
    sub, ch, pay = _uid("sub"), _uid("ch"), _uid("pay")
    _seed_rejected(db_session, sub, [ch])
    db_session.add(VpPayment(external_id=pay, platform=PLATFORM, status="rechazado"))
    db_session.flush()
    _run(db_session, FakeVP({sub: [_item(ch, pay)]}))
    db_session.execute(text("UPDATE vp_payments SET charge_external_id = NULL WHERE external_id = :p"), {"p": pay})
    assert link_payments_to_charges(db_session, PLATFORM)["vp_payments"] == 1
    assert db_session.scalar(select(VpPayment.charge_external_id).where(VpPayment.external_id == pay)) == ch


def test_partial_failure_keeps_the_other_subscriptions_and_retries_only_the_failed(db_session: Session) -> None:  # noqa: F811
    (sa, ca), (sb, cb), (sc, cc) = [(_uid("sub"), _uid("ch")) for _ in range(3)]
    for sub, ch, day in ((sa, ca, "03"), (sb, cb, "02"), (sc, cc, "01")):
        _seed_rejected(db_session, sub, [ch], charge_date=f"2026-10-{day}")
    plan = {sa: [_item(ca, _uid("pay"))], sb: [_http_error(500)], sc: [_item(cc, _uid("pay"))]}
    stats = _run(db_session, FakeVP(plan), max_retries=1)
    assert stats["subscriptions_failed"] == 1 and stats["subscriptions_checked"] == 2
    assert _details(db_session, ca) and _details(db_session, cc) and not _details(db_session, cb)
    retry = FakeVP({sb: [_item(cb, _uid("pay"))]})
    _run(db_session, retry)
    assert [c[0] for c in retry.calls] == [sb] and _details(db_session, cb)


def test_backoff_on_429_and_5xx_then_success(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    sleeps = Sleeps()
    client = FakeVP({sub: [_http_error(429, {"Retry-After": "7"}), _http_error(503), [_item(ch, _uid("pay"))]]})
    stats = _run(db_session, client, sleep=sleeps, backoff_base=1.0, max_retries=3)
    assert stats["subscriptions_checked"] == 1 and stats["subscriptions_failed"] == 0 and stats["retries"] == 2
    assert sleeps.waits[0] == 7.0  # respeta Retry-After
    assert sleeps.waits[1] == 2.0  # backoff exponencial: base * 2**1
    assert len(client.calls) == 3


def test_persistent_429_aborts_the_run_early(db_session: Session) -> None:  # noqa: F811
    subs = [(_uid("sub"), _uid("ch")) for _ in range(4)]
    for sub, ch in subs:
        _seed_rejected(db_session, sub, [ch])
    plan = {sub: [_http_error(429)] for sub, _ in subs}
    client = FakeVP(plan)
    stats = _run(db_session, client, max_retries=1)
    assert stats["aborted"] == "rate_limited" and stats["subscriptions_checked"] == 0
    assert len(client.calls) == 2  # un intento + un reintento y se corta: no insiste con las otras suscripciones


def test_charge_not_returned_by_the_api_gets_a_marker_and_is_rechecked_after_the_cutoff(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    _run(db_session, FakeVP({sub: []}))  # p. ej. suscripcion cancelada: 0 cobros
    [marker] = _details(db_session, ch)
    assert marker.code == "" and marker.reason is None
    quiet = FakeVP({sub: []})
    _run(db_session, quiet)
    assert quiet.calls == []  # dentro de la ventana no se repite
    marker.checked_at = datetime.now(UTC) - timedelta(days=40)
    db_session.flush()
    later = FakeVP({sub: [_item(ch, _uid("pay"))]})
    _run(db_session, later, recheck_days=30)
    assert len(later.calls) == 1
    [row] = _details(db_session, ch)  # la glosa real REEMPLAZA al marcador (no quedan dos filas)
    assert row.code == "-3" and row.reason == "Excede monto máximo"


def test_api_error_nok_counts_as_failure_without_marker(db_session: Session) -> None:  # noqa: F811
    from app.integrations.virtualpos.client import VirtualPOSAPIError

    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    stats = _run(db_session, FakeVP({sub: [VirtualPOSAPIError("E-041", "sin datos", 400, 200)]}))
    assert stats["subscriptions_failed"] == 1 and not _details(db_session, ch)


def test_non_rejected_local_charges_are_not_candidates(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch], status="PAGADO")
    client = FakeVP({sub: [_item(ch, _uid("pay"))]})
    assert _run(db_session, client)["subscriptions_pending"] == 0 and client.calls == []


def test_new_reason_registers_catalog_and_emits_reason_changed_once(db_session: Session) -> None:  # noqa: F811
    sub, ch1, ch2 = _uid("sub"), _uid("ch"), _uid("ch")
    _seed_rejected(db_session, sub, [ch1, ch2])
    reason = f"Glosa nueva {_uid()}"
    client = FakeVP({sub: [_item(ch1, _uid("pay"), code="-3", message=reason),
                           _item(ch2, _uid("pay"), code="-3", message=reason)]})
    with status_events.event_context(run_id=None, baseline=False, enabled=True):
        stats = _run(db_session, client)
    assert stats["reasons_new"] == 1
    catalog = db_session.scalar(select(RejectionReasonCatalog).where(
        RejectionReasonCatalog.source == PLATFORM, RejectionReasonCatalog.reason == reason))
    assert catalog is not None and catalog.code == "-3" and catalog.occurrences == 2
    events = list(db_session.scalars(select(StatusChangeEvent).where(
        StatusChangeEvent.event_kind == "reason_changed", StatusChangeEvent.source == PLATFORM,
        StatusChangeEvent.to_value == reason)))
    assert len(events) == 1 and events[0].entity_type == "charge" and events[0].field == "rejection_reason"
    # Otra suscripcion con la misma glosa: suma ocurrencias pero ya no es una glosa nueva.
    sub2, ch3 = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub2, [ch3])
    with status_events.event_context(run_id=None, baseline=False, enabled=True):
        stats2 = _run(db_session, FakeVP({sub2: [_item(ch3, _uid("pay"), code="-3", message=reason)]}))
    assert stats2["reasons_new"] == 0
    db_session.refresh(catalog)
    assert catalog.occurrences == 3


def test_events_disabled_still_stores_details(db_session: Session) -> None:  # noqa: F811
    sub, ch = _uid("sub"), _uid("ch")
    _seed_rejected(db_session, sub, [ch])
    reason = f"Glosa off {_uid()}"
    with status_events.event_context(run_id=None, baseline=False, enabled=False):
        stats = _run(db_session, FakeVP({sub: [_item(ch, _uid("pay"), message=reason)]}))
    assert stats["details_new"] == 1 and stats["reasons_new"] == 0
    assert db_session.scalar(select(RejectionReasonCatalog).where(RejectionReasonCatalog.reason == reason)) is None


def test_pagination_reads_every_page_of_a_subscription(db_session: Session) -> None:  # noqa: F811
    sub, ch1, ch2 = _uid("sub"), _uid("ch"), _uid("ch")
    _seed_rejected(db_session, sub, [ch1, ch2])

    class Paged:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def list_charges(self, subscription_id, page=1, limit=100, status=None):
            self.calls.append(page)
            items = [_item(ch1, _uid("pay"))] if page == 1 else [_item(ch2, _uid("pay"))]
            return {"charges": items, "pagination": {"page": page, "pages": 2, "limit": limit, "total": 2}}

    client = Paged()
    asyncio.run(capture_vp_rejections(db_session, PLATFORM, client, pause_seconds=0.0, sleep=_no_sleep))
    assert client.calls == [1, 2] and _details(db_session, ch1) and _details(db_session, ch2)


def test_unknown_platform_is_rejected(db_session: Session) -> None:  # noqa: F811
    with pytest.raises(ValueError):
        asyncio.run(capture_vp_rejections(db_session, "toku", FakeVP({}), sleep=_no_sleep))
