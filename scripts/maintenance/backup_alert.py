"""BCK-01a: aviso de "respaldo fallido" por el pipeline real de alertas (`app/services/alerts.py`).

Lo llama `backup_db.ps1 -AlertOnFailure` cuando el respaldo falla. Usa el mismo SMTP y destinatarios que las
alertas (`ALERT_SMTP_*`, `ALERT_EMAIL_TO`). El aviso solo lleva el nombre de la base y la etapa que fallo: nada de
datos personales, rutas con nombres de socios ni mensajes de error crudos.

Uso (PowerShell, desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\backup_alert.py --database crm --stage pg_dump
    ... --dry-run   # imprime el aviso sin enviarlo

Sale con 0 si el aviso se envio (o en dry-run) y con 1 si no se pudo enviar.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_SAFE = re.compile(r"^[A-Za-z0-9_ .:-]{1,60}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aviso de respaldo fallido (BCK-01a).")
    parser.add_argument("--database", required=True, help="Base que se intento respaldar.")
    parser.add_argument("--stage", required=True, help="Etapa que fallo (pg_dump, validacion, copia externa...).")
    parser.add_argument("--dry-run", action="store_true", help="Imprime el aviso sin enviarlo.")
    return parser


def build_condition(database: str, stage: str):
    from app.services import alerts

    database = database if _SAFE.match(database) else "(nombre no valido)"
    stage = stage if _SAFE.match(stage) else "(desconocida)"
    return alerts.Condition(
        key=f"backup_failed:{database}",
        channel="Respaldos",
        title=f"respaldo de la base {database} fallido",
        text=f"El respaldo diario de la base {database} fallo en la etapa: {stage}.",
        details=("Revisar CRM_backups\\logs\\backup_db.log en el PC del servidor.",
                 "Runbook: docs/operations/backups.md, seccion «Si el respaldo falla»."),
        link="docs/operations/backups.md",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from app.services import alerts

    cond = build_condition(args.database, args.stage)
    now = datetime.now(UTC)
    if args.dry_run:
        msg = alerts.build_message("new", cond, now, now)
        print(f"Asunto: {msg['Subject']}")
        print(msg.get_content())
        return 0
    ok = alerts.send_condition("new", cond, now, now)
    print("Aviso enviado." if ok else "Aviso NO enviado (revisar ALERT_EMAIL_TO / ALERT_SMTP_HOST).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
