"""Fechas de alta/baja (TK-PAR-05) y senales de suscripcion (TK-20) de Toku desde los reportes, sin esperar al ETL completo.

Por defecto es un DRY-RUN: ejecuta el calculo dentro de una transaccion de SOLO LECTURA y solo imprime conteos (cuantas
suscripciones recibirian `started_at`/`ended_at` y cuantas bajas se crearian en core; con `--signals`, cuantas son activas
efectivas y recuperables y por que motivo). Con `--apply` escribe en `core_subscriptions` (y en
`core_subscription_signals` si se pasa `--signals`). No toca la API, no ejecuta migraciones y no imprime filas ni datos
personales.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/toku_report_lifecycle.py --signals           # dry-run
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/toku_report_lifecycle.py --signals --apply   # escribe

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
from app.services.toku_report_signals import compute_report_signals


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply", action="store_true", help="Escribe en core (sin esta bandera es un dry-run de solo lectura)."
    )
    parser.add_argument(
        "--signals",
        action="store_true",
        help="Ademas calcula las senales de suscripcion y el estado reporte > API (TK-20), independiente de la bandera "
        "TOKU_REPORT_SIGNALS_ENABLED del ETL.",
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
        if args.signals:
            if args.apply:  # las bajas recien creadas deben existir en core antes de calcular sus senales
                db.flush()
            print("Senales (TK-20):")
            for key, value in compute_report_signals(db, dry_run=not args.apply).items():
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
