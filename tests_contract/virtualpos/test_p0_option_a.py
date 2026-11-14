"""Lote 3 (BILL-11, DEC-45): recetas P0 de la opcion A contra el sandbox. ESCRITAS, NO EJECUTADAS.

Pendientes de aprobacion en bloque por el usuario (runbook docs/operations/sandbox-testing-and-decisions.md §3.1).
Fuente de las recetas: docs/designs/facturacion-gestionada-escenarios.md, seccion (a).

Reglas comunes:
- Marca `contract_write`: ademas de las guardas de la suite (APP_ENV=sandbox, host de sandbox, CONTRACT_TESTS=1,
  CONTRACT_WRITES=1, VIRTUALPOS_SANDBOX_WRITES_ENABLED=true) cada receta exige CONTRACT_CT_P0=1 (aprobacion en
  bloque) y CONTRACT_CT_PHASE (`arm` o `observe`). Si falta algo, se omite (skip).
- Las suscripciones de prueba son NUEVAS, creadas por una persona con el formulario publico del plan y las tarjetas
  oficiales de sandbox (https://virtualpos.readme.io/reference/datos-de-prueba-sandbox, DEC-09). Sus ids se leen
  SOLO de variables de proceso (`CONTRACT_CT_<RECETA>_SUB`); si falta la variable, la receta se omite. Los cambios
  de tarjeta (`changecard`) los hace una persona en el link del proveedor: la prueba nunca recibe ni guarda numeros
  de tarjeta; solo exige la variable que confirma que el cambio se hizo.
- Todo cargo creado pasa por `ChargeRegistry`. Los que deben esperar su fecha se guardan en un archivo de estado
  (ids de suscripcion y de cargo, sin PII) bajo reports/ (ignorado por git) y la fase `observe` los mide y los
  cancela si siguen `pendiente`. El resto se cancela al final de la sesion (fixture `created_charges`).
- Topes por receta (runbook §3.1): se comprueban ANTES de cada escritura; nunca se superan.
- Nunca se usa el DELETE plural; los automaticos solo se cancelan por `charge_id` y solo donde la receta lo pide.
- `GET /v3/charge/{id}/retry` tiene efectos: se llama una sola vez por intento, sin el backoff de lectura.
- CT-STALE es medicion pura del proveedor con el cliente de la suite (no usa apply_change_request ni decide DEC-30).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests_contract.virtualpos import provider
from tests_contract.virtualpos.conftest import REPORT_DIR, ChargeRegistry
from tests_contract.virtualpos.guards import ENV_SUB_FIXED, ENV_SUB_VARIABLE
from tests_contract.virtualpos.provider import call, charge_obj, chile_today, records

DESIGN = "docs/designs/facturacion-gestionada-escenarios.md"
STATE_FILE = REPORT_DIR / "ct-p0-state.json"
ENV_APPROVED = "CONTRACT_CT_P0"
ENV_PHASE = "CONTRACT_CT_PHASE"

write_test = pytest.mark.contract_write


# --- utilidades --------------------------------------------------------------------------------------------------

def _require_approval_and_phase(*allowed: str) -> str:
    if os.environ.get(ENV_APPROVED) != "1":
        pytest.skip(f"Recetas P0 sin aprobacion en bloque ({ENV_APPROVED}=1 ausente).")
    phase = (os.environ.get(ENV_PHASE) or "").strip()
    if phase not in ("arm", "observe"):
        pytest.skip(f"Falta {ENV_PHASE} (arm u observe).")
    if phase not in allowed:
        pytest.skip(f"La receta no tiene fase '{phase}'.")
    return phase


def _env(name: str, what: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        pytest.skip(f"Falta la variable {name} ({what}).")
    return value


def _dedicated_sub(name: str) -> str:
    """Id de la suscripcion de la receta. Debe ser distinta de las suscripciones compartidas de VP-ESC."""
    sub_id = _env(name, "suscripcion nueva de la receta, creada con el formulario publico")
    shared = {(os.environ.get(ENV_SUB_FIXED) or "").strip(), (os.environ.get(ENV_SUB_VARIABLE) or "").strip()}
    if sub_id in shared:
        pytest.skip(f"{name} coincide con una suscripcion compartida de VP-ESC: la receta exige una dedicada.")
    return sub_id


def _active_subscription(sub_id: str) -> dict[str, Any]:
    resp = call("GET", f"/v3/suscription/{sub_id}")
    body = resp.body if isinstance(resp.body, dict) else {}
    sub = body.get("suscription") if isinstance(body.get("suscription"), dict) else body
    if not resp.ok or body.get("status") == "NOK":
        pytest.skip(f"No se pudo leer la suscripcion de la receta (HTTP {resp.status}, {resp.error_code}).")
    if str(sub.get("status") or "").upper() != "ACTIVA":
        pytest.skip("La suscripcion de la receta no esta ACTIVA.")
    return sub


def _charges(sub_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, 6):
        resp = call("GET", f"/v3/suscription/{sub_id}/charges", {"page": page, "limit": 100})
        rows = records(resp.body, "charges") if resp.ok else []
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def _is_automatic(charge: dict[str, Any]) -> bool:
    """Los automaticos de VirtualPOS no traen internal_code; los manuales si (VP-C28, 2026-10-28)."""
    return not charge.get("internal_code")


def _charge(charge_id: str) -> dict[str, Any]:
    resp = call("GET", f"/v3/charge/{charge_id}")
    return charge_obj(resp.body) if resp.ok else {}


def _has_uuid(charge: dict[str, Any]) -> bool:
    payment = charge.get("payment")
    order = payment.get("order") if isinstance(payment, dict) else None
    return bool(isinstance(order, dict) and order.get("uuid"))


def _payment_uuid(charge: dict[str, Any]) -> str | None:
    payment = charge.get("payment")
    order = payment.get("order") if isinstance(payment, dict) else None
    return str(order["uuid"]) if isinstance(order, dict) and order.get("uuid") else None


def _day(offset: int) -> str:
    return (chile_today() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _today() -> str:
    return _day(0)


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def _observed(resp: provider.Resp) -> str:
    return f"HTTP {resp.status} {resp.error_code}" if resp.error_code else f"HTTP {resp.status}"


def _call_once(method: str, path: str) -> provider.Resp:
    """Llamada sin reintentos (para GET con efectos como /retry). Misma pausa que el cliente de la suite."""
    time.sleep(provider.PAUSE_SECONDS)
    return asyncio.run(provider._request(method, path, None, None))


@dataclass
class Budget:
    """Tope de escrituras de una receta (runbook §3.1). Se comprueba antes de escribir."""

    recipe: str
    max_posts: int
    max_retries: int = 0
    max_auto_cancels: int = 0
    posts: int = 0
    retries: int = 0
    auto_cancels: int = 0

    def take(self, kind: str) -> None:
        used, cap = {"post": (self.posts, self.max_posts), "retry": (self.retries, self.max_retries),
                     "auto_cancel": (self.auto_cancels, self.max_auto_cancels)}[kind]
        if used >= cap:
            pytest.fail(f"{self.recipe}: tope de '{kind}' alcanzado ({cap}); se detiene sin escribir.")
        if kind == "post":
            self.posts += 1
        elif kind == "retry":
            self.retries += 1
        else:
            self.auto_cancels += 1


@dataclass
class State:
    """Cargos que deben esperar su fecha. Solo ids de suscripcion y de cargo (no son PII)."""

    path: Path = STATE_FILE
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> State:
        if STATE_FILE.exists():
            return cls(data=json.loads(STATE_FILE.read_text(encoding="utf-8")))
        return cls()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def put(self, recipe: str, **values: Any) -> None:
        self.data[recipe] = {**values, "armed_at": datetime.now(UTC).isoformat(timespec="seconds")}
        self.save()

    def get(self, recipe: str) -> dict[str, Any]:
        entry = self.data.get(recipe)
        if not entry:
            pytest.skip(f"{recipe}: no hay fase 'arm' registrada en {STATE_FILE.name}.")
        return entry

    def drop(self, recipe: str) -> None:
        self.data.pop(recipe, None)
        self.save()


def _create_kept(budget: Budget, sub_id: str, recipe: str, charge_date: str, state: State, **extra: Any) -> str:
    """Crea un cargo que debe sobrevivir a la sesion (espera su fecha). Se guarda en el estado al instante."""
    budget.take("post")
    keeper = ChargeRegistry()
    resp = keeper.create(sub_id, recipe, charge_date=charge_date)
    cid = provider.charge_id_of(resp.body)
    if not resp.ok or not cid:
        pytest.fail(f"{recipe}: no se pudo crear el cargo ({_observed(resp)}).")
    state.put(recipe, sub_id=sub_id, charge_id=cid, charge_date=charge_date, **extra)
    return cid


def _close_kept(created_charges: ChargeRegistry, entry: dict[str, Any], *keys: str) -> None:
    """Entrega al registro de la sesion los cargos guardados para que los cancele si siguen `pendiente`."""
    for key in keys or ("charge_id",):
        if entry.get(key):
            created_charges.add(entry["sub_id"], entry[key])


def _wait_until_after(entry: dict[str, Any], days_after: int = 0) -> None:
    due = _shift(entry["charge_date"], days_after)
    if _today() <= due:
        pytest.skip(f"Aun no pasa la fecha de observacion ({due}).")


# --- CT-00: ¿el sandbox cobra en la fecha? -------------------------------------------------------------------------

@write_test
@pytest.mark.contract(claim="CT-00")
def test_ct_00_sandbox_charges_on_date(claim, created_charges):
    """[CT-00-COBRO] Plan MONTO_FIJO dia 0, num_charges 12, renovacion T, enrolada con la tarjeta aprobada.
    arm: crea 1 manual a manana. observe (pasada la fecha): estado del manual y si trae payment.order.uuid.
    Tope: 1 suscripcion, 1 cargo. Limpieza: cancela el manual si sigue pendiente. Escenarios CO-05, RZ-03, RZ-05."""
    phase = _require_approval_and_phase("arm", "observe")
    state = State.load()
    if phase == "arm":
        sub_id = _dedicated_sub("CONTRACT_CT_00_SUB")
        _active_subscription(sub_id)
        _create_kept(Budget("CT-00", max_posts=1), sub_id, "CT-00", _day(1), state)
        return
    entry = state.get("CT-00")
    _wait_until_after(entry)
    got = _charge(entry["charge_id"])
    claim.check("CT-00", DESIGN, {"status": "pagado", "con_order_uuid": True},
                {"status": got.get("status"), "con_order_uuid": _has_uuid(got)},
                note="CO-05: un manual a manana se cobra en su fecha en el sandbox")
    _close_kept(created_charges, entry)
    state.drop("CT-00")


# --- CT-CO-AUTO: coexistencia de manuales con automaticos futuros -------------------------------------------------

@write_test
@pytest.mark.contract(claim="CT-CO-AUTO")
def test_ct_co_auto_manual_coexists_with_automatic(claim, created_charges):
    """[CT-CO-AUTO] Plan MONTO_FIJO, 12 cobros, renovacion T, tarjeta aprobada; >= 3 automaticos pendiente futuros.
    Crea 2 manuales en el mes del primer automatico futuro (CO-01, CO-02) y comprueba que los automaticos siguen
    intactos (CO-14). RA-01 (cancelar el automatico del mes) ya se midio el 2026-10-28 y no se repite aqui.
    Tope: 1 suscripcion, 3 cargos. Limpieza: la sesion cancela los manuales."""
    _require_approval_and_phase("arm")
    sub_id = _dedicated_sub("CONTRACT_CT_CO_AUTO_SUB")
    _active_subscription(sub_id)
    budget = Budget("CT-CO-AUTO", max_posts=3)
    before = _charges(sub_id)
    autos = sorted((c for c in before if _is_automatic(c) and c.get("status") == "pendiente"
                    and str(c.get("charge_date")) > _today()), key=lambda c: str(c.get("charge_date")))
    if len(autos) < 3:
        pytest.skip("La suscripcion no tiene 3 automaticos pendiente futuros.")
    first = str(autos[0]["charge_date"])
    month = first[:7]
    second = _shift(first, 1)
    if second[:7] != month:
        second = max(_day(1), _shift(first, -1))
    results = []
    for charge_date in (first, second):
        budget.take("post")
        results.append(created_charges.create(sub_id, "CT-CO-AUTO", charge_date=charge_date))
    after = _charges(sub_id)
    autos_after = {str(c.get("id")) for c in after if _is_automatic(c) and c.get("status") == "pendiente"}
    pend_month = sum(1 for c in after if c.get("status") == "pendiente" and str(c.get("charge_date"))[:7] == month)
    claim.check("CT-CO-AUTO", DESIGN, {"manuales_aceptados": 2, "automaticos_intactos": True, "pendientes_mes": 3},
                {"manuales_aceptados": sum(r.ok and bool(provider.charge_id_of(r.body)) for r in results),
                 "automaticos_intactos": {str(c["id"]) for c in autos} <= autos_after,
                 "pendientes_mes": pend_month,
                 "errores": [r.error_code for r in results if r.error_code]},
                note="CO-01/CO-02/CO-14; medido el 2026-10-27/28 en la suscripcion previa (aceptado, sin E-087)")


# --- CT-CO-DUP: ¿se cobran ambos si no se cancela el automatico del mes? -------------------------------------------

@write_test
@pytest.mark.contract(claim="CT-CO-DUP")
def test_ct_co_dup_double_charge(claim, created_charges):
    """[CT-CO-DUP] Como CT-CO-AUTO, con el primer automatico en 1 a 2 dias. arm: crea 1 manual en la misma fecha del
    automatico y NO lo cancela. observe (pasada la fecha): estado del automatico y del manual (CO-04, doble cobro).
    Tope: 1 suscripcion, 1 cargo. Limpieza: cancela el manual si sigue pendiente; el automatico no se toca."""
    phase = _require_approval_and_phase("arm", "observe")
    state = State.load()
    if phase == "arm":
        sub_id = _dedicated_sub("CONTRACT_CT_CO_DUP_SUB")
        _active_subscription(sub_id)
        soon = [c for c in _charges(sub_id) if _is_automatic(c) and c.get("status") == "pendiente"
                and _day(1) <= str(c.get("charge_date")) <= _day(2)]
        if not soon:
            pytest.skip("La suscripcion no tiene un automatico pendiente en 1 a 2 dias.")
        auto = soon[0]
        _create_kept(Budget("CT-CO-DUP", max_posts=1), sub_id, "CT-CO-DUP", str(auto["charge_date"]), state,
                     auto_charge_id=str(auto["id"]))
        return
    entry = state.get("CT-CO-DUP")
    _wait_until_after(entry)
    auto, manual = _charge(entry["auto_charge_id"]), _charge(entry["charge_id"])
    claim.check("CT-CO-DUP", DESIGN, {"automatico": "pagado", "manual": "pagado"},
                {"automatico": auto.get("status"), "manual": manual.get("status")},
                note="hipotesis de riesgo del diseno (hallazgo 4): sin cancelar el automatico se cobran ambos")
    _close_kept(created_charges, entry)
    state.drop("CT-CO-DUP")


# --- CT-CO-NC3: cancelar los 3 automaticos de un plan corto y crear manuales --------------------------------------

@write_test
@pytest.mark.contract(claim="CT-CO-NC3")
def test_ct_co_nc3_cancel_automatics_then_manuals(claim, created_charges):
    """[CT-CO-NC3] Plan MONTO_FIJO, num_charges 3, renovacion F, tarjeta aprobada. Cancela por charge_id los 3
    automaticos pendiente (irreversible, solo en esta suscripcion dedicada) y crea manuales (CO-18, CO-19): ¿se
    aceptan? ¿la suscripcion sigue ACTIVA? Tope: 1 suscripcion, 3 cancelaciones de automaticos, 3 manuales.
    Limpieza: la sesion cancela los manuales."""
    _require_approval_and_phase("arm")
    sub_id = _dedicated_sub("CONTRACT_CT_CO_NC3_SUB")
    _active_subscription(sub_id)
    budget = Budget("CT-CO-NC3", max_posts=3, max_auto_cancels=3)
    autos = [c for c in _charges(sub_id) if _is_automatic(c) and c.get("status") == "pendiente"]
    if len(autos) != 3:
        pytest.skip(f"Se esperaban 3 automaticos pendiente (hay {len(autos)}): no es la suscripcion de la receta.")
    cancelled = []
    for auto in autos:
        budget.take("auto_cancel")
        cancelled.append(call("DELETE", f"/v3/charge/{auto['id']}"))
    created = []
    for offset in (20, 50, 80):
        budget.take("post")
        created.append(created_charges.create(sub_id, "CT-CO-NC3", days=offset))
    sub_after = _active_subscription_status(sub_id)
    claim.check("CT-CO-NC3", DESIGN,
                {"automaticos_cancelados": 3, "manuales_aceptados": 3, "suscripcion": "ACTIVA"},
                {"automaticos_cancelados": sum(r.ok for r in cancelled),
                 "manuales_aceptados": sum(r.ok and bool(provider.charge_id_of(r.body)) for r in created),
                 "suscripcion": sub_after,
                 "errores": [r.error_code for r in cancelled + created if r.error_code]},
                note="CO-18/CO-19; num_charges no limito manuales en la medicion del 2026-10-28")


def _active_subscription_status(sub_id: str) -> str | None:
    resp = call("GET", f"/v3/suscription/{sub_id}")
    body = resp.body if isinstance(resp.body, dict) else {}
    sub = body.get("suscription") if isinstance(body.get("suscription"), dict) else body
    return str(sub.get("status")) if sub.get("status") else None


# --- CT-RZ-MC y CT-RZ-SWAP: rechazos con la tarjeta de rechazo oficial ---------------------------------------------

def _arm_rejection(recipe: str, sub_var: str, confirm_var: str) -> None:
    sub_id = _dedicated_sub(sub_var)
    _env(confirm_var, "confirmacion de que una persona cambio la tarjeta a la de rechazo oficial con changecard")
    _active_subscription(sub_id)
    _create_kept(Budget(recipe, max_posts=1), sub_id, recipe, _day(1), State.load())


@write_test
@pytest.mark.contract(claim="CT-RZ-MC")
def test_ct_rz_mc_rejection_after_card_change(claim, created_charges):
    """[CT-RZ-MC] Plan MONTO_FIJO dia 0 enrolada con la tarjeta aprobada; una persona hace changecard a la tarjeta de
    rechazo oficial (CONTRACT_CT_RZ_CARD_REJECT=1 lo confirma). arm: manual a manana. observe (cada dia, hasta 4 dias
    despues de la fecha): estado del manual, uuid presente (RZ-06, RZ-07, RZ-19 T1 -> T3). /attempts da 403 en
    sandbox y no se usa. Tope: 1 suscripcion, 1 cargo. Limpieza: al cerrar la observacion, cancela si sigue pendiente."""
    phase = _require_approval_and_phase("arm", "observe")
    if phase == "arm":
        _arm_rejection("CT-RZ-MC", "CONTRACT_CT_RZ_MC_SUB", "CONTRACT_CT_RZ_CARD_REJECT")
        return
    state = State.load()
    entry = state.get("CT-RZ-MC")
    _wait_until_after(entry)
    got = _charge(entry["charge_id"])
    claim.check("CT-RZ-MC", DESIGN, {"status": "rechazado", "con_order_uuid": True},
                {"status": got.get("status"), "con_order_uuid": _has_uuid(got)},
                note="observacion diaria; la prueba se cierra 4 dias despues de la fecha")
    if _today() > _shift(entry["charge_date"], 4):
        _close_kept(created_charges, entry)
        state.drop("CT-RZ-MC")


@write_test
@pytest.mark.contract(claim="CT-RZ-SWAP")
def test_ct_rz_swap_retry_after_card_fixed(claim, created_charges):
    """[CT-RZ-SWAP] Como CT-RZ-MC. Tras el rechazo, una persona hace changecard a la tarjeta aprobada
    (CONTRACT_CT_RZ_CARD_OK=1) y la fase observe reintenta DOS veces seguidas (GET /retry sin reintento automatico)
    para medir la idempotencia y si el uuid del Payment cambia (RZ-19 T3 -> T1, RZ-20, RZ-29, RZ-30; aporta a V-4).
    Tope: 1 suscripcion, 1 cargo, 2 reintentos. Limpieza: cancela el manual si sigue pendiente."""
    phase = _require_approval_and_phase("arm", "observe")
    if phase == "arm":
        _arm_rejection("CT-RZ-SWAP", "CONTRACT_CT_RZ_SWAP_SUB", "CONTRACT_CT_RZ_CARD_REJECT")
        return
    state = State.load()
    entry = state.get("CT-RZ-SWAP")
    _wait_until_after(entry)
    before = _charge(entry["charge_id"])
    if before.get("status") != "rechazado":
        pytest.skip(f"El cargo aun no esta rechazado (estado {before.get('status')}).")
    _env("CONTRACT_CT_RZ_CARD_OK", "confirmacion de que una persona volvio a la tarjeta aprobada con changecard")
    budget = Budget("CT-RZ-SWAP", max_posts=0, max_retries=2)
    retries = []
    for _ in range(2):
        budget.take("retry")
        retries.append(_call_once("GET", f"/v3/charge/{entry['charge_id']}/retry"))
    after = _charge(entry["charge_id"])
    uuid_before, uuid_after = _payment_uuid(before), _payment_uuid(after)
    second = retries[1]
    second_body = second.body if isinstance(second.body, dict) else {}
    second_refused = not second.ok or second_body.get("status") == "NOK" or second.error_code is not None
    claim.check("CT-RZ-SWAP", DESIGN, {"estado_final": "pagado", "segundo_reintento_rechazado": True},
                {"estado_final": after.get("status"),
                 "reintentos": [_observed(r) for r in retries],
                 "segundo_reintento_rechazado": second_refused,
                 "uuid_antes": uuid_before is not None, "uuid_despues": uuid_after is not None,
                 "uuid_cambio": uuid_before != uuid_after},
                note="solo booleanos del uuid (no se guardan los uuid); idempotencia del /retry")
    _close_kept(created_charges, entry)
    state.drop("CT-RZ-SWAP")


# --- CT-CANCEL: cancelar la suscripcion con manuales pendientes ----------------------------------------------------

@write_test
@pytest.mark.contract(claim="CT-CANCEL")
def test_ct_cancel_subscription_with_pending_manuals(claim, created_charges):
    """[CT-CANCEL] Plan MONTO_FIJO, tarjeta aprobada, suscripcion dedicada. Crea 2 manuales pendiente, cancela la
    suscripcion (DELETE /v3/suscription/{id}) y luego intenta un POST (CO-20, JB-17): ¿los manuales quedan cancelados?
    ¿el POST se rechaza? Es la unica receta que cancela una suscripcion entera: exige
    CONTRACT_CT_CANCEL_CONFIRM igual al id. Tope: 1 suscripcion, 2 cargos y 1 POST que debe rechazarse.
    Limpieza: la sesion cancela lo que siga pendiente."""
    _require_approval_and_phase("arm")
    sub_id = _dedicated_sub("CONTRACT_CT_CANCEL_SUB")
    if _env("CONTRACT_CT_CANCEL_CONFIRM", "repeticion del id de la suscripcion a cancelar") != sub_id:
        pytest.skip("CONTRACT_CT_CANCEL_CONFIRM no coincide con CONTRACT_CT_CANCEL_SUB.")
    _active_subscription(sub_id)
    budget = Budget("CT-CANCEL", max_posts=3)
    manuals = []
    for offset in (20, 21):
        budget.take("post")
        manuals.append(created_charges.create(sub_id, "CT-CANCEL", days=offset))
    ids = [provider.charge_id_of(r.body) for r in manuals if provider.charge_id_of(r.body)]
    if len(ids) != 2:
        pytest.skip("No se pudieron crear los 2 manuales; no se cancela la suscripcion.")
    cancel = call("DELETE", f"/v3/suscription/{sub_id}")
    states = [_charge(cid).get("status") for cid in ids]
    budget.take("post")
    late = created_charges.create(sub_id, "CT-CANCEL", days=22)
    claim.check("CT-CANCEL", DESIGN,
                {"cancelacion": "HTTP 200", "manuales": ["cancelado", "cancelado"], "post_posterior": "rechazado"},
                {"cancelacion": _observed(cancel), "manuales": states,
                 "post_posterior": "rechazado" if not provider.charge_id_of(late.body) else "aceptado",
                 "post_posterior_error": late.error_code, "suscripcion": _active_subscription_status(sub_id)},
                note="CO-20/JB-17; si el POST posterior se acepta, el cargo queda en el registro y se cancela al final")


# --- CT-STALE: ¿VirtualPOS cobra un automatico pendiente vencido? -------------------------------------------------

@write_test
@pytest.mark.contract(claim="CT-STALE")
def test_ct_stale_overdue_pending_automatic(claim, created_charges):
    """[CT-STALE] Medicion pura del proveedor con el cliente de la suite (no usa apply_change_request ni decide DEC-30).
    Plan MONTO_FIJO, tarjeta aprobada. arm: busca un automatico `pendiente` con fecha pasada (si no hay, se omite:
    hay que esperar) y crea un manual de reemplazo a manana sin tocar el vencido. observe (pasada la fecha): estado
    del vencido y del reemplazo (JB-08). Tope: 1 cargo. Limpieza: cancela el reemplazo si sigue pendiente; el
    automatico vencido NO se cancela."""
    phase = _require_approval_and_phase("arm", "observe")
    state = State.load()
    if phase == "arm":
        sub_id = _dedicated_sub("CONTRACT_CT_STALE_SUB")
        _active_subscription(sub_id)
        stale = [c for c in _charges(sub_id) if _is_automatic(c) and c.get("status") == "pendiente"
                 and str(c.get("charge_date")) < _today()]
        if not stale:
            pytest.skip("No hay automaticos pendiente vencidos: esperar a que aparezca uno.")
        _create_kept(Budget("CT-STALE", max_posts=1), sub_id, "CT-STALE", _day(1), state,
                     stale_charge_id=str(stale[0]["id"]))
        return
    entry = state.get("CT-STALE")
    _wait_until_after(entry)
    stale, replacement = _charge(entry["stale_charge_id"]), _charge(entry["charge_id"])
    claim.check("CT-STALE", DESIGN, {"vencido": "sin afirmacion documentada", "reemplazo": "pagado"},
                {"vencido": stale.get("status"), "reemplazo": replacement.get("status")},
                matches=replacement.get("status") == "pagado",
                note="JB-08: si el vencido pasa a pagado, VirtualPOS cobra pendientes vencidos (insumo para DEC-30)")
    _close_kept(created_charges, entry)
    state.drop("CT-STALE")
