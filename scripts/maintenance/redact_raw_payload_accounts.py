"""Enmascara numeros de cuenta bancaria completos ya guardados en columnas JSON (d212). Lo ejecuta el USUARIO.

Contexto: hasta d212 el saneador de payloads (`app/services/payload_sanitization.py`) no plegaba tildes, asi que una
clave como «Número Cuenta» de los informes TCH pasaba el filtro y la cuenta completa podia quedar en `raw_payload`
(y en sus copias consolidadas). Este script corrige los datos ya guardados: toda clave de numero de cuenta (misma
normalizacion que el saneador: sin tildes, minusculas, separadores equivalentes) cuyo valor escalar tenga MAS de 4
digitos se reemplaza por `••••` + los ultimos 4 digitos (mismo formato que `account_masking`).

- Por defecto es DRY-RUN: solo cuenta (por tabla.columna, filas y valores) y hace ROLLBACK. No imprime valores.
- `--apply` exige `--confirm-database <nombre>` con el nombre EXACTO de la base actual; todo va en UNA transaccion
  (commit al final, rollback ante cualquier error) y registra cuantos valores y filas cambio.
- Recorre todas las columnas json/jsonb del esquema `public`. NO toca columnas de texto como
  `tch_suscripciones.numero_cuenta` (esa se enmascara al leer; ver d199).

Ejemplo (PowerShell, desde la raiz; hacer respaldo antes de aplicar):
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\redact_raw_payload_accounts.py
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\redact_raw_payload_accounts.py --apply --confirm-database <base>
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("redact_raw_payload_accounts")

MASK = "••••"
# Formas compactas (sin separadores) de las claves de numero de cuenta que quita el saneador.
ACCOUNT_KEYS_COMPACT = frozenset({
    "accountnumber", "bankaccountnumber", "numerocuenta", "numerodecuenta", "nrocuenta", "numcuenta", "ncuenta",
    "nocuenta", "cuentabancaria", "numerocuentabancaria",
})
# Prefiltro SQL (barato): solo filas con alguna clave que mencione cuenta/account en cualquier nivel.
_PREFILTER = """strict $.** ? (@.type() == "object").keyvalue() ? (@.key like_regex "(cuenta|account)" flag "i")"""


class NotConfirmedError(Exception):
    """`--apply` sin `--confirm-database` igual a la base actual."""


def is_account_key(key: Any) -> bool:
    folded = unicodedata.normalize("NFKD", str(key)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", folded.lower()) in ACCOUNT_KEYS_COMPACT


def redact_value(value: Any) -> Any:
    """`••••1234` si el escalar tiene mas de 4 digitos; si no, el valor tal cual."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return value
    digits = re.sub(r"\D", "", str(value))
    return MASK + digits[-4:] if len(digits) > 4 else value


def redact(value: Any, under_account_key: bool = False) -> tuple[Any, int]:
    """Copia con las cuentas enmascaradas y cuantos valores cambio (recursivo sobre dict/list)."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        changed = 0
        for key, nested in value.items():
            out[key], n = redact(nested, is_account_key(key))
            changed += n
        return out, changed
    if isinstance(value, list):
        items = [redact(item, under_account_key) for item in value]
        return [item for item, _ in items], sum(n for _, n in items)
    if under_account_key:
        new = redact_value(value)
        return new, int(new != value)
    return value, 0


def json_columns(db: Session) -> list[tuple[str, str, str]]:
    rows = db.execute(text(
        "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
        "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.data_type IN ('json', 'jsonb') "
        "ORDER BY c.table_name, c.column_name"
    ))
    return [(r[0], r[1], r[2]) for r in rows]


def _ident(name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError(f"identificador no permitido: {name!r}")
    return f'"{name}"'


def run(db: Session, apply: bool, confirm_database: str | None) -> dict[str, Any]:
    """Recorre y (con apply) reescribe en UNA transaccion. Devuelve solo conteos."""
    current = db.execute(text("SELECT current_database()")).scalar_one()
    if apply and confirm_database != current:
        raise NotConfirmedError(
            f"--apply exige --confirm-database con el nombre exacto de la base actual ('{current}')."
        )
    report: dict[str, Any] = {"database": current, "mode": "apply" if apply else "dry-run", "columns": {}}
    try:
        for table, column, data_type in json_columns(db):
            t, c = _ident(table), _ident(column)
            as_jsonb = f"{c}::jsonb" if data_type == "json" else c
            rows = db.execute(text(
                f"SELECT ctid::text, {as_jsonb} FROM {t} WHERE {c} IS NOT NULL "
                f"AND jsonb_path_exists({as_jsonb}, CAST(:path AS jsonpath)) FOR UPDATE"
            ), {"path": _PREFILTER}).all()
            rows_changed = values_changed = 0
            for ctid, payload in rows:
                new, n = redact(payload)
                if not n:
                    continue
                rows_changed += 1
                values_changed += n
                if apply:
                    db.execute(
                        text(f"UPDATE {t} SET {c} = CAST(:v AS {data_type}) WHERE ctid = CAST(:ctid AS tid)"),
                        {"v": json.dumps(new, ensure_ascii=False), "ctid": ctid},
                    )
            if rows_changed:
                report["columns"][f"{table}.{column}"] = {"filas": rows_changed, "valores": values_changed}
        report["filas_total"] = sum(v["filas"] for v in report["columns"].values())
        report["valores_total"] = sum(v["valores"] for v in report["columns"].values())
        if apply:
            db.commit()
            log.info("APPLY confirmado en '%s': %s filas, %s valores enmascarados",
                     current, report["filas_total"], report["valores_total"])
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return report


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Reescribe los valores. Sin esto es DRY-RUN (solo conteos).")
    parser.add_argument("--confirm-database", help="Nombre exacto de la base actual; obligatorio con --apply.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    owns_session = session_factory is None
    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        report = run(db, args.apply, args.confirm_database)
    except NotConfirmedError as exc:
        print(str(exc))
        return 2
    finally:
        if owns_session:
            db.close()
    print("APPLY" if args.apply else "DRY-RUN (sin cambios)", f"base={report['database']}")
    for name, counts in report["columns"].items():
        print(f"  {name}: filas={counts['filas']} valores={counts['valores']}")
    print(f"  total: filas={report['filas_total']} valores={report['valores_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
