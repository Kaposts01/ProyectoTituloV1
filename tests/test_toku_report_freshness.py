"""TK-19 / TK-PAR-02 / DEC-21: aviso de dato con mas de 7 dias y GET de estado del panel de carga. Fixtures sinteticas."""

from datetime import UTC, datetime, timedelta

from billing_requests_support import client_for
from toku_reports_support import write_report

from app.services import toku_report_import as imp
from tests.test_toku_report_routes import (  # noqa: F401  (fixtures)
    db_session,
    env,
    world,
)

STATUS_URL = "/api/v1/imports/toku-reports/status"


def test_age_helpers() -> None:
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    assert imp.REPORT_MAX_AGE_DAYS == 7
    assert imp.is_older_than_max_age(now - timedelta(days=7, minutes=1), now)
    assert not imp.is_older_than_max_age(now - timedelta(days=7), now)
    assert not imp.is_older_than_max_age(None, now)
    assert imp.data_age_days(now - timedelta(days=9, hours=3), now) == 9
    assert imp.data_age_days(None, now) is None


def test_upload_of_old_data_warns_distinct_from_stale_report(world, tmp_path) -> None:  # noqa: F811
    old = (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    r = world.post("admin", write_report(tmp_path / "Productos.xlsx", "productos", generated=old))
    assert r.status_code == 200
    body = r.json()
    assert "data_older_than_max_age" in body["warnings"] and "stale_report" not in body["warnings"]
    assert body["data_age_days"] >= 19


def test_fresh_upload_has_no_age_warning(world, tmp_path) -> None:  # noqa: F811
    fresh = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    r = world.post("admin", write_report(tmp_path / "Clientes.xlsx", "clientes", generated=fresh))
    assert r.status_code == 200 and "data_older_than_max_age" not in r.json()["warnings"]


def test_status_lists_latest_per_type_with_stale_flag(world, tmp_path) -> None:  # noqa: F811
    old = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    assert world.post("admin", write_report(tmp_path / "a.xlsx", "deudas", generated=old)).status_code == 200
    assert world.post("admin", write_report(tmp_path / "b.xlsx", "pagos", generated=fresh)).status_code == 200
    client, headers = client_for(world.db, world.admin)
    r = client.get(STATUS_URL, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["max_age_days"] == 7
    by_type = {row["report_type"]: row for row in body["reports"]}
    assert by_type["deudas"]["is_stale"] is True and by_type["pagos"]["is_stale"] is False
    assert "deudas" in body["stale_types"] and "pagos" not in body["stale_types"]
    assert set(by_type["pagos"]) == {"report_type", "generated_at", "loaded_at", "rows_total", "age_days", "is_stale",
                                     "filename", "result"}  # L7-IMPORT: nombre (sin ruta) y resultado


def test_status_requires_the_import_permission(world) -> None:  # noqa: F811
    for who in ("soporte", "ejecutivo", "jefatura", "coordinador"):
        client, headers = client_for(world.db, getattr(world, who))
        assert client.get(STATUS_URL, headers=headers).status_code == 403, who
