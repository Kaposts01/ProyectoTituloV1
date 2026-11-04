"""Corrida baseline del historial de cambios (SYNC-D-03). La ejecuta el USUARIO, nunca un agente.

Consolida los canales pedidos con ``baseline=True``: los eventos de esa corrida quedan marcados
``is_baseline=true`` y NO cuentan como novedad del dia (``GET /api/v1/changes/daily`` los excluye). Sirve para
la primera consolidacion de un canal con tablas centralizadas vacias o tras una carga historica.

Importante: consolidar ESCRIBE en las tablas centralizadas (igual que la sincronizacion nocturna) y en
``status_change_events``. Por eso:
- Sin ``--apply`` es solo lectura: muestra la base, conteos de filas centralizadas y de eventos, y no escribe nada.
- Con ``--apply`` hay que confirmar la base con ``--confirm-database <nombre>``; debe coincidir con la base
  a la que apunta el entorno actual (la guarda impide aplicar a una base distinta de la esperada).
- Hacer antes un respaldo y aplicar primero la migracion 20261029_0042 (tablas de eventos).

Ejemplo (PowerShell, desde la raiz):
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\consolidate_baseline.py --source toku
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\consolidate_baseline.py --source toku --apply --confirm-database <base>

No imprime URLs, credenciales ni datos personales.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SOURCES = ("virtualpos", "toku", "payku", "tch")


class BaselineNotConfirmedError(Exception):
    """Falta la confirmacion explicita de la base destino o no coincide."""


def check_apply_allowed(current_database: str, confirm_database: str | None) -> None:
    """``--apply`` solo si ``--confirm-database`` coincide EXACTAMENTE con la base actual."""
    if not confirm_database or confirm_database != current_database:
        raise BaselineNotConfirmedError(
            f"Para aplicar hay que pasar --confirm-database con el nombre exacto de la base actual ('{current_database}')."
        )


def run(sources: list[str], apply: bool, confirm_database: str | None) -> dict:
    from app.db.session import SessionLocal
    from app.models.crm import Charge, Payment, Subscription
    from app.models.status_change import StatusChangeEvent
    from app.services.channel_consolidation import consolidate_to_centralized

    db = SessionLocal()
    try:
        current = db.execute(text("select current_database()")).scalar_one()
        report: dict = {"database": current, "sources": sources, "mode": "apply" if apply else "dry-run"}
        report["rows"] = {
            m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in (Subscription, Charge, Payment)
        }
        try:
            with db.begin_nested():
                report["events_before"] = db.scalar(select(func.count()).select_from(StatusChangeEvent))
        except ProgrammingError:
            raise SystemExit("Falta aplicar la migracion 20261029_0042 (tablas de eventos) en esta base.") from None
        if not apply:
            return report
        check_apply_allowed(current, confirm_database)
        run_id = uuid.uuid4()
        failures: list[str] = []
        total = consolidate_to_centralized(db, sources, failures=failures, run_id=run_id, baseline=True)
        db.commit()
        report["records_processed"] = total
        report["failures"] = failures
        report["run_id"] = str(run_id)
        report["baseline_events_created"] = db.scalar(
            select(func.count()).select_from(StatusChangeEvent).where(
                StatusChangeEvent.run_id == run_id, StatusChangeEvent.is_baseline.is_(True)
            )
        )
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", action="append", choices=SOURCES, help="Canal a consolidar (repetible). Por defecto todos.")
    parser.add_argument("--apply", action="store_true", help="Escribe (consolida con baseline=True). Sin esto es solo lectura.")
    parser.add_argument("--confirm-database", help="Nombre exacto de la base destino; obligatorio con --apply.")
    args = parser.parse_args()
    try:
        report = run(args.source or list(SOURCES), args.apply, args.confirm_database)
    except BaselineNotConfirmedError as exc:
        print(str(exc))
        raise SystemExit(2) from None
    for key, value in report.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
