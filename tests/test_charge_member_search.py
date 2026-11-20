"""Search the displayed member identity; retain source scope and redact exports without PII."""

import uuid

import pytest

from app.db.session import SessionLocal
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.payku_channel import PaykuCycle
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.services.export_queries import ExportFilters, fetch_page, select_specs
from app.services.unified_views import build_filters


@pytest.fixture
def records():
    tag = f"DEMO-UX-{uuid.uuid4().hex[:10]}"
    number = 10_000_000 + int(uuid.uuid4().hex[:6], 16) % 70_000_000
    rut = f"{number}-K"  # Synthetic identifier; search normalization does not validate its check digit.
    file_number = 100_000_000 + int(uuid.uuid4().hex[:6], 16)
    with SessionLocal() as db:
        transaction = db.begin()
        try:
            for channel in ("virtualpos1", "toku", "payku"):
                key = f"{tag}-{channel}"
                db.add_all([
                    Client(source=channel, external_id=key, social_id=rut, first_name=tag, last_name=channel),
                    Subscription(source=channel, external_id=key, client_external_id=key, client_social_id=rut, status="activa"),
                    Charge(source=channel, external_id=key, subscription_external_id=key, status="pagado", amount="12500", charge_date="2026-01-05"),
                    Payment(source=channel, external_id=key, client_external_id=key, status="paid", amount="12500", payment_date="2026-01-05"),
                ])
            db.add_all([
                PaykuCycle(external_id=f"{tag}-payku", subscription_id=f"{tag}-payku", cycle_day="2026-01-05", status="paid", amount_paid="12500"),
                TchClient(rut=rut, name=tag, last_name="tch"),
                TchSubscription(file_number=file_number, client_rut=rut, status="VIGENTE"),
                TchTransaction(file_number=file_number, dedupe_key=tag, status="ACEPTADA", amount="12500", charge_date="2026-01-05"),
            ])
            db.flush()
            yield db, tag, rut
        finally:
            transaction.rollback()


@pytest.mark.parametrize("entity,channel", [
    ("cobros", "virtualpos1"), ("cobros", "toku"), ("cobros", "payku"), ("cobros", "tch"),
    ("pagos", "virtualpos1"), ("pagos", "toku"), ("pagos", "payku"),
])
@pytest.mark.parametrize("field", ["client", "rut", "all"])
def test_search_and_export_counts_use_same_identity_without_exposing_pii(records, entity, channel, field):
    db, tag, rut = records
    needle = f"{tag} {channel}" if field != "rut" else f"{int(rut.split('-')[0]):,}".replace(",", ".") + "-k"
    filters = build_filters(entity, query=needle, filter_field=field, status=None, date_from=None, date_to=None)
    permissions = {"general.charges.view"}
    specs, denied = select_specs(entity, channel, permissions)
    assert not denied
    rows, counts = fetch_page(db, specs, filters, True, 0, 50)
    assert len(rows) == 1 and sum(counts.values()) == 1
    assert rows[0]["name"] == f"{tag} {channel}"
    assert rows[0]["channel"] == channel
    redacted, export_counts = fetch_page(db, specs, filters, False, 0, 50)
    assert export_counts == counts and len(redacted) == 1
    assert redacted[0]["rut"] is None and redacted[0]["name"] is None
    assert "query" not in filters.audit()
    assert filters.audit()["query_len"] == len(needle)
    absent, _ = fetch_page(db, specs, ExportFilters(query="NO-EXISTE-UX", filter_field="client"), True, 0, 50)
    assert absent == []
    other_channel = "toku" if channel != "toku" else "virtualpos1"
    unrelated, _ = fetch_page(db, specs, ExportFilters(query=f"{tag} {other_channel}", filter_field="client"), True, 0, 50)
    assert unrelated == []  # Sharing a RUT must not substitute a different source's name.


def test_search_does_not_grant_other_channels():
    specs, denied = select_specs("cobros", "toku", {"virtualpos.charges.view"})
    assert specs == [] and denied
