"""Lote 1: afirmaciones de LECTURA de la doc de VirtualPOS contra el sandbox. Registran drift; no fallan por él."""

from __future__ import annotations

import re

import pytest

from tests_contract.virtualpos.provider import call, records

DOCS = "docs/integrations/virtualpos/resources"


def _all_charges(sub_id: str, **extra: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 51):
        resp = call("GET", f"/v3/suscription/{sub_id}/charges", {"page": page, "limit": 100, **extra})
        rows = records(resp.body, "charges") if resp.ok else []
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def _first_subscription_with_charges() -> tuple[str, list[dict]]:
    resp = call("GET", "/v3/suscriptions", {"page": 1, "limit": 100})
    for sub in records(resp.body, "suscriptions"):
        sid = str(sub.get("id") or sub.get("suscription_id") or "")
        if sid:
            charges = _all_charges(sid)
            if charges:
                return sid, charges
    pytest.skip("Ninguna suscripcion del sandbox tiene cargos para inspeccionar.")


@pytest.mark.contract(claim="VP-C01")
def test_vp_c01_listado_trae_todos_los_cargos(claim):
    """Doc: docs/integrations/virtualpos/resources/subscriptions.md (+ charges.md).
    Esperado: `charge_program[]` de GET /v3/suscriptions trae TODOS los cargos de la suscripcion
    (igual al total de GET /v3/suscription/{id}/charges)."""
    resp = call("GET", "/v3/suscriptions", {"page": 1, "limit": 100})
    subs = records(resp.body, "suscriptions")
    if not resp.ok or not subs:
        pytest.skip("GET /v3/suscriptions sin datos en el sandbox.")
    doc = f"{DOCS}/subscriptions.md"
    with_cp = sum(isinstance(s.get("charge_program"), list) for s in subs)
    claim.check("VP-C01", doc, {"con_charge_program": len(subs), "total": len(subs)},
                {"con_charge_program": with_cp, "total": len(subs)}, http_status=resp.status,
                note="toda suscripcion del listado trae charge_program[]")
    for sub in [s for s in subs if isinstance(s.get("charge_program"), list)][:5]:
        sid = str(sub.get("id") or sub.get("suscription_id") or "")
        total = len(_all_charges(sid))
        claim.check("VP-C01", doc, total, len(sub["charge_program"]), note=f"suscripcion {sid}: charges vs charge_program")


@pytest.mark.contract(claim="VP-C08")
def test_vp_c08_forma_de_payments_y_parser(claim):
    """Doc: docs/integrations/virtualpos/resources/payments.md (l.956) y pagination.md.
    Esperado: GET /v3/payments devuelve `payments` como lista; el ejemplo oficial lo muestra como objeto y la doc
    pide un parser que acepte ambos. Se verifica que `_records_from_response` no descarte datos reales."""
    from app.services.virtualpos_sync import _records_from_response

    resp = call("GET", "/v3/payments", {"page": 1, "limit": 5})
    body = resp.body
    value = body.get("payments") if isinstance(body, dict) else None
    shape = type(value).__name__ if value is not None else "ausente"
    claim.check("VP-C08", f"{DOCS}/payments.md", "list", shape, http_status=resp.status,
                note=f"claves raiz: {sorted(body) if isinstance(body, dict) else type(body).__name__}")
    parsed = _records_from_response(body)
    if value:
        claim.check("VP-C08", "app/services/virtualpos_sync.py::_records_from_response",
                    "registros > 0", f"{len(parsed)} registros", http_status=resp.status, matches=bool(parsed),
                    note="" if parsed else f"HALLAZGO GRAVE: el parser descarta datos reales (forma {shape})")
    else:
        pytest.skip("Sin pagos en el sandbox: no se puede evaluar el parser.")


@pytest.mark.contract(claim="VP-C14")
def test_vp_c14_paginacion(claim):
    """Doc: docs/integrations/virtualpos/resources/pagination.md.
    Esperado: page parte en 1; limit minimo 1 y maximo 100 (E-090 page, E-091 limit invalidos)."""
    doc = f"{DOCS}/pagination.md"
    cases = {
        "page=1,limit=100": ({"page": 1, "limit": 100}, 200),
        "limit=101": ({"page": 1, "limit": 101}, None),
        "page=0": ({"page": 0, "limit": 100}, None),
    }
    first_ids = {}
    for label, (params, expected_status) in cases.items():
        resp = call("GET", "/v3/clients", params)
        rows = records(resp.body, "clients")
        first_ids[label] = rows[0].get("id") if rows else None
        if expected_status:
            claim.check("VP-C14", doc, expected_status, resp.status, note=label, http_status=resp.status)
        else:
            claim.check("VP-C14", doc, "error 400 (E-090/E-091)", f"HTTP {resp.status} {resp.error_code or ''}".strip(),
                        note=f"{label}; registros devueltos: {len(rows)}", http_status=resp.status,
                        error_code=resp.error_code)
    claim.check("VP-C14", doc, "page=0 no devuelve el mismo primer registro que page=1 (page parte en 1)",
                f"primer id page=0 == page=1: {first_ids['page=0'] is not None and first_ids['page=0'] == first_ids['page=1,limit=100']}",
                note="observacion; el sandbox puede aceptar page=0")


@pytest.mark.contract(claim="VP-C15")
def test_vp_c15_clients_paginacion_en_raiz(claim):
    """Doc: docs/integrations/virtualpos/resources/pagination.md (tabla seccion 2).
    Esperado: GET /v3/clients trae page/limit/total en la raiz y NO `pages`."""
    resp = call("GET", "/v3/clients", {"page": 1, "limit": 5})
    keys = sorted(resp.body) if isinstance(resp.body, dict) else []
    root = {"page", "limit", "total"} <= set(keys) and "pages" not in keys
    claim.check("VP-C15", f"{DOCS}/pagination.md", "page/limit/total en la raiz, sin pages",
                "page/limit/total en la raiz, sin pages" if root else "distinto", http_status=resp.status,
                note=f"claves observadas: {keys}; pagination={isinstance(resp.body, dict) and 'pagination' in keys}")


@pytest.mark.contract(claim="VP-C16")
def test_vp_c16_rafaga_de_20_get(claim):
    """Doc: docs/integrations/virtualpos/resources/pagination.md (l.74) y errors.md.
    Esperado: rate limit NO documentado; solo se observa si aparece 429 o cabeceras de rate limit en 20 GET seguidos."""
    statuses, rl_headers = [], set()
    for _ in range(20):
        resp = call("GET", "/v3/plans", {"page": 1, "limit": 1})
        statuses.append(resp.status)
        rl_headers |= {h for h in resp.headers if "ratelimit" in h or "rate-limit" in h or h == "retry-after"}
    claim.check("VP-C16", f"{DOCS}/pagination.md", "sin 429 ni cabeceras de rate limit (no documentado)",
                {"429": statuses.count(429), "estados": sorted({str(s) for s in statuses}), "cabeceras": sorted(rl_headers)},
                matches=statuses.count(429) == 0 and not rl_headers,
                note="rafaga con pausa de ~300 ms entre llamadas; solo observacion")


def _json_kind(value: object) -> str:
    """Nombre JSON del tipo: int/float -> 'number' (bool queda aparte)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


@pytest.mark.contract(claim="VP-C19")
def test_vp_c19_tipos_de_charge(claim):
    """Doc: docs/integrations/virtualpos/resources/charges.md (Objeto Charge).
    Esperado: amount numerico, charge_date string YYYY-MM-DD, id de cargo string `cid_...`/`id_...`."""
    sid, charges = _first_subscription_with_charges()
    sample = charges[0]
    doc = f"{DOCS}/charges.md"
    claim.check("VP-C19", doc, "number", _json_kind(sample.get("amount")), note=f"suscripcion {sid}, amount")
    ok_dates = all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("charge_date"))) for c in charges)
    claim.check("VP-C19", doc, "YYYY-MM-DD en todos los cargos", "YYYY-MM-DD en todos los cargos" if ok_dates
                else f"ejemplo: {sample.get('charge_date')}", note="formato de charge_date")
    claim.check("VP-C19", doc, "str con prefijo cid_/id_", f"{type(sample.get('id')).__name__} {str(sample.get('id'))[:4]}",
                matches=isinstance(sample.get("id"), str) and str(sample["id"]).startswith(("cid_", "id_")),
                note="forma del id del cargo (solo prefijo)")


@pytest.mark.contract(claim="VP-C28")
def test_vp_c28_internal_code_en_payload_del_cargo(claim, sub_variable):
    """Doc: docs/integrations/virtualpos/resources/charges.md (solo `cancel_charges[]` muestra `internal_code`).
    Esperado: el payload de un cargo existente de la suscripcion variable expone `internal_code` (lectura pura).
    Registra solo NOMBRES de campos y si hay valores no vacios, nunca los valores."""
    listing = call("GET", f"/v3/suscription/{sub_variable}/charges", {"page": 1, "limit": 100})
    rows = records(listing.body, "charges") if listing.ok else []
    if not rows:
        pytest.skip("La suscripcion CONTRACT_VP_SUB_VARIABLE no tiene cargos para inspeccionar.")
    detail = call("GET", f"/v3/charge/{rows[0].get('id')}")
    detail_obj = detail.body.get("charge") if isinstance(detail.body, dict) and isinstance(detail.body.get("charge"), dict)         else (detail.body if isinstance(detail.body, dict) else {})
    observed = {
        "campos_listado": sorted(rows[0]),
        "campos_detalle": sorted(detail_obj),
        "internal_code_en_listado": any("internal_code" in r for r in rows),
        "internal_code_en_detalle": "internal_code" in detail_obj,
        "con_valor_no_vacio": sum(bool(r.get("internal_code")) for r in rows),
        "total_cargos": len(rows),
    }
    exposed = observed["internal_code_en_listado"] or observed["internal_code_en_detalle"]
    claim.check("VP-C28", f"{DOCS}/charges.md", "internal_code presente en el payload del cargo", observed,
                http_status=listing.status, matches=exposed,
                note="si no aparece, no hay forma verificable de adoptar un cargo previo por internal_code")


@pytest.mark.contract(claim="VP-C26")
def test_vp_c26_filtros_de_fecha(claim):
    """Doc: docs/integrations/virtualpos/resources/charges.md (l.766-767).
    Esperado: charge_date_from/to NO estan declarados (solo aparecen en errores E-093/E-094/E-095); se observa si
    existen y filtran en GET /v3/suscription/{id}/charges."""
    sid, charges = _first_subscription_with_charges()
    dates = sorted(str(c.get("charge_date")) for c in charges if c.get("charge_date"))
    if len(dates) < 2 or dates[0] == dates[-1]:
        pytest.skip("La suscripcion no tiene cargos con fechas distintas para probar el filtro.")
    day = dates[-1]
    doc = f"{DOCS}/charges.md"
    resp_from = call("GET", f"/v3/suscription/{sid}/charges", {"page": 1, "limit": 100, "charge_date_from": day})
    rows_from = records(resp_from.body, "charges")
    resp_to = call("GET", f"/v3/suscription/{sid}/charges", {"page": 1, "limit": 100, "charge_date_to": dates[0]})
    rows_to = records(resp_to.body, "charges")
    claim.check("VP-C26", doc, {"http": 200, "devueltos": "< sin_filtro", "todos_cumplen": True},
                {"http": resp_from.status, "devueltos": len(rows_from), "sin_filtro": len(charges),
                 "todos_cumplen": all(str(c.get("charge_date")) >= day for c in rows_from)},
                http_status=resp_from.status, error_code=resp_from.error_code, note="charge_date_from",
                matches=resp_from.ok and len(rows_from) < len(charges)
                and all(str(c.get("charge_date")) >= day for c in rows_from))
    claim.check("VP-C26", doc, {"http": 200, "devueltos": "< sin_filtro", "todos_cumplen": True},
                {"http": resp_to.status, "devueltos": len(rows_to), "sin_filtro": len(charges),
                 "todos_cumplen": all(str(c.get("charge_date")) <= dates[0] for c in rows_to)},
                http_status=resp_to.status, error_code=resp_to.error_code, note="charge_date_to",
                matches=resp_to.ok and len(rows_to) < len(charges)
                and all(str(c.get("charge_date")) <= dates[0] for c in rows_to))
