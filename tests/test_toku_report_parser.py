"""TK-18: parser de reportes de Toku. Solo fixtures sinteticas generadas por `toku_reports_support`."""

import dataclasses
import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from toku_reports_support import (
    PEPPER,
    PII_SENTINELS,
    SENTINEL_DUP_PM,
    SENTINEL_EXTRA,
    SENTINEL_MAIL,
    SENTINEL_NAME,
    default_row,
    product_text,
    write_report,
    write_unsupported,
)

from app.services import toku_report_parser as parser
from app.services.toku_report_parser import (
    MissingPepperError,
    ReportFormatError,
    UnsupportedReportError,
    hash_product_key,
    map_catalog_severity,
    open_report,
    read_response_catalog,
)


def _read(path, severity=None):
    with open_report(path, pepper=PEPPER, severity_lookup=severity) as rep:
        return rep.meta, list(rep.records()), rep.stats


# ---- estructura / metadatos -------------------------------------------------------------------


def test_title_block_and_header_in_row_7(tmp_path):
    path = write_report(tmp_path / "a.xlsx", "productos")
    meta, records, stats = _read(path)
    assert meta.report_type == "productos"
    assert meta.generated_at.date() == date(2026, 10, 20) and meta.generated_at.hour == 10
    assert meta.window_start == date(2026, 1, 1) and meta.window_end == date(2026, 10, 20)
    assert meta.warnings == ()
    assert len(records) == 3 and stats.rows_total == 3 and stats.rows_skipped == 0


def test_header_in_row_1_without_title_uses_now_and_warns(tmp_path):
    path = write_report(tmp_path / "payment_method_inscription_intent_x.xlsx", "inscripciones", with_title=False)
    now = datetime(2026, 11, 1, 9, 0).astimezone()
    with open_report(path, pepper=PEPPER, now=now) as rep:
        assert rep.meta.report_type == "inscripciones"
        assert rep.meta.generated_at == now
        assert "generated_at_fallback_now" in rep.meta.warnings
        assert rep.meta.window_start is None
        assert len(list(rep.records())) == 3


def test_title_without_readable_date_falls_back(tmp_path):
    path = write_report(tmp_path / "a.xlsx", "deudas", generated=None)
    meta, _, _ = _read(path)
    assert "generated_at_fallback_now" in meta.warnings


@pytest.mark.parametrize(
    ("report_type", "title"),
    [
        ("intentos", "Intentos de cobro"), ("intentos", "Intentos de pago"), ("productos", "Suscripciones"),
        ("productos", "Productos"), ("deudas", "Cualquier cosa"),
    ],
)  # fmt: skip
def test_detection_by_signature_not_title(tmp_path, report_type, title):
    path = write_report(tmp_path / "nombre_engañoso_clientes.xlsx", report_type, title=title)
    meta, _, _ = _read(path)
    assert meta.report_type == report_type


@pytest.mark.parametrize("report_type", ["productos", "medios_pago", "intentos", "deudas", "inscripciones"])
def test_detects_every_supported_type(tmp_path, report_type):
    meta, records, _ = _read(write_report(tmp_path / "a.xlsx", report_type))
    assert meta.report_type == report_type and len(records) == 3


def test_missing_columns_lists_names_only(tmp_path):
    path = write_report(tmp_path / "a.xlsx", "intentos", drop_columns=("Deuda", "ID Mandato"))
    with pytest.raises(ReportFormatError) as exc:
        open_report(path, pepper=PEPPER)
    msg = str(exc.value).casefold()
    assert "deuda" in msg and "id mandato" in msg and "intentos" in msg
    assert not any(s.casefold() in msg for s in PII_SENTINELS) and "cus_t" not in msg


def test_unsupported_report_type_without_echo(tmp_path):
    path = write_unsupported(tmp_path / "c.xlsx")
    with pytest.raises(UnsupportedReportError) as exc:
        open_report(path, pepper=PEPPER)
    assert "no soportado" in str(exc.value)
    assert SENTINEL_NAME not in str(exc.value)


def test_not_an_xlsx_is_a_format_error(tmp_path):
    bad = tmp_path / "x.xlsx"
    bad.write_bytes(b"no soy un zip")
    with pytest.raises(ReportFormatError):
        open_report(bad, pepper=PEPPER)


def test_no_header_found(tmp_path):
    path = write_report(tmp_path / "a.xlsx", "productos", columns=["Cliente", "Monto"], rows=[{}])
    with pytest.raises(ReportFormatError, match="encabezado"):
        open_report(path, pepper=PEPPER)


def test_extra_columns_reported_by_name_only(tmp_path):
    path = write_report(tmp_path / "a.xlsx", "productos", extra_columns={"columna_nueva": SENTINEL_EXTRA})
    meta, records, _ = _read(path)
    assert "columna_nueva" in meta.extra_columns
    assert SENTINEL_EXTRA not in repr(records)
    # las columnas personales tampoco son «requeridas»: aparecen como extras por nombre, nunca como valores
    assert SENTINEL_NAME not in repr((meta, records))


def test_duplicate_medio_de_pago_is_read_by_position(tmp_path):
    _, records, _ = _read(write_report(tmp_path / "a.xlsx", "inscripciones", n_rows=1))
    assert records[0].payment_method_external_id == "pm_T0001"
    assert SENTINEL_DUP_PM not in repr(records)


# ---- normalizacion ----------------------------------------------------------------------------


def test_debts_use_dd_mm_yyyy_and_booleans(tmp_path):
    rows = [default_row("deudas", 1, **{"Fecha de Vencimiento": "31/12/2026", "Pagado": "true", "Anulado": None})]
    _, (debt,), _ = _read(write_report(tmp_path / "a.xlsx", "deudas", rows))
    assert debt.due_date == date(2026, 12, 31) and debt.paid is True and debt.voided is False
    assert debt.amount == Decimal("10000.00")


def test_iso_dates_and_real_excel_datetimes(tmp_path):
    rows = [default_row("intentos", 1, **{"Fecha de Vencimiento": datetime(2026, 3, 4),  # noqa: DTZ001 - Excel no admite zonas
         "Fecha de Transacción": "2026-03-04T12:30:00Z"})]
    _, (att,), _ = _read(write_report(tmp_path / "a.xlsx", "intentos", rows))
    assert att.due_date == date(2026, 3, 4)
    assert att.attempted_at.isoformat().startswith("2026-03-04T12:30:00")


def test_products_estado_is_payment_method_status(tmp_path):
    rows = [default_row("productos", 1, Estado="temporary_failed", **{"Fecha de Eliminación": "2026-05-01"})]
    _, (prod,), _ = _read(write_report(tmp_path / "a.xlsx", "productos", rows))
    assert prod.payment_method_status == "temporary_failed"
    assert prod.deleted_at_source is not None and prod.subscription_external_id == "sub_T0001"
    assert prod.amount == Decimal("10000.00") and prod.due_day == 5 and prod.is_recurring is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(10000, "10000.00"), ("10.000", "10000.00"), ("$ 1.234,50", "1234.50"), ("1234,5", "1234.50"), ("12.5", "12.50")],
)  # fmt: skip
def test_amount_parsing(raw, expected):
    assert parser.parse_amount(raw) == Decimal(expected)


def test_invalid_rows_are_counted_with_reason_codes(tmp_path):
    rows = [
        default_row("deudas", 1),
        default_row("deudas", 2, **{"Fecha de Vencimiento": "no-fecha"}),
        default_row("deudas", 3, Monto="abc"),
        default_row("deudas", 4, ID="xx_1"),
        default_row("deudas", 5, Pagado="quizas"),
        default_row("deudas", 1),  # duplicado
    ]
    _, records, stats = _read(write_report(tmp_path / "a.xlsx", "deudas", rows))
    assert len(records) == 1 and stats.rows_total == 6 and stats.rows_skipped == 5
    assert stats.skip_reasons == {
        "invalid_due_date": 1, "invalid_amount": 1, "invalid_id": 1, "invalid_bool": 1, "duplicate_in_file": 1,
    }  # fmt: skip


# ---- gravedad ---------------------------------------------------------------------------------


def test_severity_by_catalog_and_unknown_code(tmp_path):
    rows = [
        default_row("intentos", 1, **{"Código de Respuesta Toku": "1001"}),
        default_row("intentos", 2, **{"Código de Respuesta Toku": "4242"}),
        default_row("intentos", 3, **{"Código de Respuesta Toku": None}),
    ]
    path = write_report(tmp_path / "a.xlsx", "intentos", rows)
    catalog, cstats = read_response_catalog(path)
    lookup = {c.code: c.severity for c in catalog}
    assert lookup == {"0000": "SU", "1001": "TE", "1019": "PE", "9999": "UE"} and cstats.rows_skipped == 0
    _, records, _ = _read(path, lookup)
    assert [r.severity for r in records] == ["TE", "UNKNOWN", None]
    assert records[0].response_code == "1001" and records[0].has_mandate is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SU", "SU"), ("te", "TE"), ("PE - Permanente", "PE"), ("UE", "UE"), ("Éxito", "SU"),
        ("Error temporal", "TE"), ("Temporal", "TE"), ("Error permanente", "PE"), ("Permanente", "PE"),
        ("Error desconocido", "UE"), ("Success", "SU"), ("???", None), (None, None), ("", None),
    ],
)  # fmt: skip
def test_catalog_severity_mapping(raw, expected):
    assert map_catalog_severity(raw) == expected


def test_catalog_unmapped_severity_is_skipped(tmp_path):
    catalog = [("Código Toku", "Gravedad", "Mensaje", "Descripción"), ("1234", "???", "x", None), ("1001", "TE", "ok", None)]
    path = write_report(tmp_path / "a.xlsx", "intentos", catalog=catalog)
    records, stats = read_response_catalog(path)
    assert [r.code for r in records] == ["1001"] and stats.skip_reasons == {"unmapped_severity": 1}


def test_long_code_regex_severity(tmp_path):
    rows = [
        default_row("inscripciones", 1, **{"Código de Respuesta": "SUABC0000"}),
        default_row("inscripciones", 2, **{"Código de Respuesta": "PEXYZ2044"}),
        default_row("inscripciones", 3, **{"Código de Respuesta": "texto libre con sentinela"}),
        default_row("inscripciones", 4, **{"Código de Respuesta": None}),
    ]
    _, records, _ = _read(write_report(tmp_path / "a.xlsx", "inscripciones", rows))
    assert [r.severity for r in records] == ["SU", "PE", "UNKNOWN", None]
    assert [r.response_code_full for r in records] == ["SUABC0000", "PEXYZ2044", None, None]
    assert parser.LONG_CODE_RE.pattern == r"^(SU|TE|PE|UE)([A-Z]{3})(\d{4})$"


# ---- hash de producto ------------------------------------------------------------------------


def test_hash_is_deterministic_normalized_and_pepper_dependent():
    h = hash_product_key(product_text(1), PEPPER)
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert h == hash_product_key(product_text(1), PEPPER)
    assert h == hash_product_key("  " + product_text(1).upper().replace(" ", "   ") + " ", PEPPER)
    assert h != hash_product_key(product_text(2), PEPPER)
    assert h != hash_product_key(product_text(1), "otro-pepper")
    assert hash_product_key("", PEPPER) == "" and hash_product_key(None, PEPPER) == ""


def test_hash_requires_pepper(tmp_path):
    with pytest.raises(MissingPepperError, match="falta TOKU_REPORT_HASH_PEPPER"):
        hash_product_key("x", "")
    with pytest.raises(MissingPepperError, match="falta TOKU_REPORT_HASH_PEPPER"):
        open_report(write_report(tmp_path / "a.xlsx", "productos"), pepper="")


def test_records_have_no_personal_fields_and_no_plain_product_text(tmp_path):
    forbidden = {"name", "nombre", "mail", "email", "phone", "celular", "rut", "external_id", "card", "token", "bin", "account", "mandate_id", "product_text", "id_producto"}  # fmt: skip
    for report_type in ("productos", "medios_pago", "intentos", "deudas", "inscripciones"):
        meta, records, _ = _read(write_report(tmp_path / f"{report_type}.xlsx", report_type))
        assert records, report_type
        names = {f.name for f in dataclasses.fields(records[0])}
        assert not (names & forbidden), (report_type, names & forbidden)
        assert dataclasses.is_dataclass(records[0]) and records[0].__dataclass_params__.frozen
        blob = repr(records) + repr(meta)
        for s in (*PII_SENTINELS, "Donación", "00000001-K"):
            assert s not in blob, (report_type, s)
        assert SENTINEL_MAIL not in blob
