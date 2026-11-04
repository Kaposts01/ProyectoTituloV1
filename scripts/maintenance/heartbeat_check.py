"""d139c (L5-ALERTAS): chequeo externo del latido del backend, para el Programador de tareas de Windows.

Consulta `GET /api/v1/health/heartbeat` (sin sesion). Si el backend NO responde (conexion rechazada, timeout, HTTP
5xx o respuesta ilegible) envia un correo por el mismo SMTP de las alertas (`ALERT_SMTP_*`, `ALERT_EMAIL_TO`). Con
`--alert-on-degraded` tambien avisa cuando responde `degraded` (sync vieja o scheduler detenido).

Misma deduplicacion que las alertas: un aviso al caer, un recordatorio como maximo cada 6 h y un «Recuperado» al
volver. El estado va en un archivo JSON local (`--state-file`; por defecto en la carpeta temporal del usuario), porque
si el backend esta caido no se puede guardar en la base.

Respeta `ALERTS_ENABLED`: apagada, no envia nada (solo imprime). `--dry-run` imprime el aviso sin enviarlo ni
guardar estado. Nunca imprime destinatarios ni credenciales.

Uso (PowerShell, desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv\\Scripts\\python.exe scripts\\maintenance\\heartbeat_check.py --url http://localhost:8000
Codigo de salida: 0 = sano, 1 = degradado, 2 = caido (util para el historial del Programador de tareas).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HEARTBEAT_PATH = "/api/v1/health/heartbeat"
DEFAULT_URL = "http://localhost:8000"
DEFAULT_STATE = Path(tempfile.gettempdir()) / "synkmetrix_heartbeat_state.json"
KEY = "heartbeat:backend"

EXIT_OK, EXIT_DEGRADED, EXIT_DOWN = 0, 1, 2


def probe(base_url: str, timeout: float) -> tuple[str, dict[str, Any] | None, str]:
    """('ok' | 'degraded' | 'down', cuerpo, motivo corto sin datos sensibles)."""
    url = base_url.rstrip("/") + HEARTBEAT_PATH
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return "down", None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "down", None, type(getattr(exc, "reason", exc)).__name__
    except ValueError:
        return "down", None, "respuesta ilegible"
    status = str(body.get("status") or "")
    if status == "ok":
        return "ok", body, "ok"
    if status == "degraded":
        return "degraded", body, ", ".join(body.get("problems") or []) or "degraded"
    return "down", body, status or "estado desconocido"


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def decide(state: dict[str, Any], problem: bool, now: datetime, repeat_hours: float = 6.0) -> str | None:
    """'new' | 'reminder' | 'recovered' | None, con la misma regla de las alertas."""
    active = bool(state.get("active"))
    last_sent = _parse(state.get("last_sent_at"))
    if problem:
        if not active or last_sent is None:
            return "new"
        if (now - last_sent).total_seconds() >= repeat_hours * 3600:
            return "reminder"
        return None
    if active and last_sent is not None:
        return "recovered"
    return None


def _condition(reason: str, url: str, degraded: bool):
    from app.services import alerts

    text = (f"El backend responde pero está degradado ({reason})." if degraded
            else f"El backend no responde al latido ({reason}).")
    return alerts.Condition(
        key=KEY, channel="Backend", title="backend sin latido" if not degraded else "backend degradado",
        text=text, details=(f"Chequeado: {url.rstrip('/')}{HEARTBEAT_PATH}",
                            "Revisar que el PC y el proceso del backend estén encendidos (SYNC-D-18 / DEC-11)."),
        link=HEARTBEAT_PATH)


def run(args: argparse.Namespace, now: datetime | None = None) -> int:
    from app.core.config import settings
    from app.services import alerts

    moment = now or datetime.now(UTC)
    outcome, _body, reason = probe(args.url, args.timeout)
    problem = outcome == "down" or (outcome == "degraded" and args.alert_on_degraded)
    print(f"Latido: {outcome} ({reason})")
    state_path = Path(args.state_file)
    state = _load(state_path)
    action = decide(state, problem, moment)
    exit_code = {"ok": EXIT_OK, "degraded": EXIT_DEGRADED, "down": EXIT_DOWN}[outcome]
    if action is None:
        return exit_code
    since = _parse(state.get("since")) if state.get("active") else None
    since = since or moment
    cond = _condition(reason, args.url, degraded=outcome == "degraded")
    if args.dry_run:
        msg = alerts.build_message(action, cond, since, moment)
        print(f"--- DRY-RUN ({action}): no se envia ni se guarda estado ---")
        print(f"Asunto: {msg['Subject']}")
        print(msg.get_content())
        return exit_code
    if not settings.alerts_enabled:
        print("ALERTS_ENABLED esta apagada: no se envia el aviso.")
        return exit_code
    if not alerts.send_condition(action, cond, since, moment):
        print("Aviso no enviado (revisar ALERT_EMAIL_TO, ALERT_SMTP_HOST y el log); se reintenta en la proxima corrida.")
        return exit_code
    print(f"Aviso enviado: {action}.")
    if action == "recovered":
        _save(state_path, {"active": False, "last_resolved_at": moment.isoformat()})
    else:
        _save(state_path, {"active": True, "since": since.isoformat(), "last_sent_at": moment.isoformat()})
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chequeo externo del latido del backend (correo si no responde).")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL base del backend (por defecto {DEFAULT_URL}).")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout en segundos (por defecto 10).")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE), help="Archivo JSON de deduplicacion.")
    parser.add_argument("--alert-on-degraded", action="store_true", help="Avisar tambien si responde 'degraded'.")
    parser.add_argument("--dry-run", action="store_true", help="Imprime el aviso sin enviarlo ni guardar estado.")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
