from app.integrations.virtualpos.auth import build_signature
from app.services.virtualpos_sync import (
    _external_id,
    _has_next_page,
    _records_from_response,
    _sanitize_record,
    _subscription_id,
)


def test_build_signature_matches_hs256_jwt_format() -> None:
    signature = build_signature("sandbox-key", "sandbox-secret")

    assert signature == (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJhcGlfa2V5Ijoic2FuZGJveC1rZXkifQ."
        "UMl6ZCDxz_rMaQWfyLISAcTVTKOcVtyL3wu9jChE6z8"
    )


def test_reads_common_response_envelope_and_subscription_identifier() -> None:
    records = _records_from_response({"suscriptions": [{"id": "sub_123"}]})

    assert records == [{"id": "sub_123"}]
    assert _subscription_id(records[0]) == "sub_123"


def test_continues_subscription_pagination_from_metadata_or_full_page() -> None:
    records = [{"id": str(index)} for index in range(100)]

    assert _has_next_page({"pagination": {"pages": 2}}, records, page=1, limit=100)
    assert _has_next_page([], records, page=1, limit=100)
    assert not _has_next_page({"meta": {"has_next": False}}, records, page=1, limit=100)


def test_uses_nested_payment_order_uuid_as_external_identifier() -> None:
    assert _external_id({"order": {"uuid": "payment_123"}}) == "payment_123"


def test_removes_card_data_before_staging_provider_payloads() -> None:
    record = _sanitize_record({"order": {"uuid": "payment_123", "card_number": "4111111111111111"}})

    assert record == {"order": {"uuid": "payment_123"}}
