"""EXP-03 / EXP-05: endpoints GET /api/v1/export/{entidad} con datos sinteticos."""

import csv
import io
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.models.write_run import WriteRun
from app.services.charge_stats import chile_today
from app.services.rbac import seed_permissions

PII_HEADERS = {"RUT del cliente", "Nombre del cliente", "Correo", "Teléfono", "Dirección", "RUT", "Nombre"}


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=f"exp-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"exp-{suffix}", password_hash=hash_password("Pw-exp-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": f"exp-{suffix}", "password": "Pw-exp-12345"}).status_code == 200
    return client


_TAG = "zq[0-9a-f]{8}"


@pytest.fixture(autouse=True)
def _cleanup_synthetic_rows():
    """Estos tests hacen commit (la ruta usa sus propias sesiones): se borra todo lo sintetico al terminar para no
    contaminar otros tests que cuentan filas (status_events, dashboard)."""
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        stmts = [
            "DELETE FROM write_runs WHERE request_payload->>'username' ~ ('^exp-' || :tag)",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^exp-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^exp-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^exp-' || :tag)",
            "DELETE FROM charges WHERE external_id ~ :tag",
            "DELETE FROM payments WHERE external_id ~ :tag",
            "DELETE FROM subscriptions WHERE external_id ~ :tag",
            "DELETE FROM clients WHERE external_id ~ :tag OR external_id ~ :tag",
            "DELETE FROM tch_transacciones WHERE dedupe_key ~ :tag",
            "DELETE FROM tch_suscripciones WHERE cliente_rut IN (SELECT rut FROM tch_clientes WHERE nombre ~ :tag)",
            "DELETE FROM tch_clientes WHERE nombre ~ :tag",
        ]
        for stmt in stmts:
            db.execute(text(stmt), params)
        db.commit()
    finally:
        db.close()


def _parse(resp) -> tuple[list[str], list[dict[str, str]]]:
    assert resp.status_code == 200, resp.text
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    return rows[0], [dict(zip(rows[0], r, strict=True)) for r in rows[1:]]


def _sfx() -> str:
    return "zq" + uuid.uuid4().hex[:8]


def _seed_clients(sfx: str) -> None:
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"c1-{sfx}", first_name=f"Ana{sfx}", last_name="Prueba", email=f"ana{sfx}@example.test",
                   phone_number="+56900000001", social_id="11111111-1", status="active"),
            Client(source="toku", external_id=f"c2-{sfx}", first_name=f"Beto{sfx}", last_name="Prueba", email=f"beto{sfx}@example.test",
                   social_id="22222222-2", status="active"),
            TchClient(rut=f"33{random.randint(100000, 999999)}-3", name=f"Cata{sfx}", last_name="Prueba", email=f"cata{sfx}@example.test",
                       phone="+56900000003", address="Calle Falsa 123", district="Comuna X", city="Ciudad Y"),
        ])
        db.commit()
    finally:
        db.close()


ALL_VIEW = ["tch.clientes.view", "virtualpos.clients.view", "toku.customers.view", "payku.clients.view"]


def test_clientes_without_pii_permission_has_no_personal_columns(monkeypatch) -> None:
    sfx = _sfx()
    _seed_clients(sfx)
    client = _login(monkeypatch, sfx, ALL_VIEW)
    resp = client.get("/api/v1/export/clientes", params={"query": sfx, "filter_field": "name", "all": "true"})
    header, rows = _parse(resp)
    assert not (set(header) & PII_HEADERS), header
    assert {r["Canal"] for r in rows} == {"virtualpos1", "toku", "tch"}
    text = resp.content.decode("utf-8-sig")
    for leaked in ("11111111-1", "example.test", "+569", "Calle Falsa", f"Ana{sfx}"):
        assert leaked not in text


def test_clientes_with_export_pii_includes_personal_columns(monkeypatch) -> None:
    sfx = _sfx()
    _seed_clients(sfx)
    client = _login(monkeypatch, sfx, [*ALL_VIEW, "export.pii"])
    header, rows = _parse(client.get("/api/v1/export/clientes", params={"query": sfx, "filter_field": "name", "all": "true"}))
    assert {"RUT", "Nombre", "Correo", "Teléfono", "Dirección"} <= set(header)
    by_canal = {r["Canal"]: r for r in rows}
    assert by_canal["virtualpos1"]["RUT"] == "11111111-1" and by_canal["virtualpos1"]["Correo"] == f"ana{sfx}@example.test"
    assert by_canal["tch"]["Dirección"].startswith("Calle Falsa 123")


def test_channel_permissions_filter_on_server(monkeypatch) -> None:
    sfx = _sfx()
    _seed_clients(sfx)
    only_tch = _login(monkeypatch, sfx + "a", ["tch.clientes.view"])
    _, rows = _parse(only_tch.get("/api/v1/export/clientes", params={"query": sfx, "filter_field": "name", "all": "true"}))
    assert {r["Canal"] for r in rows} == {"tch"}
    assert only_tch.get("/api/v1/export/clientes", params={"canal": "toku"}).status_code == 403
    assert only_tch.get("/api/v1/export/cobros").status_code == 403  # sin permiso de vista de cobros
    nothing = _login(monkeypatch, sfx + "b", ["dashboard.view"])
    assert nothing.get("/api/v1/export/clientes").status_code == 403
    assert nothing.get("/api/v1/export/cobros/count").status_code == 403


def test_unknown_entity_and_bad_filters_are_rejected(monkeypatch) -> None:
    client = _login(monkeypatch, _sfx(), ALL_VIEW)
    assert client.get("/api/v1/export/inexistente").status_code in (404, 422)
    assert client.get("/api/v1/export/clientes", params={"canal": "otro"}).status_code == 422
    assert client.get("/api/v1/export/clientes", params={"filter_field": "zzz", "query": "a"}).status_code == 422
    assert client.get("/api/v1/export/clientes", params={"date_from": "31-12-2020"}).status_code == 422


def test_cobros_filters_pagination_all_formulas_and_headers(monkeypatch) -> None:
    sfx = _sfx()
    db = SessionLocal()
    try:
        db.add_all([
            Charge(source="virtualpos1", external_id=f"ch{i}-{sfx}", subscription_external_id=f"sub-{sfx}", status=st, charge_date=d, amount=amt, currency="CLP")
            for i, (st, d, amt) in enumerate([
                ("pagado", "2026-01-10", "1000"), ("rechazado", "2026-02-10", "2000"), ("pagado", "2026-03-10T10:00:00", "3000"),
                ("pagado", "2026-04-10", "4000"), ("=cmd", "2026-05-10", "5000"),
            ])
        ])
        db.commit()
    finally:
        db.close()
    client = _login(monkeypatch, sfx, ["virtualpos.charges.view"])
    base = {"query": sfx, "filter_field": "id"}
    resp = client.get("/api/v1/export/cobros", params={**base, "all": "true"})
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;") and f"cobros-{chile_today():%Y%m%d}" in disposition
    assert resp.content.startswith(b"\xef\xbb\xbf")
    header, rows = _parse(resp)
    assert header[:5] == ["Canal", "ID de cobro", "ID de suscripción", "Estado", "Fecha de cobro"] and len(rows) == 5
    assert "'=cmd" in {r["Estado"] for r in rows}  # formula neutralizada
    assert not (set(header) & PII_HEADERS)
    # paginacion: sin `all` se exporta solo la pagina; con `all` se ignora
    assert len(_parse(client.get("/api/v1/export/cobros", params={**base, "limit": 2}))[1]) == 2
    assert len(_parse(client.get("/api/v1/export/cobros", params={**base, "limit": 2, "offset": 4}))[1]) == 1
    # filtros
    assert len(_parse(client.get("/api/v1/export/cobros", params={**base, "all": "true", "status": "pagado"}))[1]) == 3
    window = {**base, "all": "true", "date_from": "2026-02-01", "date_to": "2026-03-31"}
    assert len(_parse(client.get("/api/v1/export/cobros", params=window))[1]) == 2
    amounts = {**base, "all": "true", "amount_min": "2500", "amount_max": "4500"}
    assert len(_parse(client.get("/api/v1/export/cobros", params=amounts))[1]) == 2
    nothing = {"query": "nada-" + sfx, "filter_field": "id", "all": "true"}
    assert len(_parse(client.get("/api/v1/export/cobros", params=nothing))[1]) == 0
    count = client.get("/api/v1/export/cobros/count", params={**base, "status": "pagado"}).json()
    assert count["rows"] == 3 and count["include_pii"] is False


def test_cobros_vp_pii_requires_permission_and_audit_has_no_content(monkeypatch) -> None:
    sfx = _sfx()
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{sfx}", first_name=f"Dora{sfx}", last_name="Prueba", social_id="44444444-4",
                   email=f"d{sfx}@example.test"),
            Subscription(source="virtualpos1", external_id=f"sub-{sfx}", client_external_id=f"cl-{sfx}", status="activa"),
            Charge(source="virtualpos1", external_id=f"ch-{sfx}", subscription_external_id=f"sub-{sfx}", status="pagado",
                   charge_date="2026-01-01", amount="10"),
        ])
        db.commit()
    finally:
        db.close()
    params = {"query": sfx, "filter_field": "id", "all": "true"}
    plain = _login(monkeypatch, sfx + "p", ["virtualpos.charges.view"])
    header, rows = _parse(plain.get("/api/v1/export/cobros", params=params))
    assert "RUT del cliente" not in header and "44444444-4" not in str(rows)
    pii = _login(monkeypatch, sfx + "q", ["virtualpos.charges.view", "export.pii"])
    header, rows = _parse(pii.get("/api/v1/export/cobros", params=params))
    assert rows[0]["RUT del cliente"] == "44444444-4" and rows[0]["Nombre del cliente"] == f"Dora{sfx} Prueba"
    db = SessionLocal()
    try:
        run = db.scalars(select(WriteRun).where(
            WriteRun.operation == "export_csv", WriteRun.request_payload["username"].astext == f"exp-{sfx}q")).one()
        payload = run.request_payload
        assert payload["endpoint"] == "export/cobros" and payload["rows"] == 1 and payload["pii_included"] is True
        assert payload["filters"]["all"] is True and payload["filters"]["canales"] == ["virtualpos1", "virtualpos2"]
        assert run.status == "completed" and run.started_at is not None and run.requested_by_user_id is not None
        dumped = str(payload)
        for leaked in ("44444444-4", f"Dora{sfx}", "example.test"):
            assert leaked not in dumped
    finally:
        db.close()


def test_audit_does_not_store_personal_search_text(monkeypatch) -> None:
    sfx = _sfx()
    client = _login(monkeypatch, sfx, ["virtualpos.clients.view"])
    resp = client.get("/api/v1/export/clientes", params={"query": "55555555-5", "filter_field": "rut", "canal": "virtualpos"})
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        run = db.scalars(select(WriteRun).where(WriteRun.request_payload["username"].astext == f"exp-{sfx}")).one()
        assert "55555555" not in str(run.request_payload)
        assert run.request_payload["filters"]["query_len"] == 10
    finally:
        db.close()


def test_suscripciones_vp_and_tch_with_filters(monkeypatch) -> None:
    sfx = _sfx()
    ficha = random.randint(70_000_000, 79_999_999)
    rut = f"66{random.randint(100000, 999999)}-6"
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{sfx}", first_name=f"Eva{sfx}", last_name="Prueba", social_id="77777777-7"),
            Subscription(source="virtualpos1", external_id=f"s1-{sfx}", client_external_id=f"cl-{sfx}", status="activa",
                         suscription_date="2026-01-05", amount="3000", currency="CLP"),
            Subscription(source="virtualpos1", external_id=f"s2-{sfx}", status="cancelada", suscription_date="2025-01-05",
                         canceled_at="2026-02-02", amount="1000"),
            Subscription(source="virtualpos1", external_id=f"s3-{sfx}", status="SUSCRIPCION_FALLIDA", suscription_date="2026-01-05"),
            Charge(source="virtualpos1", external_id=f"ch-{sfx}", subscription_external_id=f"s1-{sfx}", status="pagado",
                   charge_date="2026-03-03"),
            TchClient(rut=rut, name=f"Fer{sfx}", last_name="Prueba"),
            TchSubscription(file_number=ficha, client_rut=rut, status="VIGENTE", activation_date="2026-01-01", amount="5000",
                           peso_equivalent="5000"),
        ])
        db.commit()
    finally:
        db.close()
    perms = ["virtualpos.subscriptions.view", "tch.suscripciones.view"]
    client = _login(monkeypatch, sfx, perms)
    by_id = {"query": sfx, "filter_field": "id", "all": "true"}
    _, rows = _parse(client.get("/api/v1/export/suscripciones", params=by_id))
    assert {r["ID de suscripción"] for r in rows} == {f"s1-{sfx}", f"s2-{sfx}"}  # la fallida queda excluida, como en la vista
    s1 = next(r for r in rows if r["ID de suscripción"] == f"s1-{sfx}")
    assert s1["Último cobro"] == "2026-03-03" and s1["Estado"] == "activa" and s1["Monto"] == "3000"
    _, rows = _parse(client.get("/api/v1/export/suscripciones", params={**by_id, "status": "cancelada"}))
    assert [r["ID de suscripción"] for r in rows] == [f"s2-{sfx}"]
    tch_params = {"canal": "tch", "query": str(ficha), "filter_field": "id", "all": "true"}
    header, rows = _parse(client.get("/api/v1/export/suscripciones", params=tch_params))
    assert len(rows) == 1 and rows[0]["Canal"] == "tch" and rows[0]["Estado"] == "VIGENTE" and rows[0]["Monto"] == "5000"
    assert not (set(header) & PII_HEADERS)
    pii = _login(monkeypatch, sfx + "x", [*perms, "export.pii"])
    _, rows = _parse(pii.get("/api/v1/export/suscripciones", params=tch_params))
    assert rows[0]["RUT del cliente"] == rut and rows[0]["Nombre del cliente"] == f"Fer{sfx} Prueba"
    by_client = {"query": f"Eva{sfx}", "filter_field": "client", "all": "true"}
    _, rows = _parse(pii.get("/api/v1/export/suscripciones", params=by_client))
    assert [r["RUT del cliente"] for r in rows] == ["77777777-7"]


def test_cobros_tch_and_pagos(monkeypatch) -> None:
    sfx = _sfx()
    ficha = random.randint(80_000_000, 89_999_999)
    db = SessionLocal()
    try:
        db.add_all([
            TchTransaction(file_number=ficha, period="2026-01", amount="5000", charge_date="2026-01-15", status="ACEPTADA",
                           dedupe_key=f"{sfx}-1"),
            TchTransaction(file_number=ficha, period="2026-02", amount="5000", charge_date="2026-02-15", status="RECHAZADA",
                           rejection_reason="Sin fondos", dedupe_key=f"{sfx}-2"),
            Payment(source="toku", external_id=f"pay-{sfx}", charge_external_id=f"c-{sfx}", status="paid", payment_date="2026-01-20",
                    amount="900", currency="CLP"),
            Payment(source="payku", external_id=f"pay2-{sfx}", status="success", payment_date="2026-01-21", amount="800"),
        ])
        db.commit()
    finally:
        db.close()
    client = _login(monkeypatch, sfx, ["tch.transacciones.view", "toku.transactions.view"])
    tch = {"query": str(ficha), "filter_field": "subscription_id", "all": "true"}
    _, rows = _parse(client.get("/api/v1/export/cobros", params=tch))
    assert {(r["Canal"], r["Estado"], r["Período"]) for r in rows} == {("tch", "ACEPTADA", "2026-01"), ("tch", "RECHAZADA", "2026-02")}
    assert next(r for r in rows if r["Estado"] == "RECHAZADA")["Motivo de rechazo"] == "Sin fondos"
    _, rows = _parse(client.get("/api/v1/export/cobros", params={**tch, "status": "rechazada"}))
    assert len(rows) == 1
    # pagos: falta payku.transactions.view -> solo toku
    header, rows = _parse(client.get("/api/v1/export/pagos", params={"query": sfx, "filter_field": "id", "all": "true"}))
    assert header[:5] == ["Canal", "ID de pago", "ID de cobro", "Estado", "Fecha de pago"]
    assert [(r["Canal"], r["ID de pago"], r["Monto"]) for r in rows] == [("toku", f"pay-{sfx}", "900")]
    assert client.get("/api/v1/export/pagos", params={"canal": "payku"}).status_code == 403
