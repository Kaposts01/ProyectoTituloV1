"""SYNC-O-13 / SYNC-D-11: carga historica reanudable por ventanas de fecha (VirtualPOS, Toku, Payku).

Por defecto es un DRY-RUN: muestra las ventanas que leeria y no toca la base ni el proveedor.

    # Ver el plan (no conecta a nada)
    python scripts/sync_history.py --channel payku --from 2020-01-01 --to 2020-12-31

    # Ejecutar: registra el plan en `sync_cursors` y lee ventana por ventana, con topes
    python scripts/sync_history.py --channel payku --from 2020-01-01 --to 2020-12-31 --execute \\
        --confirm-database <nombre_exacto_de_la_base> --max-requests 200 --pause-seconds 1 --allowed-hours 22-6

    # Reanudar lo pendiente (sigue en la pagina guardada de cada ventana)
    python scripts/sync_history.py --channel payku --resume --confirm-database <base>

    # Estado del plan guardado (solo lectura)
    python scripts/sync_history.py --channel payku --status

`--execute` y `--resume` llaman a la API REAL del proveedor configurado y escriben en la base: exigen
`--confirm-database` con el nombre exacto de la base destino. Contra `crm` (produccion) se aborta sin esa
confirmacion. Pruebe primero en `crm_sandbox`. Nunca imprime datos de socios: solo fechas, paginas y conteos.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PRODUCTION_DATABASE = "crm"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Carga historica reanudable por ventanas (SYNC-O-13).")
    parser.add_argument("--channel", required=True, choices=("virtualpos1", "virtualpos2", "toku", "payku"))
    parser.add_argument("--from", dest="start", type=date.fromisoformat, help="Fecha inicial YYYY-MM-DD (inclusive)")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, help="Fecha final YYYY-MM-DD (inclusive)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true", help="Registrar el plan y leer (API real; escribe en la base)")
    action.add_argument("--resume", action="store_true", help="Reanudar las ventanas pendientes del plan guardado")
    action.add_argument("--status", action="store_true", help="Mostrar el estado del plan guardado (solo lectura)")
    parser.add_argument("--confirm-database", help="Nombre exacto de la base destino; obligatorio con --execute/--resume")
    parser.add_argument("--max-requests", type=int, default=200, help="Tope de peticiones de esta ejecucion")
    parser.add_argument("--pause-seconds", type=float, default=1.0, help="Pausa entre peticiones")
    parser.add_argument("--allowed-hours", help="Franja permitida en hora de Chile, HH-HH (p. ej. 22-6)")
    parser.add_argument("--retry-failed", action="store_true", help="Reintentar tambien las ventanas fallidas")
    return parser


def _print_plan(windows: list[tuple[date, date]], channel: str) -> None:
    print(f"Plan {channel}: {len(windows)} ventanas")
    for start, end in windows:
        print(f"  {start} .. {end}")


def _print_cursors(cursors: list[Any]) -> None:
    for c in cursors:
        error = f" error={c.last_error}" if c.last_error else ""
        print(f"  {c.window_start} .. {c.window_end}  {c.status:<8} pagina={c.page} registros={c.records_seen} "
              f"peticiones={c.requests_made}{error}")


def _database_name() -> str:
    from app.db.session import engine

    return engine.url.database or ""


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
    database_name: Callable[[], str] = _database_name,
    spec_factory: Callable[[str], Any] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    from app.services import sync_history

    if args.start and args.end and args.end < args.start:
        print("La fecha final es anterior a la inicial.", file=sys.stderr)
        return 2

    if not (args.execute or args.resume or args.status):
        if not (args.start and args.end):
            print("El dry-run necesita --from y --to.", file=sys.stderr)
            return 2
        _print_plan(sync_history.plan_windows(args.channel, args.start, args.end), args.channel)
        print("DRY-RUN: no se conecto a la base ni al proveedor. Use --execute para leer.")
        return 0

    try:
        hours = sync_history.parse_hours(args.allowed_hours)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    name = database_name()
    if (args.execute or args.resume) and args.confirm_database != name:
        target = "PRODUCCION (crm)" if name == PRODUCTION_DATABASE else f"'{name}'"
        print(f"Abortado: --execute/--resume escriben en {target} y llaman a la API real; "
              f"confirme con --confirm-database {name}.", file=sys.stderr)
        return 2
    if args.execute and not (args.start and args.end):
        print("--execute necesita --from y --to.", file=sys.stderr)
        return 2

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        if args.status:
            cursors = sync_history.load_plan(db, args.channel, args.start, args.end)
            print(f"Plan {args.channel} en '{name}': {len(cursors)} ventanas")
            _print_cursors(cursors)
            return 0
        if args.execute:
            sync_history.save_plan(db, args.channel, args.start, args.end)
        spec = spec_factory(args.channel) if spec_factory else None
        summary = asyncio.run(sync_history.run_plan(
            db, args.channel, start=args.start, end=args.end, spec=spec, max_requests=args.max_requests,
            pause_seconds=args.pause_seconds, allowed_hours=hours, retry_failed=args.retry_failed,
        ))
        print(f"{args.channel} en '{name}': ventanas terminadas={summary.windows_done} fallidas={summary.windows_failed} "
              f"peticiones={summary.requests} registros={summary.records}")
        for line in summary.windows:
            print(f"  {line}")
        if summary.stopped_reason == "sin ventanas pendientes":
            print("Sin ventanas pendientes.")
        elif summary.stopped_reason:
            print(f"Detenido: {summary.stopped_reason}. Reanude con --resume.")
        return 1 if summary.windows_failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
