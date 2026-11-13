"""Siembra SINTETICA, idempotente y reversible de 3 suscripciones VirtualPOS ``DEMO-`` en el SANDBOX (d205 b).

Uso (desde la raiz del repo, con el venv del proyecto; el script fija APP_ENV=sandbox):

    .venv\\Scripts\\python.exe scripts\\sandbox\\seed_vp_demo.py            # siembra (omite lo que ya existe)
    .venv\\Scripts\\python.exe scripts\\sandbox\\seed_vp_demo.py --remove   # borra SOLO lo sembrado (prefijo DEMO-VP-)

Que siembra (cuenta ``virtualpos1``, solo en la base; NADA en el proveedor):
- 3 suscripciones ``DEMO-VP-SUB-00n`` ACTIVAS, sin ID de cliente (como las reales de VirtualPOS) y con el cliente embebido
  en ``raw_payload.client``: nombre que empieza con ``DEMO-``, correo ``@example.test`` y RUT sintetico del rango
  ``43.xxx.xxx`` (TCH 40, Toku 41, Payku 42; 43 = VirtualPOS), con digito verificador valido.
- 2 cobros por suscripcion (``DEMO-VP-CH-00n-01`` pagado, ``-02`` pendiente) y 1 pago ``DEMO-VP-PAY-00n`` pagado, con el
  cliente embebido en el pago y el vinculo cobro->pago (``raw_payload.payment.order.uuid``) que usa la ficha por canal.

Seguridad (falla cerrado): fija ``APP_ENV=sandbox`` antes de importar ``app.*`` (solo en ``main()``; importar el modulo
no toca el entorno) y aborta si la base no contiene ``sandbox``, si es ``crm`` o ``*_test`` o si ``current_database()`` no
lo confirma. No llama a proveedores ni ejecuta Alembic. ``--remove`` borra solo filas con ``external_id`` ``DEMO-VP-%``
(tablas ``crm`` y, si el ETL las proyecto, ``core_*``) en una transaccion.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "DEMO-VP-"
SOURCE = "virtualpos1"
RUT_BASE = 43_000_000  # rango sintetico de VirtualPOS en el sandbox

PEOPLE = (
    ("DEMO-Valentina", "Prueba", 5000),
    ("DEMO-Matias", "Ejemplo", 10000),
    ("DEMO-Javiera", "Ficticia", 15000),
)


def fail(message: str) -> None:
    print(f"ABORTADO: {message}", file=sys.stderr)
    raise SystemExit(2)


def guard_database(name: str | None) -> str:
    """Falla cerrado salvo que la base sea claramente un sandbox. Nunca `crm`, `*_test` ni otra."""
    value = (name or "").strip().lower()
    if not value or value == "crm" or value.endswith("_test") or "sandbox" not in value:
        fail("la base resuelta no es el sandbox (se exige un nombre que contenga 'sandbox'). No se escribe nada.")
    return value


def rut_dv(number: int) -> str:
    total, factor = 0, 2
    for digit in reversed(str(number)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - total % 11
    return "0" if rest == 11 else "K" if rest == 10 else str(rest)


def demo_rut(n: int) -> str:
    number = RUT_BASE + n
    return f"{number}-{rut_dv(number)}"


def build_rows() -> dict[str, list[dict[str, Any]]]:
    """Filas a sembrar por tabla (`subscriptions`, `charges`, `payments`). Todo sintetico y con prefijo DEMO-VP-."""
    subs, charges, payments = [], [], []
    for n, (first, last, amount) in enumerate(PEOPLE, start=1):
        sub_id, pay_id = f"{PREFIX}SUB-{n:03d}", f"{PREFIX}PAY-{n:03d}"
        rut = demo_rut(n)
        client = {
            "first_name": first, "last_name": last, "email": f"{first.lower()}.{last.lower()}@example.test",
            "social_id": rut, "phone": None,
        }
        subs.append({
            "external_id": sub_id, "status": "ACTIVA", "suscription_date": f"2026-0{n}-05 10:00:00", "amount": str(amount),
            "currency": "CLP", "client_social_id": rut,
            "raw_payload": {"id": sub_id, "status": "ACTIVA", "amount": str(amount), "currency": "CLP",
                            "suscription_date": f"2026-0{n}-05 10:00:00", "client": client, "origin": "DEMO"},
        })
        for k, (status, date) in enumerate((("pagado", f"2026-0{n + 1}-05"), ("pendiente", "2026-12-05")), start=1):
            ch_id = f"{PREFIX}CH-{n:03d}-{k:02d}"
            payload: dict[str, Any] = {"id": ch_id, "status": status, "amount": str(amount), "currency": "CLP",
                                       "charge_date": date, "description": "DEMO cobro sintetico"}
            if status == "pagado":
                payload["payment"] = {"order": {"uuid": pay_id}}
            charges.append({"external_id": ch_id, "subscription_external_id": sub_id, "status": status,
                            "charge_date": date, "amount": str(amount), "currency": "CLP", "raw_payload": payload})
        payments.append({
            "external_id": pay_id, "charge_external_id": f"{PREFIX}CH-{n:03d}-01", "status": "pagado",
            "payment_date": f"2026-0{n + 1}-05 10:05:00", "amount": str(amount), "currency": "CLP",
            "raw_payload": {"client": client, "order": {"uuid": pay_id, "status": "pagado", "amount": str(amount),
                                                        "created_at": f"2026-0{n + 1}-05 10:05:00"}},
        })
    return {"subscriptions": subs, "charges": charges, "payments": payments}


def _models() -> dict[str, Any]:
    from app.models.crm import Charge, Payment, Subscription

    return {"subscriptions": Subscription, "charges": Charge, "payments": Payment}


def seed(db: Any) -> dict[str, tuple[int, int]]:
    """Inserta lo que falta (por `source` + `external_id`). Devuelve {tabla: (creadas, omitidas)}. No hace commit."""
    from sqlalchemy import select

    out: dict[str, tuple[int, int]] = {}
    models = _models()
    for table, rows in build_rows().items():
        model = models[table]
        existing = set(db.scalars(select(model.external_id).where(
            model.source == SOURCE, model.external_id.in_([r["external_id"] for r in rows]))))
        new = [model(source=SOURCE, **r) for r in rows if r["external_id"] not in existing]
        db.add_all(new)
        out[table] = (len(new), len(existing))
    db.flush()
    return out


def remove(db: Any) -> dict[str, int]:
    """Borra SOLO filas `DEMO-VP-%` (crm y, si existen, sus proyecciones core). Devuelve {tabla: borradas}. No hace commit."""
    from sqlalchemy import text

    like = {"like": f"{PREFIX}%"}
    out: dict[str, int] = {}
    db.execute(text("UPDATE core_charges SET latest_rejection_payment_id = NULL WHERE external_id LIKE :like"), like)
    for table in ("core_payments", "core_charges", "core_subscriptions", "payments", "charges", "subscriptions"):
        out[table] = db.execute(text(f"DELETE FROM {table} WHERE external_id LIKE :like"), like).rowcount
    # Atributos que el ETL pudo observar de estos clientes sinteticos: solo los valores exactos sembrados.
    values = sorted({str(v) for sub in build_rows()["subscriptions"] for v in (
        sub["client_social_id"], sub["raw_payload"]["client"]["email"],
        f"{sub['raw_payload']['client']['first_name']} {sub['raw_payload']['client']['last_name']}")})
    out["core_client_attributes"] = db.execute(
        text("DELETE FROM core_client_attributes WHERE source = :source AND attribute_value = ANY(:values)"),
        {"source": SOURCE, "values": values},
    ).rowcount
    db.flush()
    return out


def _bootstrap_sandbox() -> Callable[[], Any]:
    """Fija APP_ENV=sandbox ANTES de importar settings y valida la base. Solo se llama desde main()."""
    os.environ["APP_ENV"] = "sandbox"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import text

    from app.core.config import settings
    from app.db.session import SessionLocal, engine

    if settings.env_mode != "sandbox":
        fail(f"APP_ENV efectivo es {settings.env_mode!r}; se exige sandbox.")
    name = guard_database(engine.url.database)
    with engine.connect() as conn:
        live = conn.execute(text("SELECT current_database()")).scalar()
    if guard_database(live) != name:
        fail("current_database() no coincide con la base configurada.")
    print(f"Base: {name} (sandbox).")
    return SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--remove", action="store_true", help="borra solo las filas DEMO-VP- sembradas")
    args = parser.parse_args(argv)
    db = _bootstrap_sandbox()()
    try:
        result = remove(db) if args.remove else seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    for table, value in result.items():
        print(f"{table}: {'borradas ' + str(value) if args.remove else f'creadas {value[0]}, omitidas {value[1]}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
