"""d143 (L6-GLOSAS): motivo de rechazo SIEMPRE en texto legible en Cobros, su exportacion y las fichas. Datos SINTETICOS.

Prioridad: glosa del reporte de la plataforma > glosa de la API > catalogo > «Motivo no informado (código X)».
"""

import hashlib
import random
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import CoreCharge
from app.models.crm import Charge
from app.models.tch import TchTransaction
from app.models.vp_report import VpReportFile, VpReportPayment
from app.services.export_queries import ExportFilters, iter_rows, select_specs
from app.services.rbac import seed_permissions
from app.services.rejection_format import rejection_text

_TAG = "zg[0-9a-f]{8}"
NOW = datetime(2026, 11, 4, tzinfo=UTC)


def _sfx() -> str:
    return "zg" + "".join(random.choice("0123456789abcdef") for _ in range(8))


# ----------------------------------------------------------------------------- prioridad (sin base de datos)


def test_report_glosa_wins_over_api_and_catalog() -> None:
    assert rejection_text("virtualpos1", "-3", report_reason="Excede monto máximo", api_reason="Rechazo general") == (
        "Excede monto máximo (código -3)"
    )


def test_api_glosa_wins_over_catalog_when_no_report() -> None:
    assert rejection_text("virtualpos2", "-8", api_reason="Tarjeta vencida en el emisor") == (
        "Tarjeta vencida en el emisor (código -8)"
    )


def test_catalog_translates_code_without_glosa() -> None:
    assert rejection_text("virtualpos1", "-11") == "Excede límite de reintentos de rechazo (código -11)"
    assert rejection_text("toku", "TEPSP2070") == "Excede límite de reintentos (código TEPSP2070)"


def test_toku_report_code_sheet_then_processor_glosa_in_sentence_case() -> None:
    # La hoja oficial de codigos del reporte «Intentos de pago» es la glosa del reporte de Toku.
    assert rejection_text("toku", "PEPSP1019", api_reason="[78] BLOQUEADA / PRIMER USO") == "Tarjeta bloqueada (código PEPSP1019)"
    # Codigo fuera de la hoja: la glosa de la API, sin fecha/hora ni ISO y legible.
    assert rejection_text("toku", "ISO:51", api_reason="[51] EXCEDE LÍMITE DE INTENTOS EL 01-10-2025 A LAS 07:33") == (
        "Excede límite de intentos (código ISO:51)"
    )


def test_payku_gateway_and_subscription_status_are_text() -> None:
    assert rejection_text("payku", None, api_reason="Excede cupo máximo mensual.") == "Excede el cupo máximo mensual"
    assert rejection_text("payku", None, api_reason="maximum attempt limit") == "Se agotaron los reintentos de cobro"


def test_fallback_never_invents_a_glosa() -> None:
    # d120: -2119 no tiene glosa documentada; sin glosa del proveedor no se inventa.
    assert rejection_text("virtualpos1", "-2119") == "Motivo no informado (código -2119)"
    assert rejection_text("toku", "TEPSP7777", api_reason="TEPSP7777") == "Motivo no informado (código TEPSP7777)"
    assert rejection_text("tch", None) == "Motivo no informado"
    assert rejection_text("payku", None, api_reason="   ") == "Motivo no informado"


def test_not_rejected_without_data_is_empty() -> None:
    assert rejection_text("virtualpos1", None, rejected=False) is None
    assert rejection_text("toku", "TEPSP1008", rejected=False) == "Tarjeta rechazada (código TEPSP1008)"


# ----------------------------------------------------------------------------- API unificada, exportacion y ficha


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=f"glo-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"glo-{suffix}", password_hash=hash_password("Pw-glo-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"glo-{suffix}", "password": "Pw-glo-12345"}).status_code == 200
    return client


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^glo-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^glo-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^glo-' || :tag)",
            "DELETE FROM vp_report_payments WHERE charge_external_id ~ :tag",
            "DELETE FROM vp_report_files WHERE filename ~ :tag",
            "DELETE FROM core_charges WHERE external_id ~ :tag",
            "DELETE FROM charges WHERE external_id ~ :tag",
            "DELETE FROM tch_transacciones WHERE dedupe_key ~ :tag",
        ):
            db.execute(text(stmt), params)
        db.commit()
    finally:
        db.close()


def _seed(sfx: str, file_number: int) -> None:
    db = SessionLocal()
    try:
        def charge(source: str, key: str, status: str) -> Charge:
            return Charge(source=source, external_id=f"{key}-{sfx}", status=status, charge_date="2011-08-02",
                          amount="1000", currency="CLP")

        db.add_all([
            charge("virtualpos1", "rep", "rechazado"),   # reporte + API + codigo: manda el reporte
            charge("virtualpos1", "api", "rechazado"),   # API + codigo
            charge("virtualpos1", "cat", "rechazado"),   # solo codigo documentado
            charge("virtualpos1", "unk", "rechazado"),   # codigo sin glosa documentada
            charge("virtualpos1", "nada", "rechazado"),  # nada
            charge("virtualpos1", "ok", "pagado"),       # no es rechazo
            charge("toku", "tk", "UNPAID"),              # deuda de Toku con intento fallido
            CoreCharge(source="virtualpos1", external_id=f"rep-{sfx}", latest_rejection_code="-6",
                       latest_rejection_reason="Rechazo general"),
            CoreCharge(source="virtualpos1", external_id=f"api-{sfx}", latest_rejection_code="-3",
                       latest_rejection_reason="Excede monto máximo"),
            CoreCharge(source="virtualpos1", external_id=f"cat-{sfx}", latest_rejection_code="-11"),
            CoreCharge(source="virtualpos1", external_id=f"unk-{sfx}", latest_rejection_code="-2119"),
            CoreCharge(source="toku", external_id=f"tk-{sfx}", latest_rejection_code="TEPSP2070",
                       latest_rejection_reason="EXCEDE LÍMITE DE REINTENTOS"),
            TchTransaction(file_number=file_number, period="2011-08", amount="5000", charge_date="2011-08-06",
                           status="RECHAZADA", rejection_reason=None, response_code=None, dedupe_key=f"{sfx}-1"),
        ])
        f = VpReportFile(report_type="transacciones", file_sha256=hashlib.sha256(sfx.encode()).hexdigest(),
                         filename=f"TransaccionesPAT-{sfx}.csv", status="completed")
        db.add(f)
        db.flush()
        db.add(VpReportPayment(charge_external_id=f"rep-{sfx}", platform="virtualpos1", platform_status="resolved",
                               charge_status="rechazado", response_code="-1003",
                               response_text="EXCEDE EL LÍMITE DE INTENTOS", source_generated_at=NOW, last_file_id=f.id))
        db.commit()
    finally:
        db.close()


EXPECTED = {
    "rep": "Excede el límite de intentos (código -1003)",
    "api": "Excede monto máximo (código -3)",
    "cat": "Excede límite de reintentos de rechazo (código -11)",
    "unk": "Motivo no informado (código -2119)",
    "nada": "Motivo no informado",
    "ok": None,
    "tk": "Excede límite de reintentos (código TEPSP2070)",
}
DATES = {"date_from": "2011-08-01", "date_to": "2011-08-31"}
PERMS = ["virtualpos.charges.view", "toku.invoices.view", "tch.transacciones.view"]


def _by_key(rows: list[dict], sfx: str) -> dict[str, str | None]:
    out = {}
    for row in rows:
        if row["channel"] == "tch":
            out["tch"] = row["rejection_reason"]
        elif str(row["charge_id"]).endswith(sfx):
            out[str(row["charge_id"]).removesuffix(f"-{sfx}")] = row["rejection_reason"]
    return out


def test_unified_charges_api_shows_text_by_priority(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    client = _login(monkeypatch, sfx, PERMS)
    resp = client.get("/api/v1/general/charges", params={**DATES, "limit": 200})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert all(not any(key.startswith("_rej") for key in row) for row in rows)
    got = _by_key(rows, sfx)
    assert {k: got[k] for k in EXPECTED} == EXPECTED
    assert got["tch"] == "Motivo no informado"


def test_export_rows_carry_the_same_text() -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    items, _denied = select_specs("cobros", None, set(PERMS))
    rows = list(iter_rows(SessionLocal, items, ExportFilters(date_from=date(2011, 8, 1), date_to=date(2011, 8, 31)), False))
    assert all(set(row) >= {"rejection_reason"} and not any(k.startswith("_rej") for k in row) for row in rows)
    got = _by_key(rows, sfx)
    assert {k: got[k] for k in EXPECTED} == EXPECTED


def test_charge_detail_includes_rejection_text(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx, random.randint(90_000_000, 99_999_999))
    client = _login(monkeypatch, sfx, PERMS)
    vp = client.get(f"/api/v1/staging/virtualpos/charges/rep-{sfx}")
    assert vp.status_code == 200, vp.text
    assert vp.json()["charge"]["payload"]["motivo_rechazo"] == EXPECTED["rep"]
    paid = client.get(f"/api/v1/staging/virtualpos/charges/ok-{sfx}").json()
    assert "motivo_rechazo" not in paid["charge"]["payload"]
    tk = client.get(f"/api/v1/staging/toku/invoice/tk-{sfx}")
    assert tk.status_code == 200, tk.text
    assert tk.json()["record"]["payload"]["motivo_rechazo"] == EXPECTED["tk"]
