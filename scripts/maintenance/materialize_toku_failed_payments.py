"""Materializa los intentos FAILED de Toku como core_payments (RJ-15, decision D4).

Por defecto es un DRY-RUN: corre dentro de una transaccion de solo lectura (PostgreSQL rechaza cualquier
escritura) e imprime solo conteos. Para escribir hay que pasar `--apply` de forma explicita.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/materialize_toku_failed_payments.py            # dry-run
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/materialize_toku_failed_payments.py --apply    # escribe

Usa la base del ambiente activo (APP_ENV / DATABASE_URL); con APP_ENV=development eso es la base real
`crm`, asi que `--apply` lo corre siempre el usuario (idealmente con respaldo previo). No llama a ninguna API,
no ejecuta migraciones, no toca core_charges ni las tablas tk_* y no imprime datos personales. Las filas creadas
llevan `source_status = 'FAILED'` y se pueden deshacer con
`DELETE FROM core_payments WHERE source = 'toku' AND source_status = 'FAILED'`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.toku_failed_payments import materialize_failed_toku_payments


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply", action="store_true", help="Escribe los cambios (sin esta bandera es un dry-run de solo lectura)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        stats = materialize_failed_toku_payments(db, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    print(f"Ambiente: {settings.env_mode} | modo: {'APPLY' if args.apply else 'DRY-RUN (solo lectura)'}")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
