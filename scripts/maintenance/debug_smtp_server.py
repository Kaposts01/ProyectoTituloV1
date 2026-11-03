"""d137 (L5-ALERTAS): servidor SMTP de depuracion local, SIN dependencias nuevas (solo biblioteca estandar).

Acepta correos en `127.0.0.1:<puerto>` y los IMPRIME (asunto y cuerpo); con `--out-dir` ademas los guarda como `.eml`.
NUNCA reenvia nada: no hay ningun relay ni conexion de salida. Sirve para probar las alertas en sandbox (ver
docs/data/alerts.md, «Probar en sandbox»). Python 3.12+ ya no trae `smtpd` y `aiosmtpd` no esta en el venv.

Uso (PowerShell, desde la raiz del repo; Ctrl+C para cortar):
    .venv\\Scripts\\python.exe scripts\\maintenance\\debug_smtp_server.py --port 1025
    .venv\\Scripts\\python.exe scripts\\maintenance\\debug_smtp_server.py --port 1025 --out-dir $env:TEMP\\alertas

Habla lo minimo de SMTP (EHLO/HELO, MAIL, RCPT, DATA, RSET, NOOP, QUIT); sin STARTTLS ni AUTH, por eso las alertas
deben ir con `ALERT_SMTP_STARTTLS=false` y sin `ALERT_SMTP_USER`/`ALERT_SMTP_PASSWORD`. De los destinatarios solo
imprime la cantidad.
"""

from __future__ import annotations

import argparse
import socketserver
import threading
import uuid
from email import message_from_bytes, policy
from pathlib import Path

MAX_MESSAGE_BYTES = 1_000_000


class _Handler(socketserver.StreamRequestHandler):
    server: DebugSMTPServer

    def _reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def handle(self) -> None:
        self._reply("220 synkmetrix-debug-smtp listo (no reenvia nada)")
        recipients: list[str] = []
        while True:
            raw = self.rfile.readline(4096)
            if not raw:
                return
            command = raw.decode("utf-8", "replace").strip()
            verb = command.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                self._reply("250 synkmetrix-debug-smtp")
            elif verb == "MAIL":
                recipients = []
                self._reply("250 OK")
            elif verb == "RCPT":
                recipients.append(command)
                self._reply("250 OK")
            elif verb == "DATA":
                self._reply("354 Fin con <CRLF>.<CRLF>")
                self._receive(len(recipients))
                recipients = []
                self._reply("250 OK: recibido (no se reenvia)")
            elif verb in ("RSET", "NOOP"):
                recipients = [] if verb == "RSET" else recipients
                self._reply("250 OK")
            elif verb == "QUIT":
                self._reply("221 Adios")
                return
            else:
                self._reply("502 Comando no soportado")

    def _receive(self, n_recipients: int) -> None:
        lines: list[bytes] = []
        size = 0
        while True:
            line = self.rfile.readline(MAX_MESSAGE_BYTES)
            if not line or line in (b".\r\n", b".\n"):
                break
            if line.startswith(b".."):
                line = line[1:]
            size += len(line)
            if size <= MAX_MESSAGE_BYTES:
                lines.append(line)
        self.server.deliver(b"".join(lines), n_recipients)


class DebugSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], out_dir: Path | None = None, quiet: bool = False) -> None:
        super().__init__(address, _Handler)
        self.out_dir = out_dir
        self.quiet = quiet
        self.messages: list = []
        self._lock = threading.Lock()

    def deliver(self, data: bytes, n_recipients: int) -> None:
        msg = message_from_bytes(data, policy=policy.default)
        with self._lock:
            self.messages.append(msg)
        if self.out_dir is not None:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            (self.out_dir / f"alerta-{uuid.uuid4().hex[:8]}.eml").write_bytes(data)
        if not self.quiet:
            body = msg.get_body(preferencelist=("plain",))
            print("=" * 72)
            print(f"Asunto: {msg['Subject']}  (destinatarios: {n_recipients})")
            print(body.get_content() if body is not None else "(sin cuerpo de texto)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SMTP de depuracion local: imprime los correos, no reenvia nada.")
    parser.add_argument("--host", default="127.0.0.1", help="Interfaz (por defecto 127.0.0.1, solo este equipo).")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--out-dir", type=Path, default=None, help="Carpeta donde guardar cada correo como .eml.")
    args = parser.parse_args(argv)
    with DebugSMTPServer((args.host, args.port), out_dir=args.out_dir) as server:
        print(f"SMTP de depuracion escuchando en {args.host}:{args.port} (Ctrl+C para salir). No reenvia nada.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
