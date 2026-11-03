"""format_rejection_reason por canal (RJ-03). Ejemplos sintéticos."""

import pytest

from app.services.payku_rejection_codes import payku_rejection_category
from app.services.rejection_format import (
    channel_of_source,
    format_rejection_reason,
    format_rejection_with_code,
    not_reported_label,
)
from app.services.vp_rejection_codes import VP_REJECTION_LABELS


def test_channel_of_source_maps_accounts_and_rejects_unknown() -> None:
    assert channel_of_source("virtualpos1") == "virtualpos"
    assert channel_of_source("virtualpos2") == "virtualpos"
    assert channel_of_source("virtualpos") == "virtualpos"
    assert channel_of_source("toku") == "toku"
    assert channel_of_source("Payku") == "payku"
    assert channel_of_source("tch") is None
    assert channel_of_source(None) is None


def test_virtualpos_keeps_current_behaviour() -> None:
    assert format_rejection_reason("virtualpos1", "-8", "x") == "Tarjeta expirada"
    assert format_rejection_reason("virtualpos2", "ZZ-99", None) == "ZZ-99"
    assert format_rejection_reason("virtualpos1", "ZZ-99", "Texto del proveedor") == "Texto del proveedor"
    assert format_rejection_reason("virtualpos1", None, None) == "No informado por VirtualPOS"


def test_virtualpos_minus_11_text_follows_the_portal() -> None:
    # D17: el texto del `-11` sigue al portal de VirtualPOS (el reporte descargado y el rejected_object
    # real), no la redaccion de la documentacion oficial.
    assert VP_REJECTION_LABELS["-11"] == "Excede límite de reintentos de rechazo"
    assert format_rejection_reason("virtualpos1", "-11", None) == "Excede límite de reintentos de rechazo"


def test_toku_prefers_catalog_message_for_long_and_short_codes() -> None:
    assert format_rejection_reason("toku", "PEPSP1019", "[78] Bloqueada / Primer uso") == "Tarjeta bloqueada"
    assert format_rejection_reason("toku", "1019", None) == "Tarjeta bloqueada"
    assert format_rejection_reason("toku", "TEPSP2070", None) == "Excede límite de reintentos"


def test_toku_without_catalog_hit_uses_normalized_reason_text_then_code() -> None:
    assert (
        format_rejection_reason("toku", "TEPSP7777", "[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33")
        == "RECHAZADA- REINTENTAR"
    )
    assert format_rejection_reason("toku", "ISO:51", "EXCEDE SALDO MAXIMO") == "EXCEDE SALDO MAXIMO"
    assert format_rejection_reason("toku", "ISO:51", None) == "ISO:51"
    assert format_rejection_reason("toku", None, "   ") == "No informado por Toku"
    assert format_rejection_reason("toku", None, None) == "No informado por Toku"


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("Rechazo de transacción.", "REJECT"),
        ("Transacción debe reintentarse.", "RETRY"),
        ("Error en transacción.", "ERROR"),
        ("Rechazo por error de tasa.", "RATE"),
        ("Excede cupo máximo mensual.", "MONTHLY_LIMIT"),
        ("Excede límite diario por transacción.", "DAILY_LIMIT"),
        ("Rubro no autorizado.", "MCC"),
        ("  rechazo de transaccion  ", "REJECT"),
    ],
)
def test_payku_category_from_gateway_message(text: str, category: str) -> None:
    assert payku_rejection_category(text) == category


def test_payku_unknown_or_success_message_has_no_category() -> None:
    assert payku_rejection_category("successful transaction") is None
    assert payku_rejection_category("mensaje nuevo") is None
    assert payku_rejection_category(None) is None


def test_payku_formats_known_messages_and_falls_back_to_raw_text() -> None:
    assert format_rejection_reason("payku", None, "Excede cupo máximo mensual.") == "Excede el cupo máximo mensual"
    assert format_rejection_reason("payku", "RETRY", "Transacción debe reintentarse.") == "La transacción debe reintentarse"
    assert format_rejection_reason("payku", None, "Mensaje nuevo del gateway") == "Mensaje nuevo del gateway"
    assert format_rejection_reason("payku", "MCC", None) == "Rubro no autorizado"
    assert format_rejection_reason("payku", None, None) == "No informado por Payku"


def test_unknown_source_falls_back_to_raw_then_code_then_generic() -> None:
    assert format_rejection_reason("tch", "X1", "texto") == "texto"
    assert format_rejection_reason("tch", "X1", None) == "X1"
    assert format_rejection_reason("tch", None, None) == "No informado"
    assert not_reported_label("toku") == "No informado por Toku"
    assert not_reported_label(None) == "No informado"


def test_virtualpos_acquirer_code_documented_in_repo_has_label() -> None:
    # VP-PAR-05: -2122 tiene glosa documentada (payments.md); los demas -2xxx usan la glosa del proveedor.
    assert format_rejection_reason("virtualpos1", "-2122", None) == "Violación de seguridad (adquirente)"
    assert format_rejection_reason("virtualpos2", "-2119", "Excede saldo maximo") == "Excede saldo maximo"
    assert format_rejection_reason("virtualpos2", "-2119", None) == "-2119"


def test_vp_par_05_closed_only_documented_acquirer_codes_have_labels() -> None:
    # d120 (opcion b): los -2xxx sin glosa documentada conservan la del proveedor; no se inventan etiquetas.
    from app.services.vp_rejection_codes import VP_ACQUIRER_REJECTION_LABELS, VP_REJECTION_LABELS

    assert set(VP_ACQUIRER_REJECTION_LABELS) == {"-2122"}
    assert {c for c in VP_REJECTION_LABELS if c.startswith("-2") and len(c) == 5} == {"-2122"}
    for code in ("-2121", "-2133", "-2150", "-2152"):
        assert format_rejection_reason("virtualpos1", code, "Glosa del proveedor") == "Glosa del proveedor"


def test_format_with_code_appends_provider_code() -> None:
    # VP-PAR-03: el motivo legible se muestra con el codigo tal como esta guardado.
    assert format_rejection_with_code("virtualpos1", "-8", "x") == "Tarjeta expirada (código -8)"
    assert format_rejection_with_code("virtualpos2", "-2119", "Excede saldo maximo") == "Excede saldo maximo (código -2119)"
    assert format_rejection_with_code("virtualpos1", "-2119", None) == "-2119"
    assert format_rejection_with_code("toku", "1019", None) == "Tarjeta bloqueada (código 1019)"
    assert format_rejection_with_code("virtualpos1", None, None) == "No informado por VirtualPOS"
    assert format_rejection_with_code("payku", "  ", "Rubro no autorizado.") == "Rubro no autorizado"
