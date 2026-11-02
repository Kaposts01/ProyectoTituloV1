"""VP-PAR-11: paridad permanente reportes PAT de VirtualPOS vs base, por mes y estado (SOLO LECTURA).

Compara los cobros de `TransaccionesPAT` ya importados (`vp_report_payments`) con `vp_charges`, dentro de la ventana que
cubren los reportes (detalle en `app/services/vp_parity.py`). No lee archivos ni llama al proveedor. La salida solo trae
mes y cantidades. Codigo de salida: 0 = paridad OK, 1 = hay diferencias en la ventana, 2 = abortado por la guarda.

GUARDA: aborta si la base no termina en `_test`, salvo que se pase explicitamente `--read-only` (solo SELECT dentro de
una transaccion READ ONLY). Ejecutarlo contra `crm` lo decide el usuario.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/vp_parity_check.py
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/vp_parity_check.py --from 2026-01 --read-only

El mismo calculo corre a diario como job (`vp_parity_check`, apagado por defecto: `VP_PARITY_CHECK_ENABLED`).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import settings
from app.services import vp_parity
from scripts.diagnostics import readonly_guard

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month_arg(value: str) -> str:
    if not _MONTH.match(value):
        raise argparse.ArgumentTypeError("use el formato AAAA-MM (p. ej. 2026-03)")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--from", dest="from_month", type=_month_arg, help="Primer mes (AAAA-MM).")
    parser.add_argument("--to", dest="to_month", type=_month_arg, help="Ultimo mes (AAAA-MM).")
    readonly_guard.add_read_only_argument(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_name = readonly_guard.enforce_database_guard(args.read_only)
    db = readonly_guard.open_readonly_session()
    try:
        print(f"Base: {db_name} | ambiente: {settings.env_mode} | solo lectura", file=sys.stderr)
        result = vp_parity.compute_vp_parity(db, from_month=args.from_month, to_month=args.to_month)
        print(vp_parity.format_result(result), end="")
    finally:
        db.rollback()
        db.close()
    return 0 if result.ok or not result.has_report else 1


if __name__ == "__main__":
    raise SystemExit(main())
