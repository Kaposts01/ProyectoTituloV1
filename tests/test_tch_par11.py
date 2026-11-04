"""TCH-PAR-11: registro de archivos TCH cargados (fecha, sha256, mes, filas, resultado) y su endpoint.

Excel SINTETICO de `tests/tch_layouts.py`; todo en una transaccion con rollback salvo el usuario de la prueba de
permisos (igual que tests/test_tch_import.py).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes import tch
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.auth import Role, User
from app.models.tch import TchFileLoad
from app.services import tch_report_registry as registry
from scripts import etl_tch
from tests.tch_layouts import layout_a

PERSONAL_KEYS = {"rut", "nombre", "apellido", "email", "telefono", "direccion", "cliente_rut", "numero_cuenta"}


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class _NoClose:
        def __getattr__(self, name):
            return getattr(session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(tch, "_get_db", lambda: _NoClose())
    monkeypatch.setattr(etl_tch, "SessionLocal", lambda: _NoClose())
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


def _sha() -> str:
    return uuid.uuid4().hex * 2


def test_a_failed_attempt_does_not_block_retrying_the_same_content(db_session) -> None:
    sha = _sha()
    registry.register_failure(db_session, sha, "a.xlsx", 10, "La carga fallo (ValueError).", report_period="2026-09")
    assert not registry.is_registered(db_session, sha)
    assert sha not in registry.consolidation_snapshot(db_session)["sha256s"]

    registry.register(db_session, sha, "a.xlsx", 10, rows_loaded=7, report_period="2026-09")
    load = db_session.get(TchFileLoad, sha)
    db_session.refresh(load)
    assert (load.result, load.rows_loaded, load.error_message) == ("cargado", 7, None)
    assert registry.is_registered(db_session, sha)


def test_a_failure_never_overwrites_a_successful_load(db_session) -> None:
    sha = _sha()
    registry.register(db_session, sha, "a.xlsx", 10, rows_loaded=7)
    registry.register_failure(db_session, sha, "a.xlsx", 10, "La carga fallo (ValueError).")
    load = db_session.get(TchFileLoad, sha)
    db_session.refresh(load)
    assert (load.result, load.rows_loaded) == ("cargado", 7)


def test_import_records_name_month_rows_and_run(db_session, tmp_path) -> None:
    upload = layout_a(tmp_path, name="synkmetrix-tch-temporal.xlsx")  # la subida se guarda con nombre temporal
    sha = registry.file_sha256(upload)

    total = etl_tch.import_incremental_file(upload, display_name="12 - TCH IG DICIEMBRE 2024.xlsx")

    load = db_session.get(TchFileLoad, sha)
    assert load is not None
    assert load.file_name == "12 - TCH IG DICIEMBRE 2024.xlsx"
    assert (load.report_period, load.rows_loaded, load.result) == ("2024-12", total, "cargado")
    assert load.etl_run_id is not None


def test_a_failed_import_is_recorded_without_report_content(db_session, tmp_path, monkeypatch) -> None:
    upload = layout_a(tmp_path)
    sha = registry.file_sha256(upload)

    def broken(*_args, **_kwargs):
        raise ValueError("ficha 961001 socio 12345678-5 sin monto")

    original = etl_tch._process_file
    monkeypatch.setattr(etl_tch, "_process_file", broken)
    with pytest.raises(ValueError):
        etl_tch.import_incremental_file(upload, display_name=upload.name)

    load = db_session.get(TchFileLoad, sha)
    assert load is not None and load.result == "fallido"
    assert "ValueError" in load.error_message
    assert "961001" not in load.error_message and "12345678" not in load.error_message
    assert not registry.is_registered(db_session, sha)

    monkeypatch.setattr(etl_tch, "_process_file", original)
    etl_tch.import_incremental_file(upload, display_name=upload.name)  # el reintento si se permite
    db_session.refresh(load)
    assert load.result == "cargado"


def test_a_duplicate_upload_does_not_touch_the_original_record(db_session, tmp_path) -> None:
    upload = layout_a(tmp_path)
    etl_tch.import_incremental_file(upload, display_name=upload.name)
    sha = registry.file_sha256(upload)
    with pytest.raises(etl_tch.ReportAlreadyLoadedError):
        etl_tch.import_incremental_file(upload, display_name="otro nombre.xlsx")
    load = db_session.get(TchFileLoad, sha)
    db_session.refresh(load)
    assert (load.result, load.file_name) == ("cargado", upload.name)


def test_registry_name_never_keeps_a_rut_or_email() -> None:
    assert etl_tch._registry_file_name(etl_tch.Path("x.xlsx"), "reporte 12.345.678-5.xlsx") == "[nombre omitido].xlsx"
    assert etl_tch._registry_file_name(etl_tch.Path("x.xlsx"), "C:\\carpeta\\ENERO 2026.xlsx").endswith("ENERO 2026.xlsx")


def test_endpoint_lists_files_with_result_and_no_personal_data(db_session) -> None:
    loaded, consolidated, failed = _sha(), _sha(), _sha()
    registry.register(db_session, consolidated, "nov.xlsx", 10, rows_loaded=3, report_period="2026-11")
    registry.mark_consolidated(db_session, {"sha256s": [consolidated], "latest_load_at": None})
    registry.register(db_session, loaded, "dic.xlsx", 20, rows_loaded=5, report_period="2026-12")
    registry.register_failure(db_session, failed, "malo.xlsx", 5, "La carga fallo (ValueError).")

    body = tch.list_report_files(limit=200)
    items = {item["sha256"]: item for item in body["items"]}
    assert items[loaded]["resultado"] == "cargado"
    assert items[consolidated]["resultado"] == "consolidado"
    assert items[failed]["resultado"] == "fallido"
    assert items[loaded]["filas"] == 5 and items[loaded]["periodo"] == "2026-12"
    assert items[loaded]["cargado_en"] is not None
    for item in body["items"]:
        assert not (set(item) & PERSONAL_KEYS)


def test_endpoint_requires_the_sync_runs_permission(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    username = f"tch-files-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"}).status_code == 200
    assert client.get("/api/v1/tch/archivos").status_code == 403


def test_endpoint_rejects_anonymous_requests() -> None:
    assert TestClient(app).get("/api/v1/tch/archivos").status_code == 401


def test_list_is_newest_first(db_session) -> None:
    first, second = _sha(), _sha()
    registry.register(db_session, first, "a.xlsx", 1)
    db_session.execute(
        TchFileLoad.__table__.update().where(TchFileLoad.file_sha256 == first).values(loaded_at=registry.datetime(2020, 1, 1, tzinfo=registry.UTC))
    )
    registry.register(db_session, second, "b.xlsx", 1)
    order = [load.file_sha256 for load in registry.list_loads(db_session, 200) if load.file_sha256 in {first, second}]
    assert order == [second, first]


# --- TCH-PAR-11 (resto): conciliacion por archivo ------------------------------------------------------------------


def test_import_records_row_counts_and_control_check_per_file(db_session, tmp_path) -> None:
    upload = layout_a(tmp_path)
    sha = registry.file_sha256(upload)
    etl_tch.import_incremental_file(upload, display_name=upload.name)

    item = next(i for i in tch.list_report_files(limit=200)["items"] if i["sha256"] == sha)
    rows, control = item["conciliacion"]["filas"], item["conciliacion"]["control"]
    # 4 fichas leidas (2 VIGENTES, 1 ELIMINADOS, 1 RECHAZADOS), todas nuevas.
    assert rows["suscripciones"] == {"leidas": 4, "insertadas": 4, "actualizadas": 0, "omitidas": 0, "con_error": 0}
    cuotas = rows["cuotas"]
    assert cuotas["insertadas"] > 0 and cuotas["actualizadas"] == 0
    # La cuota 6 de dic de la ficha 961001 viene en el historial y en ambas hojas CARGOS: queda una sola fila.
    assert cuotas["omitidas"] == cuotas["leidas"] - cuotas["insertadas"] >= 2
    assert rows["total"]["leidas"] == rows["suscripciones"]["leidas"] + cuotas["leidas"]
    # Control del propio Excel para dic-2024: 2 aceptadas y 0 rechazadas, igual que el detalle del archivo.
    assert control["periodo"] == "2024-12"
    assert (control["archivo_aceptadas"], control["archivo_rechazadas"]) == (2, 0)
    assert (control["control_aceptadas"], control["control_rechazadas"]) == (2, 0)
    assert control["cuadra"] is True
    assert "961001" not in str(item["conciliacion"]) and "@" not in str(item["conciliacion"])


def test_reloading_the_same_rows_counts_updates_not_inserts(db_session, tmp_path) -> None:
    upload = layout_a(tmp_path)
    etl_tch.import_incremental_file(upload, display_name=upload.name)
    # Segunda pasada sobre los mismos datos (como una recarga): todo es actualizacion.
    totals = etl_tch._process_file(upload, db_session)
    rows = totals["conciliacion"]["filas"]
    assert rows["suscripciones"]["insertadas"] == 0 and rows["suscripciones"]["actualizadas"] == 4
    assert rows["cuotas"]["insertadas"] == 0 and rows["cuotas"]["actualizadas"] > 0


def _control_check(rows, controls, period="2026-09"):
    return etl_tch.file_reconciliation(
        read={"suscripciones": 0, "cuotas_cargos": len(rows)}, history_rows=0, subscriptions=(0, 0, 0),
        transactions={"insertadas": len(rows), "actualizadas": 0}, transaction_rows=rows, control_rows=controls,
        period=period,
    )["control"]


def _tx(key: str, status: str, period: str = "2026-09") -> dict:
    return {"dedupe_key": key, "estado": status, "periodo": period}


def test_control_check_flags_a_file_that_does_not_match_its_own_control() -> None:
    control = [{"periodo": "2026-09", "aceptadas_cantidad": 3, "rechazadas_cantidad": 1}]
    rows = [_tx("1|2026-09|1", "ACEPTADA"), _tx("2|2026-09|1", "ACEPTADA"), _tx("3|2026-09|1", "RECHAZADA")]
    check = _control_check(rows, control)
    assert check["cuadra"] is False
    assert (check["archivo_aceptadas"], check["control_aceptadas"]) == (2, 3)

    rows.append(_tx("4|2026-09|1", "ACEPTADA"))
    assert _control_check(rows, control)["cuadra"] is True


def test_control_check_uses_the_final_state_of_each_installment_and_only_the_report_month() -> None:
    control = [{"periodo": "2026-09", "aceptadas_cantidad": 1, "rechazadas_cantidad": 0}]
    rows = [_tx("1|2026-09|1", "RECHAZADA"), _tx("1|2026-09|1", "ACEPTADA"), _tx("2|2026-08|1", "RECHAZADA", "2026-08")]
    check = _control_check(rows, control)
    assert (check["archivo_aceptadas"], check["archivo_rechazadas"], check["cuadra"]) == (1, 0, True)


def test_control_check_is_null_without_a_control_row_for_the_month() -> None:
    one = [_tx("1|2026-09|1", "ACEPTADA")]
    assert _control_check(one, [])["cuadra"] is None
    control = [{"periodo": "2026-09", "aceptadas_cantidad": 1, "rechazadas_cantidad": 0}]
    assert _control_check(one, control, period=None)["cuadra"] is None


def test_stats_keep_only_counts_and_are_cleared_with_the_registry(db_session) -> None:
    sha = _sha()
    stats = {"filas": {"total": {"leidas": 3}}, "control": {"cuadra": None, "x": 1.5}}
    registry.register(db_session, sha, "a.xlsx", 1, stats=stats)
    stored = registry.stats_by_sha(db_session, [sha])[sha]
    assert stored["filas"]["total"]["leidas"] == 3 and stored["control"] == {"cuadra": None, "x": "1.5"}
    registry.clear(db_session)
    assert registry.stats_by_sha(db_session, [sha]) == {}


def test_a_file_without_stats_lists_null_reconciliation(db_session) -> None:
    sha = _sha()
    registry.register(db_session, sha, "viejo.xlsx", 1, rows_loaded=2)
    item = next(i for i in tch.list_report_files(limit=200)["items"] if i["sha256"] == sha)
    assert item["conciliacion"] is None
