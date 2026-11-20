"""Siembra SINTETICA para el presupuesto de rendimiento en CI (PERF-03g): ~2.000 socios VirtualPOS con sus suscripciones,
cobros y pagos, mas un usuario FICTICIO de solo lectura.

Uso (en el job `perf-budget` de `.github/workflows/ci.yml`, con la base de servicio ya migrada):

    APP_ENV=sandbox PERF_CI_PASSWORD=<generada en el job> python scripts/sandbox/seed_perf_ci.py [--clients 2000]

Que siembra (solo en la base; nada va a ningun proveedor; no usa datos reales):
- ``--clients`` socios ``PERF-CL-00001``... (cuenta ``virtualpos1``), nombre ``PERF-Socio N``, correo ``@example.test`` y
  RUT sintetico del rango ``44.xxx.xxx`` con digito verificador valido. Todo determinista (semilla fija): dos corridas
  producen lo mismo.
- 1 suscripcion por socio (80 % ACTIVA, 20 % CANCELADA), 3 cobros por suscripcion repartidos en los ultimos 12 meses
  (pagado, pendiente o rechazado) y 1 pago por cada cobro pagado. Tablas ``clients``, ``subscriptions``, ``charges`` y
  ``payments``.
- Un usuario de solo lectura (rol ``perf-ci-solo-lectura``: unicamente los permisos que terminan en ``.view``). El nombre
  sale de ``PERF_CI_USER`` (por defecto ``perf-ci``) y la contrasena de ``PERF_CI_PASSWORD``: la genera el job, nunca esta
  en el repositorio y este script no la imprime.

Seguridad (falla cerrado): se niega a correr si ``APP_ENV`` no es un ambiente no productivo (``sandbox``/``qa``), si la
base no contiene ``sandbox`` o ``qa`` en su nombre, si es ``crm`` o ``*_test``, o si ``current_database()`` no lo confirma.
Idempotente: si ya hay socios ``PERF-CL-`` no vuelve a sembrarlos; el usuario se crea una sola vez.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "virtualpos1"
PREFIX = "PERF-"
RUT_BASE = 44_000_000  # rango sintetico propio de esta semilla (TCH 40, Toku 41, Payku 42, VirtualPOS demo 43)
ROLE_NAME = "perf-ci-solo-lectura"
SEED = 20261120
CHUNK = 1000
MIN_PASSWORD_LENGTH = 16
CHARGES_PER_SUB = 3


def fail(message: str) -> None:
    print(f"ABORTADO: {message}", file=sys.stderr)
    raise SystemExit(2)


def guard_database(name: str | None) -> str:
    """Falla cerrado salvo que la base sea claramente de sandbox o QA. Nunca `crm` ni `*_test`."""
    value = (name or "").strip().lower()
    if not value or value == "crm" or value.endswith("_test") or ("sandbox" not in value and "qa" not in value):
        fail("la base resuelta no es un sandbox/qa (se exige un nombre que contenga 'sandbox' o 'qa'). No se escribe nada.")
    return value


def rut_dv(number: int) -> str:
    total, factor = 0, 2
    for digit in reversed(str(number)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - total % 11
    return "0" if rest == 11 else "K" if rest == 10 else str(rest)


def synthetic_rut(n: int) -> str:
    number = RUT_BASE + n
    return f"{number}-{rut_dv(number)}"


def _month_back(today: date, months: int) -> date:
    index = today.year * 12 + (today.month - 1) - months
    return date(index // 12, index % 12 + 1, 5)


def build_rows(clients: int, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """Filas a sembrar por tabla. Determinista y 100 % sintetico (prefijo ``PERF-``)."""
    rng = random.Random(SEED)
    today = today or datetime.now(UTC).date()
    out: dict[str, list[dict[str, Any]]] = {"clients": [], "subscriptions": [], "charges": [], "payments": []}
    for n in range(1, clients + 1):
        client_id, sub_id, rut = f"{PREFIX}CL-{n:05d}", f"{PREFIX}SUB-{n:05d}", synthetic_rut(n)
        amount = rng.choice((5000, 8000, 10000, 15000, 20000))
        active = rng.random() < 0.8
        start = _month_back(today, rng.randint(6, 36))
        out["clients"].append({
            "source": SOURCE, "external_id": client_id, "first_name": f"PERF-Socio {n}", "last_name": f"Sintetico {n % 97}",
            "email": f"perf{n}@example.test", "phone_number": None, "status": "ACTIVO", "social_id": rut,
            "raw_payload": {"id": client_id, "origin": "PERF-CI"},
        })
        out["subscriptions"].append({
            "source": SOURCE, "external_id": sub_id, "client_external_id": client_id, "client_social_id": rut,
            "status": "ACTIVA" if active else "CANCELADA", "suscription_date": start.isoformat(),
            "canceled_at": None if active else _month_back(today, rng.randint(0, 5)).isoformat(),
            "amount": str(amount), "currency": "CLP", "raw_payload": {"id": sub_id, "origin": "PERF-CI"},
        })
        for k in range(1, CHARGES_PER_SUB + 1):
            charge_id = f"{PREFIX}CH-{n:05d}-{k}"
            roll = rng.random()
            status = "pagado" if roll < 0.75 else "rechazado" if roll < 0.9 else "pendiente"
            when = _month_back(today, rng.randint(0, 11)).isoformat()
            out["charges"].append({
                "source": SOURCE, "external_id": charge_id, "subscription_external_id": sub_id, "client_external_id": client_id,
                "status": status, "charge_date": when, "amount": str(amount), "currency": "CLP",
                "raw_payload": {"id": charge_id, "origin": "PERF-CI"},
            })
            if status == "pagado":
                out["payments"].append({
                    "source": SOURCE, "external_id": f"{PREFIX}PAY-{n:05d}-{k}", "charge_external_id": charge_id,
                    "client_external_id": client_id, "status": "pagado", "payment_date": when, "amount": str(amount),
                    "currency": "CLP", "raw_payload": {"origin": "PERF-CI"},
                })
    return out


def _models() -> dict[str, Any]:
    import app.models.core  # registra las tablas destino de las FK
    import app.models.source_record  # noqa: F401
    from app.models.crm import Charge, Client, Payment, Subscription

    return {"clients": Client, "subscriptions": Subscription, "charges": Charge, "payments": Payment}


def seed_data(db: Any, clients: int) -> dict[str, int]:
    """Inserta los datos si aun no estan (idempotente). Devuelve {tabla: filas}. No hace commit."""
    from sqlalchemy import func, insert, select

    models = _models()
    present = db.scalar(select(func.count()).select_from(models["clients"]).where(
        models["clients"].source == SOURCE, models["clients"].external_id.like(f"{PREFIX}CL-%")))
    if present:
        print(f"Ya hay {present} socios {PREFIX}CL- sembrados: no se vuelve a sembrar.")
        return {}
    counts: dict[str, int] = {}
    for table, rows in build_rows(clients).items():
        for start in range(0, len(rows), CHUNK):
            db.execute(insert(models[table]), rows[start:start + CHUNK])
        counts[table] = len(rows)
    db.flush()
    return counts


def ensure_readonly_user(db: Any, username: str, password: str) -> bool:
    """Crea el rol de solo lectura (solo permisos ``.view``) y el usuario ficticio. Devuelve True si lo creo."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models.auth import Role, User
    from app.services.rbac import PERMISSIONS, _ensure_role, seed_permissions

    seed_permissions(db)
    _ensure_role(db, ROLE_NAME, "Solo lectura para el presupuesto de rendimiento en CI (PERF-03g)",
                 {code for code in PERMISSIONS if code.endswith(".view")})
    db.flush()
    role = db.scalar(select(Role).where(Role.name == ROLE_NAME))
    if db.scalar(select(User).where(User.username == username)):
        return False
    db.add(User(username=username, password_hash=hash_password(password), is_active=True, roles=[role]))
    db.flush()
    return True


def _bootstrap() -> Any:
    """Verifica el ambiente y la base ANTES de escribir. Solo se llama desde main()."""
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import text

    from app.core.config import settings
    from app.db.session import SessionLocal, engine

    if settings.env_mode == "production":
        fail(f"APP_ENV efectivo es {settings.env_mode!r}; se exige sandbox o qa (APP_ENV=sandbox).")
    name = guard_database(engine.url.database)
    with engine.connect() as conn:
        live = conn.execute(text("SELECT current_database()")).scalar()
    if guard_database(live) != name:
        fail("current_database() no coincide con la base configurada.")
    print(f"Base: {name} ({settings.env_mode}).")
    return SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--clients", type=int, default=2000, help="socios sinteticos a sembrar (por defecto 2000)")
    args = parser.parse_args(argv)
    if not 1 <= args.clients <= 20000:
        fail("--clients debe estar entre 1 y 20000.")
    username = os.environ.get("PERF_CI_USER", "perf-ci").strip()
    password = os.environ.get("PERF_CI_PASSWORD", "")
    if not username or len(password) < MIN_PASSWORD_LENGTH:
        fail(f"PERF_CI_USER y PERF_CI_PASSWORD (al menos {MIN_PASSWORD_LENGTH} caracteres) deben venir del entorno del job.")
    session_factory = _bootstrap()
    db = session_factory()
    try:
        counts = seed_data(db, args.clients)
        created = ensure_readonly_user(db, username, password)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    for table, value in counts.items():
        print(f"{table}: {value} filas")
    print(f"Usuario de solo lectura {username!r}: {'creado' if created else 'ya existia'} (rol {ROLE_NAME}). La contrasena no se muestra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
