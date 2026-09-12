from types import SimpleNamespace

from app.services.crm_materialization import _values


def test_extracts_only_known_optional_canonical_fields() -> None:
    record = SimpleNamespace(
        payload={
            "first_name": "Ada",
            "email": "ada@example.test",
            "client_uuid": "client_123",
            "plan_id": "plan_123",
            "name": "Plan premium",
            "type": "FIXED",
            "suscription_id": "subscription_123",
            "suscription_date": "2026-01-01T00:00:00Z",
            "canceled_at": "2026-02-01T00:00:00Z",
            "amount": 12500,
            "status": "ACTIVE",
            "social_id": "11.111.111-1",
            "gender_id": "1",
            "birth_date": "2000-01-01",
            "created": "2026-08-30T10:00:00Z",
            "cards": [
                {
                    "card_reference_id": "card_123",
                    "status": "ACTIVE",
                    "card": {"brand": "VISA", "last4": "1234"},
                }
            ],
        },
        sync_context={"subscription_external_id": "subscription_123"},
    )

    values = _values(record)  # type: ignore[arg-type]

    assert values["first_name"] == "Ada"
    assert values["client_external_id"] == "client_123"
    assert values["name"] == "Plan premium"
    assert values["plan_type"] == "FIXED"
    assert values["subscription_external_id"] == "subscription_123"
    assert values["suscription_date"] == "2026-01-01T00:00:00Z"
    assert values["canceled_at"] == "2026-02-01T00:00:00Z"
    assert values["amount"] == "12500"
    assert values["subscription_external_id"] == "subscription_123"
    assert values["phone_number"] is None
    assert values["social_id"] == "11.111.111-1"
    assert values["provider_created_at"] == "2026-08-30T10:00:00Z"
    assert values["cards"][0]["last4"] == "1234"


def test_extracts_payment_date_from_the_payment_order() -> None:
    record = SimpleNamespace(
        payload={"order": {"authorized_at": "2026-01-01T00:00:00Z"}},
        sync_context={},
    )

    assert _values(record)["payment_date"] == "2026-01-01T00:00:00Z"  # type: ignore[arg-type]


def test_extracts_virtualpos_subscription_rut_and_amount() -> None:
    record = SimpleNamespace(
        payload={
            "client": {"social_id": "11.111.111-1"},
            "amount": 12500,
            "currency": "CLP",
        },
        sync_context={},
    )

    values = _values(record)  # type: ignore[arg-type]

    assert values["client_social_id"] == "11.111.111-1"
    assert values["amount"] == "12500"
    assert values["currency"] == "CLP"
