"""VP-PAR-02 (parte 2): parser de los reportes PAT de VirtualPOS. CSV sinteticos con los encabezados reales."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from vp_reports_support import (
    COLUMNS,
    PEPPER,
    PII_SENTINELS,
    SENTINEL_PAN,
    SENTINEL_SELLER,
    charge_id,
    payment_row,
    rejected_payment_row,
    sub_id,
    subscription_row,
    uuid_of,
    write_report,
)

from app.services import vp_report_parser as vp
from app.services.vp_report_parser import (
    ReportFormatError,
    UnsupportedReportError,
    open_report,
)

CHILE = ZoneInfo("America/Santiago")


def _read(path, **kw):
    kw.setdefault("pepper", PEPPER)
    with open_report(path, **kw) as parsed:
        return parsed.meta, parsed.stats, list(parsed.records())


# ---- deteccion del tipo por firma ---------------------------------------------------------------


def test_detects_type_by_column_signature_not_by_filename(tmp_path):
    p = write_report(tmp_path / "cualquier-nombre.csv", "transacciones")
    s = write_report(tmp_path / "TransaccionesPAT-engañoso.csv", "suscriptores")
    assert _read(p)[0].report_type == "transacciones"
    assert _read(s)[0].report_type == "suscriptores"


def test_shifted_header_semicolon_and_no_bom(tmp_path):
    path = write_report(tmp_path / "a.csv", "transacciones", title_lines=3, delimiter=";", bom=False)
    meta, stats, records = _read(path)
    assert meta.report_type == "transacciones" and len(records) == 3 and stats.rows_skipped == 0


def test_tab_delimiter_and_latin1_encoding(tmp_path):
    path = write_report(tmp_path / "a.csv", "suscriptores", delimiter="\t", encoding="cp1252", bom=False)
    meta, _, records = _read(path)
    assert meta.report_type == "suscriptores" and len(records) == 3


def test_mojibake_headers_and_cells_are_repaired(tmp_path):
    rows = [rejected_payment_row(1, "-3", "Excede monto máximo"), payment_row(2, **{"Alias POS": "Sucursal Ñuñoa"})]
    path = write_report(tmp_path / "a.csv", "transacciones", rows, mojibake=True)
    meta, _, records = _read(path)
    assert meta.report_type == "transacciones"
    assert records[0].response_text == "Excede monto máximo" and records[1].pos_alias == "Sucursal Ñuñoa"


def test_duplicated_column_uses_first_occurrence(tmp_path):
    path = write_report(
        tmp_path / "a.csv", "transacciones", [payment_row(1)], extra_columns={"Medio de pago": "Crédito"}
    )
    meta, _, records = _read(path)
    assert records[0].payment_medium == "Débito"  # la primera columna «Medio de pago» gana
    assert "Medio de pago" in meta.extra_columns  # la repetida se informa por nombre, sin valor
    assert "Crédito" not in repr(records)


def test_extra_columns_are_reported_by_name_only(tmp_path):
    path = write_report(tmp_path / "a.csv", "transacciones", extra_columns={"Columna nueva": "SENTINELA-EXTRA"})
    meta, _, records = _read(path)
    assert "Columna nueva" in meta.extra_columns
    assert "SENTINELA-EXTRA" not in repr(meta) + repr(records)


# ---- errores de formato (sin eco de valores) ------------------------------------------------------


def test_missing_columns_error_names_columns_only(tmp_path):
    header = [c for c in COLUMNS["transacciones"] if c not in ("Glosa de autorización/error/rechazo", "Alias POS")]
    path = write_report(tmp_path / "a.csv", "transacciones", [payment_row(1)], header_override=header)
    with pytest.raises(ReportFormatError) as err:
        open_report(path, pepper=PEPPER)
    message = str(err.value)
    assert "transacciones" in message and "glosa" in message.lower() and "alias pos" in message.lower()
    assert not any(s in message for s in PII_SENTINELS)


def test_unrelated_csv_is_unsupported(tmp_path):
    path = tmp_path / "otro.csv"
    path.write_text("col_a,col_b,col_c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(UnsupportedReportError):
        open_report(path, pepper=PEPPER)


def test_header_not_found_in_first_rows(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("\n".join(f"fila {i}" for i in range(30)), encoding="utf-8")
    with pytest.raises(ReportFormatError, match="encabezado"):
        open_report(path, pepper=PEPPER)


def test_empty_and_binary_files_fail_cleanly(tmp_path):
    empty = tmp_path / "e.csv"
    empty.write_bytes(b"")
    with pytest.raises(ReportFormatError):
        open_report(empty, pepper=PEPPER)
    binary = tmp_path / "b.csv"
    binary.write_bytes(bytes(range(256)) * 50)
    with pytest.raises(ReportFormatError):
        open_report(binary, pepper=PEPPER)


# ---- cobros --------------------------------------------------------------------------------------------


def test_paid_payment_record_fields(tmp_path):
    _, stats, records = _read(write_report(tmp_path / "a.csv", "transacciones", [payment_row(7)]))
    r = records[0]
    assert r.charge_external_id == charge_id(7) and r.payment_external_id == uuid_of(7)
    assert r.subscription_external_id == sub_id(7)  # sin el tabulador final
    assert r.charge_status == "pagado" and r.scheduled_date == date(2026, 10, 5)
    assert (r.charge_number, r.charges_total) == (3, 12)
    assert r.amount == Decimal("9990.00") and r.currency == "CLP"
    assert r.response_code is None and r.response_text is None  # el codigo de un pagado es de autorizacion
    assert r.payment_medium == "Débito" and r.card_last4 == "1234"
    assert r.authorized_at == datetime(2026, 10, 5, 9, 30, tzinfo=CHILE)
    assert (r.processing_fee, r.payout_amount) == (Decimal("250.00"), Decimal("9740.00"))
    assert r.payout_date == datetime(2026, 10, 7, 0, 0, tzinfo=CHILE)
    assert r.pos_alias == "TEST_POS_1" and r.subscription_origin == "POS" and r.charge_origin is None
    assert (stats.window_start, stats.window_end) == (date(2026, 10, 5), date(2026, 10, 5))
    assert stats.rows_total == 1 and stats.rows_skipped == 0


def test_rejected_payment_carries_code_and_text(tmp_path):
    rows = [
        rejected_payment_row(1, "-11", "Excede límite de reintentos de rechazo"),
        rejected_payment_row(2, "-2119", "Excede saldo maximo"),
        rejected_payment_row(3, "", ""),
    ]
    _, _, records = _read(write_report(tmp_path / "a.csv", "transacciones", rows))
    assert [(r.response_code, r.response_text) for r in records] == [
        ("-11", "Excede límite de reintentos de rechazo"),
        ("-2119", "Excede saldo maximo"),
        ("", None),
    ]
    assert all(r.charge_status == "rechazado" and r.payment_medium is None and r.card_last4 is None for r in records)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("9990", "9990.00"), ("$9.990", "9990.00"), ("9.990,50", "9990.50"), ("9990.00", "9990.00"), (" 12500 ", "12500.00")],
)
def test_amounts_are_normalized_chilean_format(tmp_path, raw, expected):
    _, _, records = _read(write_report(tmp_path / "a.csv", "transacciones", [payment_row(1, **{"Monto de cargo": raw})]))
    assert records[0].amount == Decimal(expected)


def test_dates_with_and_without_time_and_single_digit_parts(tmp_path):
    row = payment_row(1, **{"Fecha programada de cargo": "5/1/2026", "Fecha de abono": "07/10/2026 14:05:09"})
    _, _, records = _read(write_report(tmp_path / "a.csv", "transacciones", [row]))
    assert records[0].scheduled_date == date(2026, 1, 5)
    assert records[0].payout_date == datetime(2026, 10, 7, 14, 5, 9, tzinfo=CHILE)


def test_card_last4_only_accepts_exactly_four_digits_and_never_a_pan(tmp_path):
    rows = [
        payment_row(1, **{"Final número tarjeta": SENTINEL_PAN}),
        payment_row(2, **{"Final número tarjeta": "123"}),
        payment_row(3, **{"Final número tarjeta": "12ab"}),
        payment_row(4),
    ]
    _, stats, records = _read(write_report(tmp_path / "a.csv", "transacciones", rows))
    assert [r.card_last4 for r in records] == [None, None, None, "1234"]
    assert stats.discarded_card_values == 3
    assert SENTINEL_PAN not in repr(records)


def test_seller_code_is_hashed_never_stored_and_needs_pepper(tmp_path):
    path = write_report(tmp_path / "a.csv", "transacciones", [payment_row(1), payment_row(2, **{"Código de vendedor": "00000002-7"})])
    meta, _, records = _read(path)
    assert len(records[0].seller_code_hash) == 64 and records[0].seller_code_hash == records[1].seller_code_hash  # mismo RUT
    assert SENTINEL_SELLER not in repr(records) and "00000002-7" not in repr(records)
    assert "seller_hash_skipped_no_pepper" not in meta.warnings
    meta2, _, records2 = _read(path, pepper="")
    assert records2[0].seller_code_hash is None and "seller_hash_skipped_no_pepper" in meta2.warnings
    _, _, records3 = _read(path, pepper="otro-pepper")
    assert records3[0].seller_code_hash != records[0].seller_code_hash


def test_invalid_rows_are_skipped_with_reason_codes_without_values(tmp_path):
    rows = [
        payment_row(1),
        payment_row(2, **{"Id cargo": ""}),
        payment_row(3, **{"Fecha programada de cargo": "no-es-fecha"}),
        payment_row(4, **{"Monto de cargo": "abc"}),
        payment_row(1),  # duplicado dentro del archivo
        payment_row(5, **{"Monto de cargo": "12500"}),
    ]
    _, stats, records = _read(write_report(tmp_path / "a.csv", "transacciones", rows))
    assert [r.charge_external_id for r in records] == [charge_id(1), charge_id(5)]
    assert stats.rows_total == 6 and stats.rows_skipped == 4
    assert stats.skip_reasons == {"invalid_id": 1, "invalid_date": 1, "invalid_amount": 1, "duplicate_in_file": 1}


def test_blank_rows_are_ignored_and_pii_never_in_records(tmp_path):
    rows = [payment_row(1), {c: "" for c in COLUMNS["transacciones"]}, rejected_payment_row(2)]
    _, stats, records = _read(write_report(tmp_path / "a.csv", "transacciones", rows))
    assert len(records) == 2 and stats.rows_total == 2
    text = repr(records)
    assert not any(s in text for s in PII_SENTINELS)


def test_free_text_is_redacted_for_rut_email_and_long_digit_runs(tmp_path):
    row = rejected_payment_row(1, "-6", "Rechazo 12.345.678-9 juan@x.cl tarjeta 4111111111111111 fin")
    _, _, records = _read(write_report(tmp_path / "a.csv", "transacciones", [row]))
    text = records[0].response_text
    assert "12.345.678-9" not in text and "juan@x.cl" not in text and "4111111111111111" not in text
    assert text.count("[redacted]") == 3


# ---- suscripciones ---------------------------------------------------------------------------------------


def test_subscription_record_fields(tmp_path):
    rows = [
        subscription_row(1),
        subscription_row(
            2,
            **{
                "Estado de suscripción": "SUSCRIPCION_FALLIDA", "Motivo de rechazo": "Rechazo general",
                "Fecha de cancelación": "15/09/2026 12:00", "Tipo tarjeta": "TC", "Marca": "mastercard",
                "Canal/Origen": "WEB",
            },
        ),
    ]
    _, stats, records = _read(write_report(tmp_path / "s.csv", "suscriptores", rows))
    a, b = records
    assert a.subscription_external_id == sub_id(1) and a.status == "ACTIVA" and a.plan_external_id == "plan-abc"
    assert a.subscribed_at == datetime(2026, 3, 1, 10, 0, tzinfo=CHILE) and a.canceled_at is None
    assert (a.charges_total, a.charges_authorized, a.charges_rejected, a.charges_pending) == (12, 3, 1, 7)
    assert (a.charges_processing, a.charges_canceled) == (0, 1)
    assert (a.card_type, a.card_brand, a.card_last4) == ("TD", "visa", "1234")
    assert a.channel_origin == "POS" and a.pos_alias == "TEST_POS_1" and len(a.seller_code_hash) == 64
    assert a.rejection_reason is None
    assert b.status == "SUSCRIPCION_FALLIDA" and b.rejection_reason == "Rechazo general"
    assert b.canceled_at == datetime(2026, 9, 15, 12, 0, tzinfo=CHILE) and (b.card_type, b.card_brand) == ("TC", "mastercard")
    assert (stats.window_start, stats.window_end) == (date(2026, 3, 1), date(2026, 3, 1))
    assert not any(s in repr(records) for s in PII_SENTINELS)


def test_subscription_without_card_and_invalid_rows(tmp_path):
    rows = [
        subscription_row(1, **{"Tipo tarjeta": "", "Últimos 4 dígitos pan": "", "Marca": ""}),
        subscription_row(2, **{"Id de suscripción": ""}),
        subscription_row(3, **{"Fecha de suscripción": "xx"}),
        subscription_row(1),
    ]
    _, stats, records = _read(write_report(tmp_path / "s.csv", "suscriptores", rows))
    assert len(records) == 1 and (records[0].card_type, records[0].card_last4, records[0].card_brand) == (None, None, None)
    assert stats.skip_reasons == {"invalid_id": 1, "invalid_date": 1, "duplicate_in_file": 1}


# ---- fecha de generacion ---------------------------------------------------------------------------------


def test_generated_at_comes_from_the_epoch_in_the_filename(tmp_path):
    path = write_report(tmp_path / "TransaccionesPAT-VirtualPOS-1792546479.csv", "transacciones")
    meta, _, _ = _read(path, filename=path.name)
    assert meta.generated_at == datetime.fromtimestamp(1792546479, tz=UTC) and not meta.warnings


def test_generated_at_falls_back_to_now_with_warning(tmp_path):
    path = write_report(tmp_path / "sin-fecha.csv", "transacciones")
    fixed = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    meta, _, _ = _read(path, filename=path.name, now=fixed)
    assert meta.generated_at == fixed and "generated_at_fallback_now" in meta.warnings
    meta2, _, _ = _read(path, filename="x-9999999999.csv", now=fixed)  # epoch fuera de rango razonable
    assert meta2.generated_at == fixed and "generated_at_fallback_now" in meta2.warnings


def test_future_epoch_is_rejected_as_generated_at(tmp_path):
    path = write_report(tmp_path / "a.csv", "transacciones")
    future = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    meta, _, _ = _read(path, filename=f"TransaccionesPAT-VirtualPOS-{future}.csv")
    assert "generated_at_fallback_now" in meta.warnings


def test_module_exposes_types():
    assert vp.REPORT_TYPES == ("transacciones", "suscriptores")
