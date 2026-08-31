from app.integrations.virtualpos.auth import build_signature
from app.services.virtualpos_sync import _records_from_response, _subscription_id


def test_build_signature_matches_hs256_jwt_format() -> None:
    signature = build_signature("sandbox-key", "sandbox-secret")

    assert signature == (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJhcGlfa2V5Ijoic2FuZGJveC1rZXkifQ."
        "UMl6ZCDxz_rMaQWfyLISAcTVTKOcVtyL3wu9jChE6z8"
    )


def test_reads_common_response_envelope_and_subscription_identifier() -> None:
    records = _records_from_response({"data": [{"id": "sub_123"}]})

    assert records == [{"id": "sub_123"}]
    assert _subscription_id(records[0]) == "sub_123"
