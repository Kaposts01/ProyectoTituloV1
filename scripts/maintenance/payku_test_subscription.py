"""CRM-14C: suscripcion de PRUEBA en Payku PRODUCTIVO, de monto bajo, a nombre del usuario (plan y dry-run).

Payku no tiene un sandbox usable para este proyecto; si hay productivo con llaves. Este script prepara (y, solo con
todas las llaves puestas, ejecuta) una suscripcion de prueba de monto minimo para responder preguntas abiertas de la
integracion (docs/integrations/payku/prueba-productivo.md). Por defecto NO hace red ni toca la base: imprime el plan.

Modos (todos en dry-run salvo que se indique):
  (sin modo)              plan de alta: buscar previas -> cliente -> plan -> suscripcion -> inscribir tarjeta.
  --find-existing         plan de LECTURAS para buscar suscripciones previas por correo/RUT. Con --execute-read
                          las ejecuta (solo GET; igual exige --confirm-production por ser productivo).
  --verify SUB_ID         plan de LECTURAS posteriores (detalle, V3 del dia, transacciones del dia). --execute-read.
  --cancel SUB_ID         plan de baja (DELETE /api/sususcription/{id}). Con --apply la ejecuta.

Plan de CONSUMO (ficha d213 = b: el plan queda PERMANENTE en la cuenta; solo se cancela la suscripcion):
  --consumption           alta: buscar previas -> cliente -> plan de consumo -> suscripcion (sin amount) -> url de
                          inscripcion (paso MANUAL del titular; Payku cobra $50 de validacion). Exige --create-plan
                          (POST /api/suplan con --plan-name, default PRUEBA-CRM-1CLP, sin url_notify) o --plan-id.
  --charge SUB_ID         cobro unico por POST /api/sutransaction (suscription, amount, order, description). Antes
                          lee la suscripcion y se niega si no esta 'active' (tarjeta sin inscribir). Con --apply.
  --verify-consumption SUB_ID
                          lecturas para Q-06 (aparece en GET /api/transaction y, con --conciliation-date, en
                          POST /api/conciliation, una CONSULTA aunque sea POST), Q-08 (clave estable: id de la
                          respuesta del cobro vs listado vs transactions[] de la sub) y Q-33 (se distingue el cobro de
                          consumo de uno recurrente). --transaction-id con el id que devolvio --charge. --execute-read.
  Exclusion de indicadores (d207, implementada): el id su... de la suscripcion se conoce al crearla; el alta lo
  imprime con la linea PAYKU_KPI_EXCLUDED_IDS=... a cargar en el .env del CRM ANTES del siguiente sync y antes de
  --charge (sus cobros quedan fuera por su suscripcion). --charge avisa si el id no esta en la lista configurada.
  --apply                 ejecuta las ESCRITURAS del alta (o de --cancel). Exige TODO lo siguiente:
                            * --confirm-production
                            * variable de PROCESO PAYKU_TEST_SUBSCRIPTION_ARMED=1 (no va en .env)
                            * APP_ENV productivo y PAYKU_BASE_URL con host app.payku.cl (ruta de produccion del CRM)
                            * PAYKU_WRITES_ENABLED=true (apagado por defecto: si sigue apagado, el script se niega)
                            * --rut, --email, --phone y --name explicitos (el RUT no tiene valor por defecto)
                          Cada escritura queda en `write_runs` (source=payku, operation=test_subscription.*).

Costos segun la doc oficial (docs.payku.com/cl, "Crear suscripcion"): "al realizar esta solicitud por primera vez se
realizara un cobro de $50 que permite comprobar que la tarjeta se encuentra activa y es valida". La doc NO publica un
monto minimo en CLP para planes ni suscripciones (solo para PEN). Meta del usuario: total <= 51 CLP -> monto 1 CLP.

Uso (PowerShell, desde la raiz del repo):
  .venv\\Scripts\\python.exe -m scripts.maintenance.payku_test_subscription --rut 11111111-1 --email a@b.cl \\
      --phone 900000000 --name "Nombre Apellido" --plan-id plXXXX
Nunca imprime llaves ni la firma; el correo y el RUT salen enmascarados.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ARM_ENV = "PAYKU_TEST_SUBSCRIPTION_ARMED"
PRODUCTION_HOST = "app.payku.cl"
VALIDATION_CHARGE_CLP = 50  # doc oficial, "Crear suscripcion" (payku-docs-es.md L4102)
DEFAULT_AMOUNT_CLP = 1
DEFAULT_MAX_TOTAL_CLP = 51
TEST_MARKER = "CRM-14C"
CONSUMPTION_PLAN_NAME = "PRUEBA-CRM-1CLP"
ORDER_MAX = 40  # doc: sutransaction -> order maximo 40 caracteres
KPI_EXCLUDED_ENV = "PAYKU_KPI_EXCLUDED_IDS"
PLAN_NAME_MAX = 20  # doc: "Crear plan" -> name maximo 20 caracteres
EMAIL_PATH_MAX = 20  # doc: "Obtener cliente" -> id o email, maximo 20 caracteres (Q-10: no confirmado)
CUSTOMERS_PER_PAGE = 100  # doc: "Obtener clientes" -> maximo 100 por pagina
CHILE = ZoneInfo("America/Santiago")


class ArmingError(Exception):
    """Falta una de las llaves para escribir en productivo. El mensaje nombra la llave, nunca valores."""


@dataclass
class Step:
    key: str
    method: str
    path: str
    body: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    cost_clp: int = 0
    note: str = ""
    write: bool = False
    manual: bool = False


@dataclass
class Plan:
    title: str
    steps: list[Step] = field(default_factory=list)
    total_clp: int = 0
    warnings: list[str] = field(default_factory=list)
    cost_lines: list[str] = field(default_factory=list)  # si hay, reemplazan la linea generica de costo total


# --------------------------------------------------------------------------------------------------------------------
# Datos personales: siempre enmascarados al imprimir y al guardar en write_runs
# --------------------------------------------------------------------------------------------------------------------


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def mask_rut(rut: str) -> str:
    clean = rut.replace(".", "").strip()
    return f"***{clean[-5:]}" if len(clean) > 5 else "***"


def mask_phone(phone: str) -> str:
    return f"***{phone[-3:]}" if len(phone) > 3 else "***"


def _masked_body(body: dict[str, Any] | None) -> dict[str, Any] | None:
    if body is None:
        return None
    out = dict(body)
    if isinstance(out.get("email"), str):
        out["email"] = mask_email(out["email"])
    if isinstance(out.get("rut"), str):
        out["rut"] = mask_rut(out["rut"])
    if isinstance(out.get("phone"), str):
        out["phone"] = mask_phone(out["phone"])
    if isinstance(out.get("name"), str) and "client_name" not in out and "description" not in out:
        out["name"] = out["name"][:1] + "***" if out["name"] else out["name"]
    return out


def _masked_path(path: str, email: str | None) -> str:
    return path.replace(email, mask_email(email)) if email else path


# --------------------------------------------------------------------------------------------------------------------
# Planes de llamadas (puros: sin red ni base)
# --------------------------------------------------------------------------------------------------------------------


def plan_name(today: date) -> str:
    return f"CRM TEST {today:%y%m%d}"[:PLAN_NAME_MAX]


def find_existing_steps(email: str | None, rut: str | None) -> list[Step]:
    """Solo lecturas. Payku no documenta busqueda por RUT: se recorre el listado de clientes y se filtra en local."""
    steps: list[Step] = []
    if email:
        note = "detalle del cliente por correo (incluye sus suscripciones)"
        if len(email) > EMAIL_PATH_MAX:
            note += f"; ojo: la doc limita el id a {EMAIL_PATH_MAX} caracteres (Q-10)"
        steps.append(Step("read_client_by_email", "GET", f"/api/suclient/{email}", note=note))
    steps.append(
        Step(
            "read_customers",
            "GET",
            "/api/suclient/customers",
            params={"page": 1, "per_page": CUSTOMERS_PER_PAGE},
            note="listado paginado; se filtra en local por correo y RUT (la doc no ofrece filtro por RUT; sin fecha "
            "Payku toma la fecha actual, Q-12)",
        )
    )
    steps.append(
        Step(
            "read_subscriptions_v3",
            "GET",
            "/api/sususcriptionv3",
            params={"page": 1, "per_page": 4000, "date_init": "2020-01-01", "date_end": "<hoy>"},
            note="se filtran en local las suscripciones cuyo cliente coincide (Q-11: no se sabe sobre que fecha filtra)",
        )
    )
    return steps


def build_create_plan(args: argparse.Namespace, today: date) -> Plan:
    plan = Plan("Alta de suscripcion de prueba en Payku PRODUCTIVO")
    amount = int(args.amount)
    total = VALIDATION_CHARGE_CLP + amount
    plan.total_clp = total
    if total > args.max_total:
        plan.warnings.append(f"el total estimado {total} CLP supera el tope {args.max_total} CLP")

    plan.steps.extend(find_existing_steps(args.email, args.rut))
    plan.steps.append(
        Step(
            "create_client",
            "POST",
            "/api/suclient",
            body={"email": args.email or "<correo>", "name": args.name or "<nombre>", "rut": args.rut or "<RUT>",
                  "phone": args.phone or "<telefono>"},
            note="se omite si la busqueda previa encuentra el cliente por correo (se reutiliza su id cl...)",
            write=True,
        )
    )
    if args.plan_id:
        plan.steps.append(Step("read_plan", "GET", f"/api/suplan/{args.plan_id}", note="plan existente indicado con --plan-id"))
        plan_ref = args.plan_id
    else:
        name = plan_name(today)
        plan.steps.append(
            Step(
                "create_plan",
                "POST",
                "/api/suplan",
                body={"name": name, "description": f"{TEST_MARKER} prueba CRM; no es un socio real"},
                note="la doc solo documenta 'Crear plan' en Suscripcion de consumo y su body no tiene monto ni tipo: el "
                "tipo del plan creado asi NO esta confirmado. Para un plan de monto VARIABLE, crealo en el panel y "
                "pasa --plan-id",
                write=True,
            )
        )
        plan.warnings.append("sin --plan-id el plan se crea por API y su tipo (fijo/variable/consumo) no esta documentado")
        plan_ref = "<id del plan>"
    plan.steps.append(
        Step(
            "create_subscription",
            "POST",
            "/api/sususcription",
            body={"plan": plan_ref, "client": "<id del cliente>", "amount": str(amount)},
            cost_clp=0,
            note="responde {status: register, id: su..., url}; 'amount' solo aplica a planes de monto variable (CLP)",
            write=True,
        )
    )
    plan.steps.append(
        Step(
            "enroll_card",
            "BROWSER",
            "<url de la respuesta: /gateway/registrosuscripcion?...>",
            cost_clp=VALIDATION_CHARGE_CLP,
            note="el titular abre la url e inscribe su tarjeta: Payku cobra $50 de validacion (doc). Si el plan "
            "variable cobra al activar (Q-27) se suma el monto ahora; si no, el primer cobro es el mes siguiente",
            manual=True,
        )
    )
    plan.steps.append(
        Step(
            "monthly_charge",
            "AUTO",
            "(cobro recurrente de Payku)",
            cost_clp=amount,
            note="cobro del monto de la suscripcion (al activar o el mes siguiente, Q-27). Cancelar con --cancel antes "
            "del siguiente ciclo para no pagar mas",
            manual=True,
        )
    )
    return plan


def build_verify_plan(sub_id: str, today: date) -> Plan:
    day = today.isoformat()
    plan = Plan("Lecturas posteriores a la prueba (solo GET)")
    plan.steps = [
        Step("read_subscription", "GET", f"/api/sususcription/{sub_id}", note="estado, tarjeta, transactions[] (Q-27)"),
        Step("read_subscriptions_v3_today", "GET", "/api/sususcriptionv3",
             params={"page": 1, "per_page": 100, "date_init": day, "date_end": day},
             note="la sub creada hoy debe aparecer; repetir con una ventana que la excluya (Q-11)"),
        Step("read_transactions_today", "GET", "/api/transaction",
             params={"page": 1, "per_page": 100, "date_init": day, "date_end": day},
             note="buscar el cobro de $50 y el del monto (Q-06, Q-08)"),
    ]
    return plan


def build_cancel_plan(sub_id: str) -> Plan:
    plan = Plan("Baja de la suscripcion de prueba")
    plan.steps = [
        Step("cancel_subscription", "DELETE", f"/api/sususcription/{sub_id}",
             note="doc: 'Eliminar suscripcion' -> {id, status: success}. Estado final delete/cancel por confirmar (Q-13)",
             write=True),
        Step("read_subscription_after_cancel", "GET", f"/api/sususcription/{sub_id}", note="confirmar el estado final"),
    ]
    return plan


def consumption_order(today: date) -> str:
    return f"CRM14C-CONSUMO-{today:%y%m%d}"[:ORDER_MAX]


def consumption_plan_body(name: str) -> dict[str, Any]:
    """Solo name y description: sin url_notify_* (no se notifica al CRM; la prueba se lee por GET)."""
    return {"name": name, "description": f"{TEST_MARKER} plan de consumo de PRUEBA del CRM; no es un socio real"}


def build_consumption_plan(args: argparse.Namespace, today: date) -> Plan:
    plan = Plan("Alta de suscripcion de CONSUMO de prueba en Payku PRODUCTIVO")
    amount = int(args.amount)
    plan.total_clp = amount
    plan.cost_lines = consumption_cost_lines(amount, args.max_total)
    if VALIDATION_CHARGE_CLP + amount > args.max_total:
        plan.warnings.append(f"el peor caso {VALIDATION_CHARGE_CLP + amount} CLP supera el tope {args.max_total} CLP")
    plan.steps.extend(find_existing_steps(args.email, args.rut))
    plan.steps.append(
        Step("create_client", "POST", "/api/suclient",
             body={"email": args.email or "<correo>", "name": args.name or "<nombre>", "rut": args.rut or "<RUT>",
                   "phone": args.phone or "<telefono>"},
             note="se omite si la busqueda previa encuentra el cliente por correo o RUT (se reutiliza su id cl...)",
             write=True)
    )
    if args.plan_id:
        plan.steps.append(Step("read_plan", "GET", f"/api/suplan/{args.plan_id}", note="plan de consumo existente"))
        plan_ref = args.plan_id
    else:
        plan.steps.append(
            Step("create_plan", "POST", "/api/suplan", body=consumption_plan_body(args.plan_name),
                 note="doc: 'Crear plan' (seccion Suscripcion de consumo) -> {status, id: pl...}. El plan queda "
                 "PERMANENTE (d213 = b). El body no tiene tipo: que sea de consumo se confirma con la lectura siguiente",
                 write=True)
        )
        plan.steps.append(Step("read_plan", "GET", "/api/suplan/<id del plan>",
                               note="confirmar nombre y estado del plan creado (no hay campo de tipo documentado)"))
        plan_ref = "<id del plan>"
    plan.steps.append(
        Step("create_subscription", "POST", "/api/sususcription", body={"plan": plan_ref, "client": "<id del cliente>"},
             note="sin amount (solo aplica a monto variable); responde {status: register, id: su..., url}", write=True)
    )
    plan.steps.append(
        Step("enroll_card", "BROWSER", "<url de la respuesta: /gateway/registrosuscripcion?...>",
             note="paso MANUAL del titular: inscribe su tarjeta y la suscripcion queda 'active'. Costo esperado 0 CLP "
             "(sin amount ni monto de plan; ver el costo al final). Un plan de consumo no cobra solo: el cobro lo "
             "genera --charge", manual=True)
    )
    plan.steps.append(
        Step("consumption_charge", "POST", "/api/sutransaction",
             body={"suscription": "<id su...>", "amount": str(amount), "order": consumption_order(today),
                   "description": f"{TEST_MARKER} cobro de consumo de prueba"},
             cost_clp=amount, note="se ejecuta aparte con --charge SUB_ID una vez inscrita la tarjeta", write=True)
    )
    plan.steps.append(Step("verify", "GET", "(ver --verify-consumption SUB_ID)", note="lecturas Q-06, Q-08, Q-33"))
    plan.steps.append(Step("cancel", "DELETE", "/api/sususcription/<id su...>",
                           note="con --cancel SUB_ID al terminar; el plan NO se borra (d213 = b)", write=True))
    plan.warnings.append(f"el alta imprime el id su...: cargarlo en {KPI_EXCLUDED_ENV} del .env del CRM antes del "
                         "siguiente sync y antes de --charge (seccion 5 de prueba-productivo.md)")
    return plan


def consumption_cost_lines(amount: int, max_total: int) -> list[str]:
    """Texto del costo del modo --consumption (dry-run). Puro.

    Base: el historial del CRM muestra que Payku cobra al ACTIVAR el monto completo de la suscripcion; en un plan de
    consumo la suscripcion se crea sin `amount` y el plan no tiene monto, asi que al activar se espera 0. La doc
    (Crear suscripcion, L4102) anuncia ademas una validacion de $50 que no aparece en los datos: queda como caso dudoso.
    """
    worst = VALIDATION_CHARGE_CLP + amount
    return [
        "Costo esperado (plan de CONSUMO, suscripcion sin amount):",
        "  - al activar (inscribir la tarjeta): 0 CLP. Segun el historial, Payku cobra al activar el monto completo de",
        "    la suscripcion; esta no tiene amount y el plan de consumo no tiene monto: no hay monto que cobrar.",
        f"  - cobro de consumo (--charge): {amount} CLP.",
        f"  - TOTAL ESPERADO: {amount} CLP.",
        f"Caso dudoso: la doc (Crear suscripcion, L4102) anuncia una validacion de ${VALIDATION_CHARGE_CLP} al inscribir",
        "  la tarjeta que NO aparece en los datos de transacciones del CRM; tambien podria haber un cobro inicial de 0",
        f"  o 1 CLP. Rango probable: {amount} a {amount + 1} CLP; peor caso {worst} CLP (validacion + cobro),",
        f"  {'dentro' if worst <= max_total else 'FUERA'} del tope --max-total {max_total} CLP.",
        "  La lectura --verify-consumption del mismo dia dice cual fue (q15_cargo_50_en_listado).",
    ]


def configured_excluded_ids(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Ids de PAYKU_KPI_EXCLUDED_IDS: de la configuracion del CRM y, si no carga, del entorno del proceso."""
    try:
        from app.core.config import settings

        return settings.payku_kpi_excluded_id_set
    except Exception:  # noqa: BLE001 - sin configuracion cargable, el entorno del proceso
        raw = (env if env is not None else os.environ).get(KPI_EXCLUDED_ENV, "")
        return frozenset(i.strip() for i in raw.split(",") if i.strip())


def exclusion_warning(sub_id: str, excluded: frozenset[str]) -> str | None:
    if sub_id in excluded:
        return None
    return (f"{sub_id} NO esta en {KPI_EXCLUDED_ENV}: el cobro entraria a los indicadores. Agregarlo al .env del CRM "
            "antes del --charge y del siguiente sync")


def build_charge_plan(sub_id: str, args: argparse.Namespace, today: date,
                      excluded: frozenset[str] | None = None) -> Plan:
    amount = int(args.amount)
    plan = Plan("Cobro unico de CONSUMO de prueba (Payku PRODUCTIVO)")
    plan.total_clp = amount
    plan.steps = [
        Step("read_subscription_before_charge", "GET", f"/api/sususcription/{sub_id}",
             note="debe estar 'active' (tarjeta inscrita); si no, el script se niega a cobrar"),
        Step("consumption_charge", "POST", "/api/sutransaction",
             body={"suscription": sub_id, "amount": str(amount), "order": consumption_order(today),
                   "description": f"{TEST_MARKER} cobro de consumo de prueba"},
             cost_clp=amount,
             note="doc L4511: obligatorio solo 'suscription'; amount/order/description opcionales pero se envian. "
             "Responde {status, order, amount, transaction_id, verification_key}. Minimo en CLP no documentado",
             write=True),
    ]
    if amount + VALIDATION_CHARGE_CLP > args.max_total:
        plan.warnings.append(f"el monto {amount} CLP mas la validacion supera el tope {args.max_total} CLP")
    if excluded is not None and (warning := exclusion_warning(sub_id, excluded)):
        plan.warnings.append(warning)
    return plan


def build_verify_consumption_plan(sub_id: str, tx_id: str | None, today: date, conciliation_date: str | None) -> Plan:
    day = today.isoformat()
    plan = Plan("Lecturas de la prueba de consumo (Q-06, Q-08, Q-33)")
    plan.steps = [
        Step("read_subscription", "GET", f"/api/sususcription/{sub_id}",
             note="transactions[]: aparece el cobro de consumo? con que clave y descripcion (Q-08, Q-33)"),
        Step("read_transactions_today", "GET", "/api/transaction",
             params={"page": 1, "per_page": 100, "date_init": day, "date_end": day},
             note="Q-06: aparece el cobro de consumo en el listado general? y el de $50 (Q-15)?"),
    ]
    if tx_id:
        plan.steps.append(Step("read_transaction", "GET", f"/api/transaction/{tx_id}",
                               note="Q-08: el transaction_id devuelto por sutransaction resuelve aqui?"))
    if conciliation_date:
        plan.steps.append(Step("read_conciliation", "POST", "/api/conciliation",
                               body={"date_init": conciliation_date, "date_end": conciliation_date},
                               note="CONSULTA (no mueve dinero) aunque sea POST; Q-06: el abono aparece en la "
                               "conciliacion del dia de deposito (rango <= 30 dias, no futuro)"))
    return plan


def _tx_records(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("transactions", "data", "conciliations", "items"):
        value = body.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
    return []


def _key_values(record: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("transaction_id", "transaction", "id", "order"):
        value = record.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            out[key] = str(value)
    return out


def analyze_consumption(charge: dict[str, Any] | None, subscription: Any, transactions: Any,
                        conciliation: Any = None) -> dict[str, Any]:
    """Pura. Resume Q-06/Q-08/Q-33 a partir de lo leido; nombra campos, nunca datos personales."""
    wanted = set(_key_values(charge or {}).values())

    def hits(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in records if wanted & set(_key_values(r).values())]

    in_sub = hits(_tx_records(subscription.get("transactions") if isinstance(subscription, dict) else None))
    list_txs = _tx_records(transactions)
    in_list = hits(list_txs)
    in_conc = hits(_tx_records(conciliation)) if conciliation is not None else None
    matched_fields = sorted({k for r in in_sub + in_list for k, v in _key_values(r).items() if v in wanted})
    descriptions = sorted({str(r.get("description") or "") for r in in_sub + in_list})
    return {
        "q06_en_transaction": bool(in_list),
        "q06_en_conciliacion": None if in_conc is None else bool(in_conc),
        "q08_campos_que_coinciden": matched_fields,
        "q08_en_transactions_de_la_sub": bool(in_sub),
        "q33_descripciones": descriptions,
        "q33_parece_recurrente": any("Cobro:" in d for d in descriptions),
        "q15_cargo_50_en_listado": any(str(r.get("amount")).split(".")[0] == str(VALIDATION_CHARGE_CLP)
                                       for r in list_txs),
    }


def kpi_exclusion_line(*ids: str | None) -> str:
    clean = [i for i in ids if i]
    return f"{KPI_EXCLUDED_ENV}={','.join(clean)}  (agregar a la lista vigente; ver prueba-productivo.md seccion 5)"


def render_plan(plan: Plan, email: str | None = None) -> str:
    lines = [f"== {plan.title} (DRY-RUN: sin red, sin base) =="]
    for i, step in enumerate(plan.steps, 1):
        kind = "ESCRITURA" if step.write else ("MANUAL" if step.manual else "lectura")
        lines.append(f"{i}. [{kind}] {step.method} {_masked_path(step.path, email)}")
        if step.params:
            lines.append(f"     params: {step.params}")
        if step.body is not None:
            lines.append(f"     body:   {_masked_body(step.body)}")
        if step.cost_clp:
            lines.append(f"     costo:  {step.cost_clp} CLP")
        if step.note:
            lines.append(f"     nota:   {step.note}")
    if plan.cost_lines:
        lines.extend(plan.cost_lines)
    elif plan.total_clp:
        with_validation = any(s.manual and s.cost_clp == VALIDATION_CHARGE_CLP for s in plan.steps)
        detail = f" ({VALIDATION_CHARGE_CLP} de validacion + monto)" if with_validation else " (solo el monto del cobro)"
        lines.append(f"Costo total estimado: {plan.total_clp} CLP{detail}")
    for warning in plan.warnings:
        lines.append(f"AVISO: {warning}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------------------------
# Armado (llaves) — puro, recibe settings y el entorno del proceso
# --------------------------------------------------------------------------------------------------------------------


def check_armed(args: argparse.Namespace, settings: Any, env: Mapping[str, str], *, cancel: bool) -> None:
    if not args.confirm_production:
        raise ArmingError("falta --confirm-production")
    if env.get(ARM_ENV) != "1":
        raise ArmingError(f"falta la variable de proceso {ARM_ENV}=1")
    if not getattr(settings, "is_production", False):
        raise ArmingError("APP_ENV no es productivo: este script usa solo la ruta de escritura de produccion")
    host = (urlparse(str(getattr(settings, "payku_base_url", "") or "")).hostname or "").lower()
    if host != PRODUCTION_HOST:
        raise ArmingError(f"PAYKU_BASE_URL no apunta a {PRODUCTION_HOST}")
    if not getattr(settings, "payku_writes_enabled", False):
        raise ArmingError("PAYKU_WRITES_ENABLED esta apagado")
    if cancel:
        return
    if getattr(args, "charge", None):
        if VALIDATION_CHARGE_CLP + int(args.amount) > args.max_total:
            raise ArmingError(f"el monto del cobro mas la validacion supera --max-total ({args.max_total} CLP)")
        return
    if getattr(args, "consumption", False) and not (args.create_plan or args.plan_id):
        raise ArmingError("el modo --consumption exige --create-plan o --plan-id")
    missing =[flag for flag, value in (("--rut", args.rut), ("--email", args.email), ("--phone", args.phone),
                                        ("--name", args.name)) if not value]
    if missing:
        raise ArmingError("faltan parametros obligatorios: " + ", ".join(missing))
    total = VALIDATION_CHARGE_CLP + int(args.amount)
    if total > args.max_total:
        raise ArmingError(f"el total estimado supera --max-total ({args.max_total} CLP)")


def check_read_allowed(args: argparse.Namespace) -> None:
    if not args.confirm_production:
        raise ArmingError("las lecturas contra productivo exigen --confirm-production")


# --------------------------------------------------------------------------------------------------------------------
# Ejecucion (solo con --apply / --execute-read). Inyectable para tests.
# --------------------------------------------------------------------------------------------------------------------


def _ids_from(response: Any, *keys: str) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in keys:
        value = response.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, dict):
            nested = value.get("id")
            if isinstance(nested, str) and nested:
                return nested
    return None


def _norm_rut(value: Any) -> str:
    return str(value or "").replace(".", "").replace("-", "").strip().lower()


def matches_person(record: Any, email: str | None, rut: str | None) -> bool:
    if not isinstance(record, dict):
        return False
    if email and str(record.get("email") or "").strip().lower() == email.strip().lower():
        return True
    return bool(rut) and _norm_rut(record.get("rut")) == _norm_rut(rut)


class WriteRecorder:
    """Registra cada escritura en `write_runs` (pending -> completed/failed)."""

    def __init__(self, session: Any, write_run_cls: Any, sanitize: Callable[[Any], Any]) -> None:
        self.session = session
        self.write_run_cls = write_run_cls
        self.sanitize = sanitize

    def start(self, step: Step, resource_type: str, external_id: str) -> Any:
        run = self.write_run_cls(
            source="payku",
            resource_type=resource_type,
            external_id=external_id,
            operation=f"test_subscription.{step.key}",
            status="pending",
            request_payload={"marker": TEST_MARKER, "method": step.method, "path": step.path,
                             "body": _masked_body(step.body)},
        )
        self.session.add(run)
        self.session.commit()
        return run

    def finish(self, run: Any, response: Any, *, external_id: str | None = None) -> None:
        run.status = "completed"
        if external_id:
            run.external_id = external_id
        run.response_payload = self.sanitize(_masked_body(response) if isinstance(response, dict) else {"raw": str(response)[:200]})
        run.finished_at = datetime.now(UTC)
        self.session.commit()

    def fail(self, run: Any, exc: Exception, secrets: tuple[str, ...]) -> None:
        from app.services.read_only_provider_sync import safe_error_message

        run.status = "failed"
        run.error_message = safe_error_message(exc, secrets)
        run.finished_at = datetime.now(UTC)
        self.session.commit()


async def _write(recorder: WriteRecorder, step: Step, resource_type: str, external_id: str,
                 call: Callable[[], Any], secrets: tuple[str, ...], id_keys: tuple[str, ...] = ("id",)) -> Any:
    run = recorder.start(step, resource_type, external_id)
    try:
        response = await call()
    except Exception as exc:
        recorder.fail(run, exc, secrets)
        raise
    recorder.finish(run, response, external_id=_ids_from(response, *id_keys))
    return response


async def find_existing(provider: Any, email: str | None, rut: str | None) -> dict[str, Any]:
    """Solo GET. Devuelve el id del cliente encontrado y las suscripciones (id, estado) que coinciden."""
    found: dict[str, Any] = {"client_id": None, "subscriptions": []}
    if email:
        try:
            body = await provider.get_client(email)
        except Exception:  # noqa: BLE001 - 404/limite de 20 caracteres (Q-10): se recorre el listado
            body = None
        client = body.get("client") if isinstance(body, dict) and isinstance(body.get("client"), dict) else body
        if matches_person(client, email, None):
            found["client_id"] = _ids_from(client, "id")
    page = 1
    while found["client_id"] is None and page <= 50:
        body = await provider.list_clients(page=page, per_page=CUSTOMERS_PER_PAGE)
        records = body.get("customers") or body.get("clients") or body.get("data") or [] if isinstance(body, dict) else []
        if not records:
            break
        hit = next((r for r in records if matches_person(r, email, rut)), None)
        if hit:
            found["client_id"] = _ids_from(hit, "id")
        page += 1
    if found["client_id"]:
        body = await provider.list_subscriptions_v3(page=1, per_page=4000, date_init="2020-01-01",
                                                    date_end=datetime.now(CHILE).date().isoformat())
        subs = body.get("suscriptions") or body.get("data") or [] if isinstance(body, dict) else []
        for sub in subs if isinstance(subs, list) else []:
            client = sub.get("client") if isinstance(sub, dict) else None
            client_id = client.get("id") if isinstance(client, dict) else (sub.get("client") if isinstance(sub, dict) else None)
            if client_id == found["client_id"]:
                found["subscriptions"].append({"id": sub.get("id"), "status": sub.get("status")})
    return found


async def apply_create(args: argparse.Namespace, provider: Any, recorder: WriteRecorder, secrets: tuple[str, ...],
                       today: date) -> dict[str, Any]:
    plan = build_create_plan(args, today)
    steps = {s.key: s for s in plan.steps}
    existing = await find_existing(provider, args.email, args.rut)
    active = [s for s in existing["subscriptions"] if str(s.get("status") or "").lower() in ("active", "register")]
    if active:
        raise ArmingError("ya existe una suscripcion activa o en registro para esa persona: no se crea otra")

    client_id = existing["client_id"]
    if client_id is None:
        step = steps["create_client"]
        step.body = {"email": args.email, "name": args.name, "rut": args.rut, "phone": args.phone}
        response = await _write(recorder, step, "client", f"pending:{TEST_MARKER}",
                                lambda: provider.create_client(step.body), secrets, ("id", "client"))
        client_id = _ids_from(response, "id", "client")
        if not client_id:
            raise RuntimeError("Payku no devolvio el id del cliente")

    plan_id = args.plan_id
    if not plan_id:
        step = steps["create_plan"]
        response = await _write(recorder, step, "plan", f"pending:{TEST_MARKER}",
                                lambda: provider.create_plan(step.body), secrets, ("id", "plan", "plans"))
        plan_id = _ids_from(response, "id", "plan", "plans")
        if not plan_id:
            raise RuntimeError("Payku no devolvio el id del plan")

    step = steps["create_subscription"]
    step.body = {"plan": plan_id, "client": client_id, "amount": str(int(args.amount))}
    response = await _write(recorder, step, "subscription", f"pending:{TEST_MARKER}",
                            lambda: provider.create_subscription(step.body), secrets, ("id",))
    return {"client_id": client_id, "plan_id": plan_id, "subscription_id": _ids_from(response, "id"),
            "status": response.get("status") if isinstance(response, dict) else None,
            "enroll_url": response.get("url") if isinstance(response, dict) else None}


async def apply_create_consumption(args: argparse.Namespace, provider: Any, recorder: WriteRecorder,
                                   secrets: tuple[str, ...], today: date) -> dict[str, Any]:
    plan = build_consumption_plan(args, today)
    steps = {s.key: s for s in plan.steps}
    existing = await find_existing(provider, args.email, args.rut)
    active = [s for s in existing["subscriptions"] if str(s.get("status") or "").lower() in ("active", "register")]
    if active:
        raise ArmingError("ya existe una suscripcion activa o en registro para esa persona: no se crea otra")

    client_id = existing["client_id"]
    if client_id is None:
        step = steps["create_client"]
        step.body = {"email": args.email, "name": args.name, "rut": args.rut, "phone": args.phone}
        response = await _write(recorder, step, "client", f"pending:{TEST_MARKER}",
                                lambda: provider.create_client(step.body), secrets, ("id", "client"))
        client_id = _ids_from(response, "id", "client")
        if not client_id:
            raise RuntimeError("Payku no devolvio el id del cliente")

    plan_id = args.plan_id
    if not plan_id:
        step = steps["create_plan"]
        response = await _write(recorder, step, "plan", f"pending:{TEST_MARKER}",
                                lambda: provider.create_plan(step.body), secrets, ("id", "plan", "plans"))
        plan_id = _ids_from(response, "id", "plan", "plans")
        if not plan_id:
            raise RuntimeError("Payku no devolvio el id del plan")
    try:
        plan_detail = await provider.get_plan(plan_id)
    except Exception:  # noqa: BLE001 - lectura informativa: el plan ya existe
        plan_detail = None

    step = steps["create_subscription"]
    step.body = {"plan": plan_id, "client": client_id}
    response = await _write(recorder, step, "subscription", f"pending:{TEST_MARKER}",
                            lambda: provider.create_subscription(step.body), secrets, ("id",))
    sub_id = _ids_from(response, "id")
    return {"client_id": client_id, "plan_id": plan_id, "plan_detail": plan_detail, "subscription_id": sub_id,
            "status": response.get("status") if isinstance(response, dict) else None,
            "enroll_url": response.get("url") if isinstance(response, dict) else None,
            "kpi_exclusion": kpi_exclusion_line(sub_id),
            "recordatorio": f"agregar {sub_id} a {KPI_EXCLUDED_ENV} en el .env del CRM ANTES del siguiente sync y de "
                            "--charge (d207)"}


async def apply_charge(sub_id: str, args: argparse.Namespace, provider: Any, recorder: WriteRecorder,
                       secrets: tuple[str, ...], today: date,
                       excluded: frozenset[str] | None = None) -> dict[str, Any]:
    warning = exclusion_warning(sub_id, configured_excluded_ids() if excluded is None else excluded)
    if warning:
        print(f"AVISO: {warning}")
    sub = await provider.get_subscription(sub_id)
    status = str(sub.get("status") or "").lower() if isinstance(sub, dict) else ""
    if status != "active":
        raise ArmingError(f"la suscripcion no esta 'active' (estado: {status or 'desconocido'}): no se cobra")
    step = build_charge_plan(sub_id, args, today).steps[1]
    response = await _write(recorder, step, "transaction", sub_id,
                            lambda: provider.create_consumption_transaction(step.body), secrets,
                            ("transaction_id", "id"))
    tx_id = _ids_from(response, "transaction_id", "id")
    out = {key: response.get(key) for key in ("status", "order", "amount", "transaction_id")} \
        if isinstance(response, dict) else {"raw": str(response)[:200]}
    out["transaction_id"] = out.get("transaction_id") or tx_id
    out["kpi_exclusion"] = kpi_exclusion_line(sub_id)  # el cobro queda fuera por su suscripcion
    out["kpi_excluded"] = warning is None
    return out


async def verify_consumption(sub_id: str, tx_id: str | None, provider: Any, today: date,
                             conciliation_date: str | None) -> dict[str, Any]:
    """Solo lecturas (y la CONSULTA POST /api/conciliation si se pide fecha)."""
    day = today.isoformat()
    sub = await provider.get_subscription(sub_id)
    txs = await provider.list_transactions(date_init=day, date_end=day, page=1, per_page=100)
    single = None
    if tx_id:
        try:
            single = await provider.get_transaction(tx_id)
        except Exception:  # noqa: BLE001 - que no resuelva es justamente un hallazgo de Q-08
            single = None
    conciliation = None
    if conciliation_date:
        conciliation = await provider.get_conciliations({"date_init": conciliation_date, "date_end": conciliation_date})
    charge = {"transaction_id": tx_id} if tx_id else None
    analysis = analyze_consumption(charge, sub, txs, conciliation)
    analysis["q08_get_transaction_por_id_resuelve"] = None if not tx_id else isinstance(single, dict) and bool(single)
    return analysis


async def apply_cancel(sub_id: str, provider: Any, recorder: WriteRecorder, secrets: tuple[str, ...]) -> Any:
    step = build_cancel_plan(sub_id).steps[0]
    response = await _write(recorder, step, "subscription", sub_id, lambda: provider.delete_subscription(sub_id), secrets)
    try:
        after = await provider.get_subscription(sub_id)
    except Exception:  # noqa: BLE001 - la baja ya quedo registrada; la relectura es solo informativa
        after = None
    return {"cancel": response, "after": after}


# --------------------------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--rut", help="RUT del titular (obligatorio con --apply; sin valor por defecto)")
    parser.add_argument("--email", help="correo del titular (obligatorio con --apply)")
    parser.add_argument("--phone", help="telefono del titular (Payku lo exige al crear el cliente)")
    parser.add_argument("--name", help="nombre del titular")
    parser.add_argument("--plan-id", help="plan de monto VARIABLE ya creado en el panel de Payku (recomendado)")
    parser.add_argument("--amount", type=int, default=DEFAULT_AMOUNT_CLP, help="monto de la suscripcion en CLP (default 1)")
    parser.add_argument("--max-total", type=int, default=DEFAULT_MAX_TOTAL_CLP, help="tope de costo total (default 51)")
    parser.add_argument("--find-existing", action="store_true", help="plan de lecturas para buscar subs previas")
    parser.add_argument("--verify", metavar="SUB_ID", help="plan de lecturas posteriores")
    parser.add_argument("--cancel", metavar="SUB_ID", help="plan de baja de la suscripcion de prueba")
    parser.add_argument("--consumption", action="store_true", help="alta de suscripcion a un plan de CONSUMO")
    parser.add_argument("--create-plan", action="store_true", help="con --consumption: crea el plan (POST /api/suplan)")
    parser.add_argument("--plan-name", default=CONSUMPTION_PLAN_NAME, help="nombre del plan de consumo (max 20)")
    parser.add_argument("--charge", metavar="SUB_ID", help="cobro unico de consumo (POST /api/sutransaction)")
    parser.add_argument("--verify-consumption", metavar="SUB_ID", help="lecturas Q-06/Q-08/Q-33 de la prueba de consumo")
    parser.add_argument("--transaction-id", help="id devuelto por --charge (para --verify-consumption)")
    parser.add_argument("--conciliation-date", help="AAAA-MM-DD: agrega la CONSULTA POST /api/conciliation de ese dia")
    parser.add_argument("--execute-read", action="store_true",
                        help="ejecuta las LECTURAS (--find-existing/--verify/--verify-consumption)")
    parser.add_argument("--apply", action="store_true", help="ejecuta las ESCRITURAS (alta o --cancel)")
    parser.add_argument("--confirm-production", action="store_true", help="confirma que se opera en Payku productivo")
    args = parser.parse_args(argv)
    if args.amount < 1:
        parser.error("--amount debe ser >= 1")
    if len(args.plan_name) > PLAN_NAME_MAX:
        parser.error(f"--plan-name supera {PLAN_NAME_MAX} caracteres (doc 'Crear plan')")
    if args.create_plan and args.plan_id:
        parser.error("--create-plan y --plan-id son excluyentes")
    if args.create_plan and not args.consumption:
        parser.error("--create-plan solo aplica con --consumption")
    if args.apply and (args.find_existing or args.verify or args.verify_consumption):
        parser.error("--apply no aplica a los modos de lectura (usar --execute-read)")
    if args.conciliation_date:
        try:
            date.fromisoformat(args.conciliation_date)
        except ValueError:
            parser.error("--conciliation-date debe ser AAAA-MM-DD")
    return args


async def _run_live(args: argparse.Namespace, today: date) -> int:  # pragma: no cover - red real, nunca en tests
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.integrations.payku.client import PaykuClient
    from app.models.write_run import WriteRun
    from app.services.read_only_provider_sync import sanitize_record

    secrets = (settings.payku_api_key, settings.payku_secret_key)
    if args.apply:
        check_armed(args, settings, os.environ, cancel=bool(args.cancel))
        session = SessionLocal()
        try:
            recorder = WriteRecorder(session, WriteRun, sanitize_record)
            async with PaykuClient() as provider:
                if args.cancel:
                    result = await apply_cancel(args.cancel, provider, recorder, secrets)
                elif args.charge:
                    result = await apply_charge(args.charge, args, provider, recorder, secrets, today)
                elif args.consumption:
                    result = await apply_create_consumption(args, provider, recorder, secrets, today)
                else:
                    result = await apply_create(args, provider, recorder, secrets, today)
        finally:
            session.close()
        print(_masked_body(result) if isinstance(result, dict) else result)
        return 0
    check_read_allowed(args)
    async with PaykuClient() as provider:
        if args.verify_consumption:
            out = await verify_consumption(args.verify_consumption, args.transaction_id, provider, today,
                                           args.conciliation_date)
        elif args.verify:
            out = {
                "subscription": await provider.get_subscription(args.verify),
                "v3_today": await provider.list_subscriptions_v3(page=1, per_page=100, date_init=today.isoformat(),
                                                                 date_end=today.isoformat()),
                "transactions_today": await provider.list_transactions(date_init=today.isoformat(),
                                                                       date_end=today.isoformat()),
            }
        else:
            out = await find_existing(provider, args.email, args.rut)
    print(out)
    return 0


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    args = parse_args(argv)
    today = today or datetime.now(CHILE).date()
    live = args.apply or args.execute_read
    if args.cancel:
        plan = build_cancel_plan(args.cancel)
    elif args.charge:
        plan = build_charge_plan(args.charge, args, today, configured_excluded_ids())
    elif args.verify_consumption:
        plan = build_verify_consumption_plan(args.verify_consumption, args.transaction_id, today,
                                             args.conciliation_date)
    elif args.consumption:
        plan = build_consumption_plan(args, today)
    elif args.verify:
        plan = build_verify_plan(args.verify, today)
    elif args.find_existing:
        plan = Plan("Busqueda de suscripciones previas (solo GET)", find_existing_steps(args.email, args.rut))
    else:
        plan = build_create_plan(args, today)
    print(render_plan(plan, args.email))
    if not live:
        print("\nDRY-RUN: no se hizo ninguna llamada. Para ejecutar ver docs/integrations/payku/prueba-productivo.md.")
        return 0
    try:
        return asyncio.run(_run_live(args, today))
    except ArmingError as exc:
        print(f"\nBLOQUEADO: {exc}. No se hizo ninguna llamada de escritura.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
