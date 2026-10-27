"""Lote 2: afirmaciones de ESCRITURA REVERSIBLE contra el sandbox. Registran drift; no fallan por él.

Solo crean cargos `pendiente` a hoy+20 dias y solo cancelan cargos creados por ellas mismas (registro
`created_charges`, limpiado al final de la sesion). Nunca tocan cargos pagados/procesando.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests_contract.virtualpos.provider import call, charge_obj, chile_today, records

DOCS = "docs/integrations/virtualpos/resources"
write_test = pytest.mark.contract_write


def _observed(resp) -> str:
    return f"HTTP {resp.status} {resp.error_code}" if resp.error_code else f"HTTP {resp.status}"


def _pending(sub_id: str) -> list[dict]:
    resp = call("GET", f"/v3/suscription/{sub_id}/charges", {"page": 1, "limit": 100, "status": "pendiente"})
    return records(resp.body, "charges") if resp.ok else []


@write_test
@pytest.mark.contract(claim="VP-C05")
def test_vp_c05_cargo_sobre_plan_fijo(claim, created_charges, sub_fixed):
    """Doc: docs/integrations/virtualpos/resources/charges.md (POST /v3/charge) y README.md.
    Esperado: POST /v3/charge sobre una suscripcion de plan MONTO_FIJO falla con E-113 (HTTP 400).
    Drift conocido: el 2026-10-27 el sandbox lo acepto."""
    resp = created_charges.create(sub_fixed, "VP-C05")
    claim.check("VP-C05", f"{DOCS}/charges.md", "HTTP 400 E-113", _observed(resp), http_status=resp.status,
                error_code=resp.error_code, note="drift conocido: aceptado en la prueba del 2026-10-27")


@write_test
@pytest.mark.contract(claim="VP-C07")
def test_vp_c07_internal_code_duplicado(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/errors.md (E-086) y charges.md.
    Esperado: dos POST con el MISMO internal_code -> el segundo responde E-086."""
    code = created_charges.internal_code("VP-C07")
    first = created_charges.create(sub_variable, "VP-C07", internal_code=code)
    second = created_charges.create(sub_variable, "VP-C07", internal_code=code, days=21)
    claim.check("VP-C07", f"{DOCS}/errors.md", "HTTP 200", _observed(first), http_status=first.status,
                note="1er POST con el internal_code")
    claim.check("VP-C07", f"{DOCS}/errors.md", "HTTP 400 E-086", _observed(second),
                http_status=second.status, error_code=second.error_code, note="2do POST con el mismo internal_code")


@write_test
@pytest.mark.contract(claim="VP-C29")
def test_vp_c29_reutilizar_internal_code_tras_cancelar(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/charges.md (internal_code). Sin esperado documentado.
    Observa si se puede crear un cargo con un internal_code cuyo cargo anterior fue cancelado
    (la app crea uno nuevo en ese caso, no adopta el cancelado)."""
    code = created_charges.internal_code("VP-C29")
    first = created_charges.create(sub_variable, "VP-C29", internal_code=code)
    cid = charge_obj(first.body).get("id")
    if not first.ok or not cid:
        pytest.skip(f"No se pudo crear el cargo de prueba ({_observed(first)}).")
    cancelled = call("DELETE", f"/v3/charge/{cid}")
    if not cancelled.ok:
        pytest.skip(f"No se pudo cancelar el cargo de prueba ({_observed(cancelled)}).")
    second = created_charges.create(sub_variable, "VP-C29", internal_code=code, days=21)
    claim.check("VP-C29", f"{DOCS}/charges.md", "HTTP 200", _observed(second),
                http_status=second.status, error_code=second.error_code,
                note="2do POST con el mismo internal_code tras cancelar el 1.º")


@write_test
@pytest.mark.contract(claim="VP-C27")
def test_vp_c27_errores_de_negocio_llegan_con_http_200(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/errors.md (los errores se documentan como HTTP 4xx).
    Esperado: una peticion invalida (POST /v3/charge con charge_date pasada, no crea nada) responde HTTP 400 con
    status NOK. Observacion conocida: llega HTTP 200 con cuerpo {"status": "NOK", "code": 400, "error": {...}}."""
    past = (chile_today() - timedelta(days=3)).strftime("%Y-%m-%d")
    resp = created_charges.create(sub_variable, "VP-C27", charge_date=past)
    body = resp.body if isinstance(resp.body, dict) else {}
    observed = {"http": resp.status, "status": body.get("status"), "code": body.get("code"),
                "error_code": resp.error_code}
    claim.check("VP-C27", f"{DOCS}/errors.md", {"http": 400, "status": "NOK", "code": 400, "error_code": "E-078"},
                observed, http_status=resp.status, error_code=resp.error_code,
                note="el cliente de la app detecta este NOK y lanza VirtualPOSAPIError")


@write_test
@pytest.mark.contract(claim="VP-C09")
def test_vp_c09_delete_con_firma_solo_api_key(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/authentication.md (l.32).
    Esperado: DELETE /v3/charge/{id} funciona con la firma de solo {api_key}: responde 200."""
    made = created_charges.create(sub_variable, "VP-C09")
    cid = charge_obj(made.body).get("id")
    if not made.ok or not cid:
        pytest.skip(f"No se pudo crear el cargo de prueba ({_observed(made)}).")
    resp = call("DELETE", f"/v3/charge/{cid}")
    claim.check("VP-C09", f"{DOCS}/authentication.md", "HTTP 200", _observed(resp), http_status=resp.status,
                error_code=resp.error_code)


@write_test
@pytest.mark.contract(claim="VP-C11")
def test_vp_c11_delete_plural_sin_pendientes(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/charges.md (DELETE /v3/charges/{sub}) y errors.md.
    Esperado: sobre una suscripcion SIN cargos pendientes responde E-079.
    Si hay pendientes ajenos a la sesion, se salta (el DELETE plural cancelaria cargos que no creamos)."""
    own = {cid for _sub, cid in created_charges.charges}
    foreign = [c for c in _pending(sub_variable) if str(c.get("id")) not in own]
    if foreign:
        pytest.skip("La suscripcion CONTRACT_VP_SUB_VARIABLE tiene pendientes que no creo esta sesion.")
    for charge in _pending(sub_variable):  # solo los propios: se cancelan de a uno
        call("DELETE", f"/v3/charge/{charge['id']}")
    if _pending(sub_variable):
        pytest.skip("No se pudo dejar la suscripcion sin pendientes.")
    resp = call("DELETE", f"/v3/charges/{sub_variable}")
    claim.check("VP-C11", f"{DOCS}/charges.md", "HTTP 400 E-079", _observed(resp), http_status=resp.status,
                error_code=resp.error_code)


@write_test
@pytest.mark.contract(claim="VP-C12")
def test_vp_c12_delete_de_cargo_cancelado(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/errors.md (E-059) y charges.md (Cancelar Charge).
    Esperado: DELETE de un cargo que ya esta `cancelado` responde E-059. Nunca se usa un cargo pagado."""
    made = created_charges.create(sub_variable, "VP-C12")
    cid = charge_obj(made.body).get("id")
    if not made.ok or not cid:
        pytest.skip(f"No se pudo crear el cargo de prueba ({_observed(made)}).")
    first = call("DELETE", f"/v3/charge/{cid}")
    if not first.ok:
        pytest.skip(f"No se pudo cancelar el cargo de prueba ({_observed(first)}).")
    resp = call("DELETE", f"/v3/charge/{cid}")
    claim.check("VP-C12", f"{DOCS}/errors.md", "HTTP 400 E-059", _observed(resp), http_status=resp.status,
                error_code=resp.error_code)


@write_test
@pytest.mark.contract(claim="VP-C13")
def test_vp_c13_filtro_status_pendiente(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/charges.md (Listar Charges, parametro status).
    Esperado: status=pendiente devuelve solo cargos pendientes (crea 2, cancela 1, lista con el filtro)."""
    keep = created_charges.create(sub_variable, "VP-C13", days=20)
    drop = created_charges.create(sub_variable, "VP-C13", days=21)
    keep_id, drop_id = charge_obj(keep.body).get("id"), charge_obj(drop.body).get("id")
    if not (keep.ok and drop.ok and keep_id and drop_id):
        pytest.skip(f"No se pudieron crear los 2 cargos de prueba ({_observed(keep)} / {_observed(drop)}).")
    cancelled = call("DELETE", f"/v3/charge/{drop_id}")
    rows = _pending(sub_variable)
    ids = {str(r.get("id")) for r in rows}
    observed = {"todos_pendiente": all(r.get("status") == "pendiente" for r in rows),
                "incluye_cancelado": str(drop_id) in ids, "incluye_el_pendiente": str(keep_id) in ids}
    claim.check("VP-C13", f"{DOCS}/charges.md",
                {"todos_pendiente": True, "incluye_cancelado": False, "incluye_el_pendiente": True}, observed,
                note=f"cancelacion del cargo descartado: {_observed(cancelled)}", http_status=cancelled.status)


@write_test
@pytest.mark.contract(claim="VP-C21")
def test_vp_c21_charge_date_de_ayer(claim, created_charges, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/charges.md (E-078) y errors.md.
    Esperado: POST con charge_date de ayer responde E-078 (la fecha debe ser >= hoy)."""
    yesterday = (chile_today() - timedelta(days=1)).strftime("%Y-%m-%d")
    resp = created_charges.create(sub_variable, "VP-C21", charge_date=yesterday)
    claim.check("VP-C21", f"{DOCS}/charges.md", "HTTP 400 E-078", _observed(resp), http_status=resp.status,
                error_code=resp.error_code)
