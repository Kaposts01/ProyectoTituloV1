"""Fechas de alta/baja de Toku desde el reporte de Productos (TK-PAR-05), sin esperar al ETL core completo.

Por defecto es un DRY-RUN: ejecuta el calculo dentro de una transaccion de SOLO LECTURA y solo imprime conteos (cuantas
suscripciones recibirian `started_at`/`ended_at` y cuantas bajas se crearian en core). Con `--apply` escribe en
`core_subscriptions`. No toca la API, no ejecuta migraciones y no imprime filas ni datos personales.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/toku_report_lifecycle.py            # dry-run
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/toku_report_lifecycle.py --apply    # escribe

Requiere haber cargado antes el reporte de Productos (`import_toku_reports.py` o la ruta `/api/v1/imports/toku-reports`).
Usa la base del ambiente activo (APP_ENV / DATABASE_URL); con APP_ENV=development eso es la base real `crm`, asi que
`--apply` lo corre siempre el usuario, tras revisar el dry-run y con respaldo.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.core_toku_etl import materialize_report_dates


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply", action="store_true", help="Escribe en core (sin esta bandera es un dry-run de solo lectura)."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, session_factory: Callable[[], Session] = SessionLocal) -> int:
    args = parse_args(argv)
    db = session_factory()
    try:
        print(f"Ambiente: {settings.env_mode} | modo: {'APPLY' if args.apply else 'DRY-RUN (solo lectura)'}")
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        stats = materialize_report_dates(db, dry_run=not args.apply)
        for key, value in stats.items():
            print(f"  {key}: {value}")
        if args.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
