"""Unit tests for _classify_rejection in write_virtualpos.

The function gates VP retry writes — it must return the correct decision
for all code sets, keyword matches, and prior_retries escalation paths.
"""
import pytest

from app.services.write_virtualpos import _classify_rejection


def _payload(code: str = "", message: str = "", response_desc: str = "", cards: list | None = None) -> dict:
    return {
        "rejected_object": {
            "code": code,
            "message": message,
        },
        "payment": {
            "order": {
                "authorization_attempts_cards": cards or (
                    [{"created_at": "2026-01-01T00:00:00", "response_description": response_desc}]
                    if response_desc else []
                ),
            }
        },
    }


# ── Código exacto → CAMBIO_TARJETA ────────────────────────────────────────────

@pytest.mark.parametrize("code", ["-1", "-4", "-5", "-7", "-8", "-9", "-11", "-1013", "-1016"])
def test_card_codes_return_cambio_tarjeta(code: str) -> None:
    assert _classify_rejection(_payload(code=code)) == "CAMBIO_TARJETA"


@pytest.mark.parametrize("code", ["-1003", "-1009", "-1010", "-1014", "-1015"])
def test_merchant_codes_return_diferir(code: str) -> None:
    assert _classify_rejection(_payload(code=code)) == "DIFERIR"


# ── Código _RETRY_CODES: escalación por prior_retries ─────────────────────────

@pytest.mark.parametrize("code", ["-2", "-10"])
def test_retry_codes_first_attempt_return_reintentar(code: str) -> None:
    assert _classify_rejection(_payload(code=code), prior_retries=0) == "REINTENTAR"


@pytest.mark.parametrize("code", ["-2", "-10"])
def test_retry_codes_subsequent_attempt_return_manual(code: str) -> None:
    assert _classify_rejection(_payload(code=code), prior_retries=1) == "MANUAL"
    assert _classify_rejection(_payload(code=code), prior_retries=3) == "MANUAL"


# ── Código _RETRY_ONCE_CODES: escalación por prior_retries ────────────────────

@pytest.mark.parametrize("code", ["-6", "-3"])
def test_retry_once_codes_first_attempt_return_reintentar(code: str) -> None:
    assert _classify_rejection(_payload(code=code), prior_retries=0) == "REINTENTAR"


@pytest.mark.parametrize("code", ["-6", "-3"])
def test_retry_once_codes_subsequent_attempt_return_cambio_tarjeta(code: str) -> None:
    assert _classify_rejection(_payload(code=code), prior_retries=1) == "CAMBIO_TARJETA"
    assert _classify_rejection(_payload(code=code), prior_retries=2) == "CAMBIO_TARJETA"


# ── 3+ tarjetas intentadas → CAMBIO_TARJETA ───────────────────────────────────

def test_three_cards_return_cambio_tarjeta() -> None:
    payload = {
        "rejected_object": {},
        "payment": {
            "order": {
                "authorization_attempts_cards": [
                    {"created_at": "2026-01-01T00:00:00"},
                    {"created_at": "2026-01-01T00:01:00"},
                    {"created_at": "2026-01-01T00:02:00"},
                ]
            }
        },
    }
    assert _classify_rejection(payload) == "CAMBIO_TARJETA"


def test_two_cards_does_not_trigger_cambio_tarjeta_by_count() -> None:
    payload = {
        "rejected_object": {},
        "payment": {
            "order": {
                "authorization_attempts_cards": [
                    {"created_at": "2026-01-01T00:00:00"},
                    {"created_at": "2026-01-01T00:01:00"},
                ]
            }
        },
    }
    # Without a code match either, falls through to DESCONOCIDO
    assert _classify_rejection(payload) == "DESCONOCIDO"


# ── Keyword matches en texto libre ───────────────────────────────────────────

@pytest.mark.parametrize("word", ["vencida", "expirado", "bloqueada", "inválida", "robada", "perdida", "cancelada",
                                   "no soportada", "seguridad", "restringida"])
def test_card_keywords_return_cambio_tarjeta(word: str) -> None:
    assert _classify_rejection(_payload(message=word)) == "CAMBIO_TARJETA"


@pytest.mark.parametrize("word", ["fondos insuficientes", "saldo insuficiente", "cupo excedido",
                                   "timeout", "temporal", "intente de nuevo", "no disponible"])
def test_retry_keywords_first_attempt_return_reintentar(word: str) -> None:
    assert _classify_rejection(_payload(message=word), prior_retries=0) == "REINTENTAR"


@pytest.mark.parametrize("word", ["fondos insuficientes", "saldo insuficiente", "cupo excedido",
                                   "timeout", "temporal", "intente de nuevo", "no disponible"])
def test_retry_keywords_subsequent_attempt_return_cambio_tarjeta(word: str) -> None:
    assert _classify_rejection(_payload(message=word), prior_retries=1) == "CAMBIO_TARJETA"


# ── Sin código ni keyword → DESCONOCIDO ─────────────────────────────────────

def test_empty_payload_returns_desconocido() -> None:
    assert _classify_rejection({}) == "DESCONOCIDO"


def test_unknown_code_returns_desconocido() -> None:
    assert _classify_rejection(_payload(code="-9999")) == "DESCONOCIDO"


# ── Texto en response_description (última tarjeta) ───────────────────────────

def test_response_description_card_keyword_returns_cambio_tarjeta() -> None:
    assert _classify_rejection(_payload(response_desc="tarjeta vencida")) == "CAMBIO_TARJETA"


def test_response_description_retry_keyword_returns_reintentar() -> None:
    assert _classify_rejection(_payload(response_desc="fondos insuficientes"), prior_retries=0) == "REINTENTAR"
