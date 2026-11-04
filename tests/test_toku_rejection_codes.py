"""Catálogo de rechazos de Toku y normalización de glosas del procesador (RJ-02). Ejemplos sintéticos."""

import pytest

from app.services.toku_rejection_codes import (
    TOKU_REJECTION_CODES,
    lookup_toku_code,
    normalize_processor_message,
    parse_toku_response_code,
)

OFFICIAL_CODES = {
    "0000", "1001", "1002", "1007", "1008", "1010", "1011", "1017", "1019", "1059", "1062", "1073",
    "2005", "2006", "2008", "2009", "2028", "2035", "2063", "2070", "2106", "4007", "5408", "9999",
}


def test_catalog_has_the_24_official_codes_with_severity_and_message() -> None:
    assert set(TOKU_REJECTION_CODES) == OFFICIAL_CODES
    assert len(TOKU_REJECTION_CODES) == 24
    for entry in TOKU_REJECTION_CODES.values():
        assert entry.severity in {"SU", "TE", "PE", "UE"}
        assert entry.message
    assert TOKU_REJECTION_CODES["0000"].severity == "SU"
    assert TOKU_REJECTION_CODES["1019"].severity == "PE"
    assert TOKU_REJECTION_CODES["1019"].message == "Tarjeta bloqueada"
    assert TOKU_REJECTION_CODES["2070"].message == "Excede límite de reintentos"
    assert TOKU_REJECTION_CODES["9999"].severity == "UE"


def test_parse_long_code_into_severity_source_and_detail() -> None:
    parsed = parse_toku_response_code("TEPSP1008")
    assert parsed is not None
    assert (parsed.severity, parsed.source, parsed.detail) == ("TE", "PSP", "1008")
    assert parse_toku_response_code(" peBCH2063 ").detail == "2063"  # type: ignore[union-attr]
    for bad in (None, "", "1008", "XXPSP1008", "TEPSP10", "TEPSP10089"):
        assert parse_toku_response_code(bad) is None


def test_lookup_accepts_long_or_short_code_and_returns_none_if_unknown() -> None:
    assert lookup_toku_code("TEPSP1008").message == "Tarjeta rechazada"  # type: ignore[union-attr]
    assert lookup_toku_code("1008").message == "Tarjeta rechazada"  # type: ignore[union-attr]
    assert lookup_toku_code("PEBCH2063").message == "Tarjeta expirada"  # type: ignore[union-attr]
    assert lookup_toku_code("TEPSP7777") is None
    assert lookup_toku_code(None) is None
    assert lookup_toku_code("") is None


def test_codes_used_by_business_rules_but_missing_from_official_sheet_are_not_invented() -> None:
    # DEC-16 a DEC-25 usan 1051, 2043 y 2044, pero no están en la hoja oficial de 24 códigos.
    for code in ("1051", "2043", "2044"):
        assert code not in TOKU_REJECTION_CODES
        assert lookup_toku_code(f"PEPSP{code}") is None


@pytest.mark.parametrize(
    ("raw", "text", "processor_code"),
    [
        ("[51] EXCEDE SALDO MAXIMO", "EXCEDE SALDO MAXIMO", "51"),
        ("[51] EXCEDE SALDO MAXIMO. Intente de nuevo mas tarde", "EXCEDE SALDO MAXIMO. Intente de nuevo mas tarde", "51"),
        ("[05] RECHAZADA- CONTACTE A SU EMISOR", "RECHAZADA- CONTACTE A SU EMISOR", "05"),
        ("[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33", "RECHAZADA- REINTENTAR", "51"),
        ("[46] RECHAZADA- REINTENTAR EL 31-03-2026 A LAS 05:14", "RECHAZADA- REINTENTAR", "46"),
        ("[9G] TARJETA BLOQUEADA POR EL TITULAR", "TARJETA BLOQUEADA POR EL TITULAR", "9G"),
        ("[R3] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:29", "RECHAZADA- REINTENTAR", "R3"),
        ("[] EXCEDE SALDO MAXIMO", "EXCEDE SALDO MAXIMO", None),
        ("RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33", "RECHAZADA- REINTENTAR", None),
        ("RECHAZADA- REINTENTAR EL -- A LAS :", "RECHAZADA- REINTENTAR", None),
        ("BRAND_CHARGE_LIMIT-EXCEEDED", "BRAND_CHARGE_LIMIT-EXCEEDED", None),
        ("800", "800", None),
        ("  [82]   Declinada - Politica Mastercard.  Intente de nuevo mas tarde ", "Declinada - Politica Mastercard. Intente de nuevo mas tarde", "82"),
    ],
)
def test_normalize_processor_message_drops_date_time_and_extracts_iso(raw: str, text: str, processor_code: str | None) -> None:
    result = normalize_processor_message(raw)
    assert result is not None
    assert result.text == text
    assert result.processor_code == processor_code


def test_normalization_groups_messages_that_differ_only_by_date_and_time() -> None:
    a = normalize_processor_message("[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 06:54")
    b = normalize_processor_message("[51] RECHAZADA- REINTENTAR EL 22-04-2026 A LAS 05:19")
    assert a == b


def test_normalize_handles_empty_and_html_bodies() -> None:
    assert normalize_processor_message(None) is None
    assert normalize_processor_message("   ") is None
    html = normalize_processor_message("<html><body><h1>503 Service Unavailable</h1>\nNo server is available</body></html>")
    assert html is not None
    assert html.processor_code is None
    assert "<" not in html.text and len(html.text) <= 200
