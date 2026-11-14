"""d212: el saneador de payloads normaliza las claves (tildes, mayusculas, separadores) antes de comparar."""

import pytest

from app.services.payload_sanitization import is_sensitive_key, sanitize_payload

ACCOUNT = "000123456789"  # sintetico


def test_tch_header_with_accent_is_removed() -> None:
    """Caso del informe TCH: «Número Cuenta» se normalizaba a `n_mero_cuenta` y quedaba la cuenta completa."""
    out = sanitize_payload({"Número Cuenta": ACCOUNT, "Tipo Cuenta": "Corriente", "Folio": "F-1"})
    assert out == {"Tipo Cuenta": "Corriente", "Folio": "F-1"}
    assert ACCOUNT not in str(out)


@pytest.mark.parametrize("key", [
    "Número Cuenta", "NÚMERO CUENTA", "número_cuenta", "Numero-Cuenta", "numero cuenta", "  Número   Cuenta ",
    "NumeroCuenta", "numerocuenta", "Número de Cuenta", "N° Cuenta", "Nº Cuenta", "Nro. Cuenta", "Num Cuenta",
    "Cuenta Bancaria", "Número Cuenta Bancaria", "accountNumber", "Account-Number", "bank_account_number",
])
def test_account_number_variants_are_sensitive(key: str) -> None:
    assert is_sensitive_key(key)
    assert sanitize_payload({"fila": [{key: ACCOUNT}]}) == {"fila": [{}]}


@pytest.mark.parametrize("key", [
    "Card Number", "card-number", "CardNumber", "CVV", "Security Code",
    "API-Key", "apiKey", "Secret Key", "Verification-Key", "Auth Code", "Card Token", "Private Token",
])
def test_existing_sensitive_keys_tolerate_case_and_separators(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", [
    "Tipo Cuenta", "cuenta", "Cuenta", "id_account", "account", "Banco", "Número", "Folio", "Moneda Vigente",
    "panel", "token_type_hint", "signed_at", "Número Cuota",
])
def test_non_sensitive_keys_are_kept(key: str) -> None:
    assert not is_sensitive_key(key)
    assert sanitize_payload({key: "x"}) == {key: "x"}
