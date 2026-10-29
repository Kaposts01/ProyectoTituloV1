"""TK-PAR-05: fechas reales de alta y baja de las suscripciones de Toku, desde el reporte de Productos.

Tres situaciones: suscripcion activa (alta real distinta del ancla de la API), eliminada que la API ya no lista
(se crea en core como registro de baja) y fecha de baja distinta entre reporte y API (gana la API).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from toku_signals_support import World, api_subscription, uid

from app.models.core import CoreCharge, CoreSubscription
from app.models.crm import Subscription
from app.models.toku_channel import TokuInvoice
from app.services import channel_consolidation, core_toku_etl
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)


def _core(db: Session, sub: str) -> CoreSubscription | None:
    db.expire_all()
    return db.scalar(select(CoreSubscription).where(CoreSubscription.source == "toku", CoreSubscription.external_id == sub))


def _etl_subscriptions(db: Session) -> None:
    core_toku_etl._materialize_subscriptions(db)
    core_toku_etl._materialize_stub_subscriptions(db)


def test_active_subscription_gets_the_real_start_date_not_the_next_charge(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    world = World(db_session)
    api_subscription(db_session, sub, anchor="2026-11-05")  # `anchor` = proximo cobro
    world.product(sub, created=datetime(2024, 8, 13, 13, 0, tzinfo=UTC))
    _etl_subscriptions(db_session)
    result = core_toku_etl.materialize_report_dates(db_session)
    row = _core(db_session, sub)
    assert row.started_at == datetime(2024, 8, 13, 13, 0, tzinfo=UTC)
    assert row.ended_at is None and row.status == "ACTIVE"  # la API manda en el estado de una viva
    assert result["started_at_set"] >= 1


def test_deleted_subscription_missing_from_the_api_is_created_as_a_baja_record(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    world = World(db_session)
    world.product(
        sub,
        created=datetime(2024, 9, 2, 13, 0, tzinfo=UTC),
        deleted=datetime(2025, 1, 15, 15, 0, tzinfo=UTC),
        amount="5000",
    )
    result = core_toku_etl.materialize_report_dates(db_session)
    row = _core(db_session, sub)
    assert row is not None and row.status == "deleted_at_source"
    assert row.started_at == datetime(2024, 9, 2, 13, 0, tzinfo=UTC)
    assert row.ended_at == datetime(2025, 1, 15, 15, 0, tzinfo=UTC)
    assert str(row.amount) == "5000.00" and row.currency == "CLP"
    assert result["deleted_created"] >= 1
    # idempotente: la segunda pasada no crea ni cambia nada
    again = core_toku_etl.materialize_report_dates(db_session)
    assert again["deleted_created"] == 0 and again["started_at_set"] == 0 and again["ended_at_set"] == 0
    assert db_session.scalar(
        select(func.count()).select_from(CoreSubscription).where(CoreSubscription.external_id == sub)
    ) == 1


def test_baja_record_links_the_client_when_the_identity_exists_and_stores_no_personal_data(db_session: Session) -> None:  # noqa: F811
    from app.models.core import CoreClient, ExternalIdentity

    sub, customer = uid("sub"), uid("cus")
    client = CoreClient()
    db_session.add(client)
    db_session.flush()
    db_session.add(ExternalIdentity(source="toku", resource_type="client", external_id=customer, client_id=client.id))
    World(db_session).product(sub, customer=customer, deleted=datetime(2025, 2, 1, 15, 0, tzinfo=UTC))
    core_toku_etl.materialize_report_dates(db_session)
    assert _core(db_session, sub).client_id == client.id


def test_existing_stub_without_dates_is_enriched_from_the_report(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    db_session.add(TokuInvoice(external_id=uid("in"), subscription_id=sub, status="PAID", amount="1000", due_date="2025-03-01"))
    db_session.flush()
    core_toku_etl._materialize_stub_subscriptions(db_session)
    assert _core(db_session, sub).started_at is None
    World(db_session).product(
        sub, created=datetime(2024, 10, 1, 13, 0, tzinfo=UTC), deleted=datetime(2025, 4, 1, 15, 0, tzinfo=UTC)
    )
    core_toku_etl.materialize_report_dates(db_session)
    row = _core(db_session, sub)
    assert row.status == "deleted_at_source"
    assert (row.started_at, row.ended_at) == (datetime(2024, 10, 1, 13, 0, tzinfo=UTC), datetime(2025, 4, 1, 15, 0, tzinfo=UTC))


def test_api_end_date_is_not_overwritten_by_the_report(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub, status="ACTIVE", end_date="2026-03-01")
    World(db_session).product(
        sub, created=datetime(2024, 8, 13, 13, 0, tzinfo=UTC), deleted=datetime(2026, 3, 5, 15, 0, tzinfo=UTC)
    )
    _etl_subscriptions(db_session)
    core_toku_etl.materialize_report_dates(db_session)
    assert _core(db_session, sub).ended_at == datetime(2026, 3, 1, tzinfo=UTC)
    # y un nuevo sync de la API no borra las fechas que vienen del reporte
    _etl_subscriptions(db_session)
    row = _core(db_session, sub)
    assert row.started_at == datetime(2024, 8, 13, 13, 0, tzinfo=UTC) and row.ended_at == datetime(2026, 3, 1, tzinfo=UTC)


def test_report_dates_survive_the_next_api_sync_of_the_core_subscription(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub)
    World(db_session).product(sub, created=datetime(2024, 8, 13, 13, 0, tzinfo=UTC), deleted=datetime(2026, 5, 2, 15, 0, tzinfo=UTC))
    _etl_subscriptions(db_session)
    core_toku_etl.materialize_report_dates(db_session)
    _etl_subscriptions(db_session)  # el sync de la API vuelve a escribir `started_at`/`ended_at`
    row = _core(db_session, sub)
    assert row.started_at is not None and row.ended_at == datetime(2026, 5, 2, 15, 0, tzinfo=UTC)


def test_dry_run_reports_counts_and_writes_nothing(db_session: Session) -> None:  # noqa: F811
    sub, live = uid("sub"), uid("sub")
    world = World(db_session)
    api_subscription(db_session, live)
    world.product(live)
    world.product(sub, deleted=datetime(2025, 1, 15, 15, 0, tzinfo=UTC))
    _etl_subscriptions(db_session)
    result = core_toku_etl.materialize_report_dates(db_session, dry_run=True)
    assert result["deleted_created"] >= 1 and result["started_at_set"] >= 1 and result["dry_run"] is True
    assert _core(db_session, sub) is None and _core(db_session, live).started_at is None


def test_subscription_without_report_row_is_left_untouched(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub)
    _etl_subscriptions(db_session)
    core_toku_etl.materialize_report_dates(db_session)
    row = _core(db_session, sub)
    assert row.started_at is None and row.ended_at is None


def test_run_toku_core_etl_includes_the_report_dates_step(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub)
    World(db_session).product(sub, created=datetime(2024, 8, 13, 13, 0, tzinfo=UTC))
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert result["report_started_at_set"] >= 1 and "report_deleted_created" in result
    assert _core(db_session, sub).started_at == datetime(2024, 8, 13, 13, 0, tzinfo=UTC)


# ---- tabla centralizada `subscriptions` (consolidacion) -------------------------------------------------------


def _central(db: Session, sub: str) -> Subscription:
    db.expire_all()
    return db.scalar(select(Subscription).where(Subscription.source == "toku", Subscription.external_id == sub))


def test_centralized_subscription_date_uses_the_report_start_not_the_anchor(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub, anchor="2026-11-05")
    World(db_session).product(sub, created=datetime(2024, 8, 13, 13, 0, tzinfo=UTC), deleted=datetime(2026, 5, 2, 15, 0, tzinfo=UTC))
    channel_consolidation._consolidate_toku_subscriptions(db_session)
    row = _central(db_session, sub)
    assert row.suscription_date == "2024-08-13" and row.canceled_at == "2026-05-02"


def test_centralized_dates_fall_back_to_the_api_without_a_report_row_and_api_end_date_wins(db_session: Session) -> None:  # noqa: F811
    plain, ended = uid("sub"), uid("sub")
    api_subscription(db_session, plain, anchor="2026-11-05")
    api_subscription(db_session, ended, end_date="2026-03-01")
    World(db_session).product(ended, deleted=datetime(2026, 3, 5, 15, 0, tzinfo=UTC))
    channel_consolidation._consolidate_toku_subscriptions(db_session)
    assert _central(db_session, plain).suscription_date == "2026-11-05" and _central(db_session, plain).canceled_at is None
    assert _central(db_session, ended).canceled_at == "2026-03-01"


def test_chile_date_is_used_near_midnight(db_session: Session) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub)
    # 2024-08-14 02:30 UTC = 2024-08-13 22:30 en Chile (UTC-4 en invierno)
    World(db_session).product(sub, created=datetime(2024, 8, 14, 2, 30, tzinfo=UTC))
    channel_consolidation._consolidate_toku_subscriptions(db_session)
    assert _central(db_session, sub).suscription_date == "2024-08-13"


def test_charges_of_a_baja_record_attach_to_it(db_session: Session) -> None:  # noqa: F811
    sub, inv = uid("sub"), uid("in")
    World(db_session).product(sub, deleted=datetime(2025, 1, 15, 15, 0, tzinfo=UTC))
    db_session.add(TokuInvoice(external_id=inv, subscription_id=sub, status="PAID", amount="1000", due_date="2024-12-01"))
    db_session.flush()
    core_toku_etl.materialize_report_dates(db_session)
    core_toku_etl._materialize_charges(db_session)
    charge = db_session.scalar(select(CoreCharge).where(CoreCharge.external_id == inv))
    assert charge is not None and charge.subscription_id == _core(db_session, sub).id


@pytest.mark.parametrize("missing", ["created", "deleted"])
def test_report_rows_without_dates_do_not_break(db_session: Session, missing) -> None:  # noqa: F811
    sub = uid("sub")
    api_subscription(db_session, sub)
    kw = {"created": None} if missing == "created" else {}
    World(db_session).product(sub, **kw)
    _etl_subscriptions(db_session)
    core_toku_etl.materialize_report_dates(db_session)
    assert _core(db_session, sub) is not None
