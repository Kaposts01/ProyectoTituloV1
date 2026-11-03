"""d137 (L5-ALERTAS): correo de prueba por el pipeline real de alertas (`app/services/alerts.py`).

Arma un aviso con el MISMO formato y lo envia por el MISMO SMTP que las alertas (`ALERT_SMTP_*`, `ALERT_EMAIL_TO`).
Pensado para sandbox con un SMTP de depuracion local (ver docs/data/alerts.md, «Probar en sandbox»).

Por defecto es **--dry-run**: imprime asunto y cuerpo (sin destinatarios) y no abre ninguna conexion. Para enviar hay
que pasar `--send`. Se niega a correr si el ambiente no es sandbox (`APP_ENV`), salvo con `--allow-non-sandbox`.

Uso (PowerShell, desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\send_test_alert.py            # dry-run
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\send_test_alert.py --send     # envia
    ... --send --full-check   # corre el chequeo completo (run_alert_check) contra la base del ambiente

Nunca imprime destinatarios, credenciales ni valores del .env: solo el ambiente, el asunto y el cuerpo del aviso.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TEST_KEY = "test_alert:manual"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Correo de prueba de alertas (dry-run por defecto).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="send", action="store_false", help="Solo imprime el aviso (por defecto).")
    mode.add_argument("--send", dest="send", action="store_true", help="Envia el aviso por el SMTP configurado.")
    parser.set_defaults(send=False)
    parser.add_argument("--full-check", action="store_true",
                        help="Con --send: corre run_alert_check (todas las condiciones activas) en vez del aviso de prueba.")
    parser.add_argument("--allow-non-sandbox", action="store_true",
                        help="Permite correr fuera de sandbox (APP_ENV distinto de sandbox). Usar con cuidado.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from app.core.config import settings
    from app.services import alerts

    env = settings.env_mode
    print(f"Ambiente: {env}")
    if env != "sandbox" and not args.allow_non_sandbox:
        print("Rechazado: este script solo corre en sandbox (APP_ENV=sandbox). Use --allow-non-sandbox para forzarlo.")
        return 2

    now = datetime.now(UTC)
    if args.full_check:
        if not args.send:
            print("--full-check requiere --send (el chequeo completo guarda estado y envia).")
            return 2
        if not settings.alerts_enabled:
            print("ALERTS_ENABLED esta apagada: el chequeo completo no enviaria nada.")
            return 1
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            result = alerts.run_alert_check(db, now=now)
        finally:
            db.close()
        print(f"Chequeo completo: enviados={result.sent} fallidos={result.failed} activas={result.active} "
              f"omitido={result.skipped or 'no'}")
        return 0 if not result.failed and result.skipped is None else 1

    cond = alerts.Condition(
        key=TEST_KEY, channel="Prueba", title="correo de prueba de alertas",
        text="Correo de prueba enviado a mano con scripts/maintenance/send_test_alert.py.",
        details=("Si llega este mensaje, el SMTP y el destinatario de las alertas funcionan.",),
        link=alerts.SYNC_LINK)
    valid, invalid = alerts.parse_recipients(settings.alert_email_to)
    print(f"Destinatarios validos: {len(valid)} (invalidos omitidos: {invalid})")
    if not args.send:
        msg = alerts.build_message("new", cond, now, now)
        print("--- DRY-RUN: no se abre ninguna conexion ---")
        print(f"Asunto: {msg['Subject']}")
        print(msg.get_content())
        return 0
    ok = alerts.send_condition("new", cond, now, now)
    print("Enviado." if ok else "No se envio (revisar ALERT_EMAIL_TO, ALERT_SMTP_HOST y el log).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
