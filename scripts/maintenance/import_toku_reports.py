"""Carga manual de los reportes .xlsx del Backoffice de Toku (TK-19), por lote desde una carpeta o archivos sueltos.

Por defecto es un DRY-RUN: lee y valida cada archivo (tipo, filas validas, filas omitidas, ventana de fechas) y consulta
en una transaccion de SOLO LECTURA si ya fue cargado (sha256); no escribe nada. Para cargar hay que pasar `--apply`.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/import_toku_reports.py --dir "C:\\ruta\\Toku"           # dry-run
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/import_toku_reports.py --dir "C:\\ruta\\Toku" --apply   # carga

Acepta `--dir` (todos los `*.xlsx` de la carpeta; los de tipo no soportado se informan y se omiten) y/o archivos sueltos.
Orden de carga: Productos primero (resuelve el `sub_` de Intentos y Deudas), luego Medios de pago, Inscripciones, Deudas e
Intentos. Cada archivo es una transaccion; un archivo repetido (mismo sha256) se omite; un reporte mas viejo nunca pisa a uno
mas nuevo (guarda de frescura de TK-18).

Requiere `TOKU_REPORT_HASH_PEPPER` en el entorno (`ID Producto` contiene el RUT del socio y solo se guarda como HMAC). Sin el, el
script se niega a leer ningun archivo. Usa la base del ambiente activo (APP_ENV / DATABASE_URL); con APP_ENV=development eso
es la base real `crm`, asi que `--apply` lo corre siempre el usuario, con las migraciones 0039 a 0041 ya aplicadas y un respaldo.
No llama a ninguna API, no ejecuta migraciones y SOLO imprime conteos y nombres de archivo (nunca filas ni datos personales).
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
from app.models import load_all_models
from app.services import toku_report_import
from app.services.toku_report_import import ReportImportError, _sha256_file
from app.services.toku_report_parser import (
    MissingPepperError,
    ReportFormatError,
    open_report,
)

LOAD_ORDER = ("productos", "clientes", "medios_pago", "inscripciones", "deudas", "intentos", "pagos", "liquidaciones")


load_all_models()  # las FK de *_report_files apuntan a users y etl_runs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help="Archivos .xlsx sueltos.")
    parser.add_argument("--dir", dest="directory", type=Path, help="Carpeta con los reportes de Toku (*.xlsx).")
    parser.add_argument(
        "--apply", action="store_true", help="Carga los archivos (sin esta bandera es un dry-run de solo lectura)."
    )
    return parser.parse_args(argv)


def collect_files(args: argparse.Namespace) -> list[Path]:
    found: dict[str, Path] = {}
    if args.directory is not None:
        if not args.directory.is_dir():
            raise SystemExit(f"La carpeta no existe: {args.directory.name}")
        for path in sorted(args.directory.glob("*.xlsx")):
            if not path.name.startswith("~$"):  # temporales de Excel
                found[str(path.resolve()).lower()] = path
    for path in args.files:
        if not path.is_file():
            raise SystemExit(f"El archivo no existe: {path.name}")
        found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=lambda p: p.name)


def _already_loaded(db: Session, report_type: str, sha: str) -> str:
    try:
        row = db.execute(
            text("SELECT status FROM tk_report_files WHERE report_type = :t AND file_sha256 = :s"),
            {"t": report_type, "s": sha},
        ).first()
    except Exception:  # noqa: BLE001 - tabla ausente (migraciones sin aplicar) u otro error de lectura
        db.rollback()
        db.execute(text("SET TRANSACTION READ ONLY"))
        return "no verificado (migraciones 0039-0041 pendientes?)"
    return f"si ({row[0]})" if row else "no"


def detect(path: Path) -> str:
    """Tipo del reporte por firma de columnas; levanta ReportFormatError si no es soportado."""
    with open_report(path, pepper=settings.toku_report_hash_pepper) as parsed:
        return parsed.meta.report_type


def dry_run_one(db: Session, path: Path) -> dict:
    sha = _sha256_file(path)
    with open_report(path, pepper=settings.toku_report_hash_pepper) as parsed:
        records = sum(1 for _ in parsed.records())
        stats = parsed.stats
        meta = parsed.meta
        return {
            "tipo": meta.report_type,
            "filas": stats.rows_total,
            "validas": records,
            "omitidas": dict(stats.skip_reasons),
            "ventana": f"{meta.window_start} .. {meta.window_end}",
            "generado": meta.generated_at.isoformat(timespec="seconds"),
            "avisos": list(meta.warnings),
            "ya_cargado": _already_loaded(db, meta.report_type, sha),
        }


def main(argv: Sequence[str] | None = None, session_factory: Callable[[], Session] = SessionLocal) -> int:
    args = parse_args(argv)
    files = collect_files(args)
    if not files:
        print("No hay archivos que procesar (use --dir o indique archivos).")
        return 2
    if not settings.toku_report_hash_pepper:
        print("ERROR: falta TOKU_REPORT_HASH_PEPPER. Defínalo en el entorno antes de leer reportes de Toku.")
        return 3
    failures = 0
    typed: list[tuple[int, str, Path]] = []
    for path in files:
        try:
            kind = detect(path)
            typed.append((LOAD_ORDER.index(kind), path.name, path))
        except (ReportFormatError, MissingPepperError) as exc:
            failures += 1
            print(f"  {path.name}: ERROR {type(exc).__name__}: {exc}")
    typed.sort()
    db = session_factory()
    try:
        print(f"Ambiente: {settings.env_mode} | modo: {'APPLY' if args.apply else 'DRY-RUN (solo lectura)'} | archivos: {len(files)}")
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        for _order, _name, path in typed:
            try:
                if args.apply:
                    summary = toku_report_import.import_report(db, path, filename=path.name, uploaded_by_user_id=None)
                    state = "YA CARGADO" if summary.already_loaded else "ok"
                    print(
                        f"  {path.name}: {state} | {summary.report_type} | filas={summary.rows_total} nuevas={summary.rows_new} "
                        f"actualizadas={summary.rows_updated} omitidas={summary.rows_skipped} obsoletas={summary.rows_stale} "
                        f"sin_producto={summary.unresolved_product}"
                    )
                else:
                    info = dry_run_one(db, path)
                    print(f"  {path.name}: " + " | ".join(f"{k}={v}" for k, v in info.items()))
            except (ReportFormatError, ReportImportError) as exc:
                failures += 1
                print(f"  {path.name}: ERROR {type(exc).__name__}: {exc}")
        if not args.apply:
            db.rollback()
    finally:
        db.close()
    print("Fallas:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
