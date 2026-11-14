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
    if plan.total_clp:
        lines.append(f"Costo total estimado: {plan.total_clp} CLP ({VALIDATION_CHARGE_CLP} de validacion + monto)")
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
    missing = [flag for flag, value in (("--rut", args.rut), ("--email", args.email), ("--phone", args.phone),
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
    parser.add_argument("--execute-read", action="store_true", help="ejecuta las LECTURAS (--find-existing/--verify)")
    parser.add_argument("--apply", action="store_true", help="ejecuta las ESCRITURAS (alta o --cancel)")
    parser.add_argument("--confirm-production", action="store_true", help="confirma que se opera en Payku productivo")
    args = parser.parse_args(argv)
    if args.amount < 1:
        parser.error("--amount debe ser >= 1")
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
                else:
                    result = await apply_create(args, provider, recorder, secrets, today)
        finally:
            session.close()
        print(_masked_body(result) if isinstance(result, dict) else result)
        return 0
    check_read_allowed(args)
    async with PaykuClient() as provider:
        if args.verify:
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
