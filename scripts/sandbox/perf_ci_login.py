"""Inicio de sesion por script para el presupuesto de rendimiento en CI (PERF-03g).

Entra con el usuario FICTICIO de solo lectura que creo ``seed_perf_ci.py`` y escribe la cookie de sesion en un archivo
JSON con la forma que espera Lighthouse CI en ``collect.settings.extraHeaders`` (``{"Cookie": "nombre=valor"}``).

Uso (en el job de CI, con las credenciales en el entorno; nada va en argv ni se imprime):

    PERF_CI_USER=perf-ci PERF_CI_PASSWORD=<la del job> python scripts/sandbox/perf_ci_login.py \
        --base-url http://127.0.0.1:8001 --out "$RUNNER_TEMP/lhci-headers.json"

El archivo se crea con permisos 0600 fuera del arbol del repositorio (el job usa ``$RUNNER_TEMP``). Solo usa la biblioteca
estandar. Falla (codigo distinto de 0) si el inicio de sesion no devuelve 200 o no trae la cookie de acceso.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

COOKIE_PREFIX = "crm_access_token"


def fail(message: str) -> None:
    print(f"ABORTADO: {message}", file=sys.stderr)
    raise SystemExit(2)


def session_cookie(set_cookie_headers: list[str]) -> str:
    """`nombre=valor` de la cookie de acceso a partir de los encabezados Set-Cookie."""
    for header in set_cookie_headers:
        pair = header.split(";", 1)[0].strip()
        if pair.startswith(COOKIE_PREFIX) and "=" in pair:
            return pair
    fail("el inicio de sesion no devolvio la cookie de acceso.")
    return ""


def login(base_url: str, username: str, password: str) -> str:
    if not base_url.startswith(("http://127.0.0.1", "http://localhost")):
        fail("--base-url debe ser el backend local del job (http://127.0.0.1... o http://localhost...).")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return session_cookie(response.headers.get_all("Set-Cookie") or [])
    except urllib.error.HTTPError as exc:
        fail(f"el inicio de sesion respondio {exc.code}.")
    except urllib.error.URLError as exc:
        fail(f"no se pudo conectar con el backend: {exc.reason}.")
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", required=True, help="archivo JSON de salida (fuera del repositorio)")
    args = parser.parse_args(argv)
    username = os.environ.get("PERF_CI_USER", "").strip()
    password = os.environ.get("PERF_CI_PASSWORD", "")
    if not username or not password:
        fail("PERF_CI_USER y PERF_CI_PASSWORD deben venir del entorno.")
    cookie = login(args.base_url, username, password)
    out = Path(args.out)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"Cookie": cookie}, handle)
    print(f"Sesion iniciada como {username!r}; cabecera Cookie escrita en {out.name}. El valor no se muestra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
