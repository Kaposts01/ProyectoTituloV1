"""EXP-01: servicio comun de exportacion CSV (streaming, BOM, anti-formulas, PII, auditoria)."""

import csv
import io
import uuid

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.write_run import WriteRun
from app.services.exporter import (
    BOM,
    ExportColumn,
    audit_payload,
    csv_safe,
    csv_stream,
    record_export_audit,
)

COLUMNS = (
    ExportColumn("canal", "canal"),
    ExportColumn("id", "id"),
    ExportColumn("rut", "rut_cliente", pii=True),
    ExportColumn("email", "correo", pii=True),
)


def _rows(n: int, counter: list[int] | None = None):
    for i in range(n):
        if counter is not None:
            counter[0] += 1
        yield {"canal": "tch", "id": f"id-{i}", "rut": "11111111-1", "email": "a@example.test"}


def _decode(chunks) -> list[list[str]]:
    data = b"".join(chunks)
    assert data.startswith(BOM)
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def test_csv_safe_neutralizes_formulas_and_keeps_other_values() -> None:
    for risky in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert csv_safe(risky) == "'" + risky
    assert csv_safe("normal") == "normal" and csv_safe("") == "" and csv_safe(None) is None and csv_safe(7) == 7


def test_stream_has_bom_header_and_excludes_pii_columns_without_permission() -> None:
    masked = _decode(csv_stream(COLUMNS, False, _rows(2)))
    assert masked[0] == ["canal", "id"] and len(masked) == 3
    assert "11111111-1" not in str(masked) and "example.test" not in str(masked)
    full = _decode(csv_stream(COLUMNS, True, _rows(2)))
    assert full[0] == ["canal", "id", "rut_cliente", "correo"] and full[1][2] == "11.111.111-1"


def test_stream_neutralizes_formulas_in_cells() -> None:
    rows = iter([{"canal": "tch", "id": "=cmd|' /C calc'!A0", "rut": "@x", "email": "-y"}])
    out = _decode(csv_stream(COLUMNS, True, rows))
    assert out[1] == ["tch", "'=cmd|' /C calc'!A0", "'@x", "'-y"]


def test_stream_is_lazy_and_chunked() -> None:
    counter = [0]
    gen = csv_stream(COLUMNS, False, _rows(10_000, counter), chunk_rows=100)
    first = next(gen)  # BOM + cabecera + primer trozo
    assert first.startswith(BOM)
    assert counter[0] <= 101, "el generador no debe consumir toda la fuente para entregar el primer trozo"
    chunks = [first, *gen]
    assert len(chunks) > 50
    assert counter[0] == 10_000


def test_on_finish_reports_count_and_completion_and_abort() -> None:
    seen: list[tuple[int, bool]] = []
    b"".join(csv_stream(COLUMNS, False, _rows(250), chunk_rows=100, on_finish=lambda n, ok: seen.append((n, ok))))
    assert seen == [(250, True)]
    seen.clear()
    gen = csv_stream(COLUMNS, False, _rows(1000), chunk_rows=100, on_finish=lambda n, ok: seen.append((n, ok)))
    next(gen)
    gen.close()  # el cliente corta la descarga
    assert len(seen) == 1 and seen[0][1] is False and 0 < seen[0][0] < 1000


def test_empty_result_still_has_bom_and_header() -> None:
    assert _decode(csv_stream(COLUMNS, False, iter(()))) == [["canal", "id"]]


def test_audit_payload_has_no_content_and_records_pii_flag() -> None:
    class U:
        id = uuid.uuid4()
        username = "audit-user"

    payload = audit_payload(U(), "export/cobros", {"canal": "tch"}, 12, True)
    assert payload == {
        "user_id": str(U.id), "username": "audit-user", "endpoint": "export/cobros",
        "filters": {"canal": "tch"}, "rows": 12, "pii_included": True,
    }


def test_record_export_audit_writes_write_run() -> None:
    suffix = uuid.uuid4().hex[:8]

    class U:
        id = None
        username = f"exp01-{suffix}"

    db = SessionLocal()
    try:
        record_export_audit(db, U(), f"export/test-{suffix}", {"a": 1}, 5, False, source="export", resource_type="cobros", status="aborted")
        run = db.scalars(select(WriteRun).where(WriteRun.external_id == f"export/test-{suffix}")).one()
        assert run.operation == "export_csv" and run.status == "aborted" and run.started_at is not None
        assert run.request_payload["rows"] == 5 and run.request_payload["pii_included"] is False
    finally:
        # record_export_audit confirma la fila: se borra para no dejarla a los tests que revisan toda write_runs.
        db.rollback()
        db.execute(delete(WriteRun).where(WriteRun.external_id == f"export/test-{suffix}"))
        db.commit()
        db.close()


def test_qa08_el_rut_sale_con_formato_unico_es_cl():
    """QA-08: el CSV lleva el RUT como la interfaz (12.345.678-9), venga con o sin puntos y guion."""
    from app.services.exporter import format_rut

    assert format_rut("197292059") == "19.729.205-9"
    assert format_rut("19780113-1") == "19.780.113-1"
    assert format_rut("42.000.150-9") == "42.000.150-9"
    assert format_rut("7654321k") == "7.654.321-K"
    assert format_rut("2222F3K92") == "2222F3K92"  # sin forma de RUT: tal cual
    assert format_rut(None) is None and format_rut("") == ""
