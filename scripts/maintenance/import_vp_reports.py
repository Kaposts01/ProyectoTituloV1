"""Carga manual de los reportes PAT de VirtualPOS (VP-PAR-02 / RJ-04), por lote desde una carpeta o archivos.

Por defecto es un DRY-RUN: lee y valida cada archivo (tipo, filas, filas omitidas, ventana de fechas) y consulta en una
transaccion de SOLO LECTURA si ya fue cargado (sha256); no escribe nada. Para cargar hay que pasar `--apply`.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/import_vp_reports.py --dir "C:\\ruta\\VirtualPOS"           # dry-run
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/maintenance/import_vp_reports.py --dir "C:\\ruta\\VirtualPOS" --apply   # carga

Acepta `--dir` (todos los `TransaccionesPAT-*.csv` y `SuscriptoresPAT-*.csv`) y/o archivos sueltos. Cada archivo es una
transaccion; un archivo repetido (mismo sha256) se omite; un reporte mas viejo nunca pisa a uno mas nuevo. Al final,
`--apply` corre `reconcile` una vez (plataforma, glosas `report_pat` y vinculo pago->cobro de lo pendiente).

Usa la base del ambiente activo (APP_ENV / DATABASE_URL); con APP_ENV=development eso es la base real `crm`, asi que
`--apply` lo corre siempre el usuario, despues de aplicar las migraciones 0045 y 0046 y de un respaldo. No llama a
ninguna API, no ejecuta migraciones y SOLO imprime conteos y nombres de archivo (nunca filas ni datos personales).
`VP_REPORT_HASH_PEPPER` (opcional) habilita el hash del codigo de vendedor.
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
from app.services import vp_report_import
from app.services.vp_report_import import ReportImportError, _sha256_file
from app.services.vp_report_parser import ReportFormatError, open_report

PATTERNS = ("TransaccionesPAT-*.csv", "SuscriptoresPAT-*.csv")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help="Archivos CSV sueltos.")
    parser.add_argument("--dir", dest="directory", type=Path, help="Carpeta con los reportes PAT.")
    parser.add_argument(
        "--apply", action="store_true", help="Carga los archivos (sin esta bandera es un dry-run de solo lectura)."
    )
    return parser.parse_args(argv)


def collect_files(args: argparse.Namespace) -> list[Path]:
    found: dict[str, Path] = {}
    if args.directory is not None:
        if not args.directory.is_dir():
            raise SystemExit(f"La carpeta no existe: {args.directory.name}")
        for pattern in PATTERNS:
            for path in sorted(args.directory.glob(pattern)):
                found[str(path.resolve()).lower()] = path
    for path in args.files:
        if not path.is_file():
            raise SystemExit(f"El archivo no existe: {path.name}")
        found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=lambda p: p.name)


def _already_loaded(db: Session, sha: str) -> str:
    try:
        row = db.execute(text("SELECT status FROM vp_report_files WHERE file_sha256 = :s"), {"s": sha}).first()
    except Exception:  # noqa: BLE001 - tabla ausente (migracion 0045 sin aplicar) u otro error de lectura
        db.rollback()
        db.execute(text("SET TRANSACTION READ ONLY"))
        return "no verificado (migracion 0045 pendiente?)"
    return f"si ({row[0]})" if row else "no"


def dry_run_one(db: Session, path: Path) -> dict:
    sha = _sha256_file(path)
    with open_report(path, pepper=settings.vp_report_hash_pepper, filename=path.name) as parsed:
        records = sum(1 for _ in parsed.records())
        stats = parsed.stats
        return {
            "tipo": parsed.meta.report_type,
            "filas": stats.rows_total,
            "validas": records,
            "omitidas": dict(stats.skip_reasons),
            "ventana": f"{stats.window_start} .. {stats.window_end}",
            "generado": parsed.meta.generated_at.isoformat(timespec="seconds"),
            "avisos": list(parsed.meta.warnings),
            "ya_cargado": _already_loaded(db, sha),
        }


def main(argv: Sequence[str] | None = None, session_factory: Callable[[], Session] = SessionLocal) -> int:
    args = parse_args(argv)
    files = collect_files(args)
    if not files:
        print("No hay archivos que procesar (use --dir o indique archivos).")
        return 2
    db = session_factory()
    failures = 0
    try:
        print(f"Ambiente: {settings.env_mode} | modo: {'APPLY' if args.apply else 'DRY-RUN (solo lectura)'} | archivos: {len(files)}")
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        for path in files:
            try:
                if args.apply:
                    summary = vp_report_import.import_report(db, path, filename=path.name, uploaded_by_user_id=None)
                    state = "YA CARGADO" if summary.already_loaded else "ok"
                    print(
                        f"  {path.name}: {state} | {summary.report_type} | filas={summary.rows_total} nuevas={summary.rows_new} "
                        f"actualizadas={summary.rows_updated} omitidas={summary.rows_skipped} obsoletas={summary.rows_stale} "
                        f"glosas={summary.rejections.get('inserted', 0)} vinculos={summary.links.get('vp_payments', 0)}"
                    )
                else:
                    info = dry_run_one(db, path)
                    print(f"  {path.name}: " + " | ".join(f"{k}={v}" for k, v in info.items()))
            except (ReportFormatError, ReportImportError) as exc:
                failures += 1
                print(f"  {path.name}: ERROR {type(exc).__name__}: {exc}")
        if args.apply:
            out = vp_report_import.reconcile(db)
            print(f"Reconciliacion final: {out}")
        else:
            db.rollback()
    finally:
        db.close()
    print("Fallas:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
