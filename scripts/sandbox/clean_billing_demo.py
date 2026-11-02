"""Limpieza de los datos SINTETICOS ``DEMO-`` de la opcion A en el SANDBOX (UI-40). Por defecto NO borra nada.

Uso (desde la raiz del repo, con el venv del proyecto):

    $env:APP_ENV='sandbox'
    .venv\\Scripts\\python.exe scripts\\sandbox\\clean_billing_demo.py           # informe (solo lectura)
    .venv\\Scripts\\python.exe scripts\\sandbox\\clean_billing_demo.py --apply   # borra, solo si es seguro

Por que no basta un DELETE: ``billing_change_request_events`` y ``billing_policy_audit`` son inmutables (trigger
``BEFORE UPDATE OR DELETE ... FOR EACH ROW``), asi que sus filas no se borran una por una, y los eventos referencian a las
solicitudes. Un TRUNCATE de ``billing_change_requests`` tampoco sirve: ``write_runs.request_id`` la referencia y PostgreSQL
exige truncar tambien ``write_runs`` (o usar CASCADE), lo que borraria el historial de escrituras. Desactivar los triggers
exige ser duenio de la tabla y salta un control de auditoria: este script no lo hace.

Que hace ``--apply`` (una sola transaccion; si algo falla no queda nada a medias):
1. Bloquea las tablas de billing y vuelve a contar (nadie puede escribir mientras tanto).
2. Aborta si hay eventos de solicitudes que NO son ``DEMO-`` (un TRUNCATE de eventos los borraria) o si algun
   ``write_run`` apunta a una solicitud ``DEMO-`` (no se tocan escrituras).
3. DELETE de ``vp_managed_charges``, ``billing_renewal_tasks`` y ``vp_calendar_marks`` con prefijo ``DEMO-``.
4. TRUNCATE de ``billing_change_request_events`` (todas sus filas son de solicitudes ``DEMO-``, comprobado en 2) y DELETE de
   las ``billing_change_requests`` ``DEMO-``.
5. ``billing_policy_audit``: TRUNCATE solo si TODAS sus filas tienen motivo ``DEMO-``; si hay auditoria real se deja
   intacta (las 2 filas de ejemplo no molestan) y se informa.
La fila de ``billing_policy`` no se toca (es la politica vigente del sandbox).

Seguridad (falla cerrado): las mismas guardas que ``seed_billing_demo.py`` (APP_ENV sandbox/qa, nombre de base con
``sandbox`` o ``qa``, nunca ``crm``, confirmado con ``current_database()``). No llama a proveedores ni corre Alembic.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ANTES de importar `app.*` (la configuracion lee APP_ENV al importarse).
os.environ["APP_ENV"] = "sandbox"
ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)  # el .env se resuelve relativo al directorio actual
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import Connection  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

PREFIX = "DEMO-"
LIKE = f"{PREFIX}%"
TABLES = (
    "billing_change_requests", "billing_change_request_events", "vp_managed_charges", "billing_renewal_tasks",
    "vp_calendar_marks", "billing_policy_audit", "write_runs",
)

# Conteos: (clave, descripcion, SQL). Todo con el prefijo como parametro, nada interpolado.
COUNTS: tuple[tuple[str, str, str], ...] = (
    ("requests", "solicitudes DEMO-",
     "SELECT count(*) FROM billing_change_requests WHERE subscription_external_id LIKE :p"),
    ("events_demo", "eventos de solicitudes DEMO-",
     "SELECT count(*) FROM billing_change_request_events e JOIN billing_change_requests r ON r.id = e.request_id "
     "WHERE r.subscription_external_id LIKE :p"),
    ("events_other", "eventos de solicitudes NO DEMO- (bloquean el TRUNCATE de eventos)",
     "SELECT count(*) FROM billing_change_request_events e JOIN billing_change_requests r ON r.id = e.request_id "
     "WHERE r.subscription_external_id NOT LIKE :p"),
    ("write_runs_demo", "write_runs que apuntan a solicitudes DEMO- (bloquean el borrado)",
     "SELECT count(*) FROM write_runs w JOIN billing_change_requests r ON r.id = w.request_id "
     "WHERE r.subscription_external_id LIKE :p"),
    ("managed", "cobros gestionados DEMO-",
     "SELECT count(*) FROM vp_managed_charges WHERE charge_id LIKE :p OR subscription_external_id LIKE :p"),
    ("tasks", "tareas de renovacion DEMO-",
     "SELECT count(*) FROM billing_renewal_tasks WHERE subscription_external_id LIKE :p"),
    ("marks", "marcas de calendario DEMO-",
     "SELECT count(*) FROM vp_calendar_marks WHERE subscription_external_id LIKE :p"),
    ("audit_demo", "auditoria de politica DEMO-",
     "SELECT count(*) FROM billing_policy_audit WHERE reason LIKE :p"),
    ("audit_other", "auditoria de politica real (se conserva)",
     "SELECT count(*) FROM billing_policy_audit WHERE reason IS NULL OR reason NOT LIKE :p"),
)


def fail(msg: str) -> None:
    print(f"ABORTADO: {msg}", file=sys.stderr)
    raise SystemExit(2)


def guard_sandbox() -> str:
    """Misma guarda que seed_billing_demo.py: solo una base claramente sandbox/qa."""
    if settings.env_mode not in ("sandbox", "qa"):
        fail(f"APP_ENV efectivo es {settings.env_mode!r}; se exige sandbox o qa.")
    name = (engine.url.database or "").lower()
    if name == "crm" or not ("sandbox" in name or "qa" in name):
        fail("la base configurada no contiene 'sandbox' o 'qa' en su nombre (o es 'crm'). No se borra nada.")
    with engine.connect() as conn:
        live = (conn.execute(text("SELECT current_database()")).scalar() or "").lower()
    if live != name or live == "crm" or not ("sandbox" in live or "qa" in live):
        fail("current_database() no coincide con una base sandbox/qa. No se borra nada.")
    return live


def count_all(conn: Connection) -> dict[str, int]:
    return {key: int(conn.execute(text(sql), {"p": LIKE}).scalar() or 0) for key, _desc, sql in COUNTS}


def blockers(counts: dict[str, int]) -> list[str]:
    """Motivos por los que `--apply` no puede borrar sin tocar datos que no son DEMO-."""
    out = []
    if counts["events_other"]:
        out.append(f"hay {counts['events_other']} eventos de solicitudes que no son DEMO-: el TRUNCATE de eventos los borraria.")
    if counts["write_runs_demo"]:
        out.append(f"hay {counts['write_runs_demo']} write_runs que apuntan a solicitudes DEMO-; no se tocan escrituras.")
    return out


def report(counts: dict[str, int]) -> None:
    for key, desc, _sql in COUNTS:
        print(f"  {desc:70}{counts[key]:>8}")


def apply(conn: Connection) -> dict[str, int]:
    conn.execute(text(f"LOCK TABLE {', '.join(TABLES)} IN SHARE ROW EXCLUSIVE MODE"))
    counts = count_all(conn)  # recuento con las tablas bloqueadas
    problems = blockers(counts)
    if problems:
        fail(" ".join(problems))
    done: dict[str, int] = {}
    done["vp_managed_charges"] = conn.execute(text(
        "DELETE FROM vp_managed_charges WHERE charge_id LIKE :p OR subscription_external_id LIKE :p"), {"p": LIKE}).rowcount
    done["billing_renewal_tasks"] = conn.execute(text(
        "DELETE FROM billing_renewal_tasks WHERE subscription_external_id LIKE :p"), {"p": LIKE}).rowcount
    done["vp_calendar_marks"] = conn.execute(text(
        "DELETE FROM vp_calendar_marks WHERE subscription_external_id LIKE :p"), {"p": LIKE}).rowcount
    conn.execute(text("TRUNCATE billing_change_request_events"))  # todas son DEMO- (comprobado arriba)
    done["billing_change_request_events"] = counts["events_demo"]
    done["billing_change_requests"] = conn.execute(text(
        "DELETE FROM billing_change_requests WHERE subscription_external_id LIKE :p"), {"p": LIKE}).rowcount
    if counts["audit_other"] == 0:
        conn.execute(text("TRUNCATE billing_policy_audit"))
        done["billing_policy_audit"] = counts["audit_demo"]
    else:
        done["billing_policy_audit"] = 0
        print(f"AVISO: billing_policy_audit tiene {counts['audit_other']} filas reales; se conservan tambien las "
              f"{counts['audit_demo']} de ejemplo DEMO- (la tabla es inmutable).")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpieza de datos DEMO- de billing en el sandbox (por defecto, solo informe).")
    parser.add_argument("--apply", action="store_true", help="borra de verdad (solo si es seguro; ver docstring)")
    args = parser.parse_args(argv)
    dbname = guard_sandbox()
    print(f"Base conectada: {dbname} (APP_ENV={settings.env_mode}).")
    with engine.connect() as conn:
        counts = count_all(conn)
    print("Filas encontradas:")
    report(counts)
    problems = blockers(counts)
    if not args.apply:
        print("Modo informe: no se borro nada. Use --apply para borrar." if not problems
              else "Modo informe: --apply se negaria: " + " ".join(problems))
        return 0
    with engine.begin() as conn:
        done = apply(conn)
    print("Borradas:")
    for table, n in done.items():
        print(f"  {table:36}{n:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
