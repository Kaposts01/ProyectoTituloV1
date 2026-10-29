"""Usuario TEMPORAL con contrasena aleatoria para capturas visuales en el SANDBOX (decision D21).

Uso (desde la raiz del repo, con el venv del proyecto; NO hace falta fijar APP_ENV, el script lo fija):

    # Normal: crea el usuario, ejecuta el comando hijo con PW_USER/PW_PASS en su entorno y borra el usuario.
    .venv\\Scripts\\python.exe scripts\\sandbox\\ephemeral_user.py session -- node scripts\\visual\\capture_sandbox.mjs autologin --capture

    # Crea el usuario y ejecuta el hijo SIN borrar despues (el usuario queda; bórrelo con `cleanup`).
    .venv\\Scripts\\python.exe scripts\\sandbox\\ephemeral_user.py create -- <comando...>

    # Borra TODOS los usuarios `PW-*` de la base sandbox (respaldo si una sesion se corto a la fuerza).
    .venv\\Scripts\\python.exe scripts\\sandbox\\ephemeral_user.py cleanup

Reglas de seguridad (falla cerrado):
- Fija ``APP_ENV=sandbox`` ANTES de importar ``settings`` (solo en ``main()``; importar el modulo no toca el entorno) y
  aborta si la base resuelta no contiene ``sandbox`` o si es ``crm``/``*_test``/cualquier otra. Confirma con
  ``SELECT current_database()``.
- Usuario ``PW-<aleatorio>`` con el rol de MENOR privilegio que deja ver las pantallas: ``ejecutivo`` (por defecto);
  ``soporte`` solo con ``--role soporte``; ``admin`` solo con ``--role admin --i-know``. No crea roles distintos de los
  predefinidos y no modifica el codigo de autenticacion: la contrasena se guarda con el MISMO hash de la app
  (``app.core.security.hash_password``); no existe ninguna via sin contrasena.
- La contrasena sale de ``secrets``; NUNCA se imprime, no se escribe en disco ni en logs y no va en argv: solo viaja por
  variable de entorno del proceso hijo (``PW_USER`` / ``PW_PASS``). Solo se imprime el nombre de usuario (no es secreto).
- ``session`` garantiza el borrado con try/finally, tambien si el hijo falla o se interrumpe (Ctrl+C). Una muerte forzada
  del proceso Python (kill) no puede ejecutar el finally: use ``cleanup``.
- Las sesiones son JWT sin estado en servidor (cookie): no hay tabla de sesiones o tokens que borrar; al borrar el usuario
  el token deja de servir (``get_current_user`` busca al usuario) y caduca solo.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PREFIX = "PW-"
ALLOWED_ROLES = ("ejecutivo", "soporte", "admin")
ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    print(f"ABORTADO: {message}", file=sys.stderr)
    raise SystemExit(2)


def guard_database(name: str | None) -> str:
    """Falla cerrado salvo que la base sea claramente un sandbox. Nunca `crm`, `*_test` ni otra."""
    value = (name or "").strip().lower()
    if not value or value == "crm" or value.endswith("_test") or "sandbox" not in value:
        fail("la base resuelta no es el sandbox (se exige un nombre que contenga 'sandbox', p. ej. crm_sandbox). No se escribe nada.")
    return value


def _hash(password: str, hasher: Callable[[str], str] | None) -> str:
    if hasher is not None:
        return hasher(password)
    from app.core.security import hash_password  # el mismo hash de la app

    return hash_password(password)


def create_user(db: Any, role: str = "ejecutivo", *, i_know: bool = False, hasher: Callable[[str], str] | None = None) -> tuple[str, str]:
    """Crea `PW-<aleatorio>` con un unico rol y devuelve (usuario, contrasena). No hace commit."""
    from sqlalchemy import select

    from app.models.auth import Role, User
    from app.services.rbac import seed_default_roles

    if role not in ALLOWED_ROLES:
        fail(f"rol no permitido: {role!r}. Permitidos: {', '.join(ALLOWED_ROLES)}.")
    if role == "admin" and not i_know:
        fail("el rol admin exige --role admin --i-know (privilegio maximo para una cuenta temporal).")
    row = db.scalar(select(Role).where(Role.name == role))
    if row is None and role in ("ejecutivo", "soporte"):
        seed_default_roles(db)  # crea/completa solo los roles predefinidos de lectura (idempotente)
        row = db.scalar(select(Role).where(Role.name == role))
    if row is None:
        fail(f"el rol {role!r} no existe en esta base.")
    username = f"{PREFIX}{secrets.token_hex(5)}"
    password = secrets.token_urlsafe(24)
    db.add(User(username=username, password_hash=_hash(password, hasher), is_active=True, roles=[row]))
    db.flush()
    return username, password


def cleanup_users(db: Any) -> int:
    """Borra todos los usuarios con prefijo `PW-` (y sus vinculos de rol). No hace commit. Devuelve cuantos."""
    from sqlalchemy import delete, select

    from app.models.auth import User, user_roles

    ids = list(db.scalars(select(User.id).where(User.username.like(f"{PREFIX}%"))))
    if not ids:
        return 0
    db.execute(delete(user_roles).where(user_roles.c.user_id.in_(ids)))
    db.execute(delete(User).where(User.id.in_(ids)))
    db.flush()
    return len(ids)


def _cleanup_with_new_session(session_factory: Callable[[], Any]) -> int:
    db = session_factory()
    try:
        removed = cleanup_users(db)
        db.commit()
        return removed
    finally:
        db.close()


def _run_child(argv: list[str], username: str, password: str) -> int:
    env = {**os.environ, "PW_USER": username, "PW_PASS": password}
    return subprocess.run(argv, env=env, check=False).returncode


def run_session(
    session_factory: Callable[[], Any], child_argv: list[str], role: str, i_know: bool, *, keep: bool = False,
    hasher: Callable[[str], str] | None = None,
) -> int:
    """Crea el usuario, ejecuta el hijo con las credenciales en su entorno y (salvo `keep`) lo borra SIEMPRE."""
    db = session_factory()
    try:
        username, password = create_user(db, role, i_know=i_know, hasher=hasher)
        db.commit()
    finally:
        db.close()
    print(f"Usuario temporal creado: {username} (rol {role}). La contrasena no se muestra.")
    try:
        return _run_child(child_argv, username, password)
    finally:
        del password
        if not keep:
            try:
                removed = _cleanup_with_new_session(session_factory)
                print(f"Usuarios temporales borrados: {removed}.")
            except Exception as exc:  # noqa: BLE001  (no ocultar el fallo: hay que correr `cleanup`)
                print(f"ERROR: no se pudo borrar el usuario temporal ({type(exc).__name__}). Ejecute 'cleanup'.", file=sys.stderr)


def _bootstrap_sandbox() -> tuple[Callable[[], Any], str]:
    """Fija APP_ENV=sandbox ANTES de importar settings y valida la base. Solo se llama desde main()."""
    os.environ["APP_ENV"] = "sandbox"
    os.chdir(ROOT)  # el .env se resuelve relativo al directorio actual
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import text

    from app.core.config import settings
    from app.db.session import SessionLocal, engine

    if settings.env_mode != "sandbox":
        fail(f"APP_ENV efectivo es {settings.env_mode!r}; se exige sandbox.")
    name = guard_database(engine.url.database)
    with engine.connect() as conn:
        live = conn.execute(text("SELECT current_database()")).scalar()
    if guard_database(live) != name:
        fail("current_database() no coincide con la base configurada.")
    return SessionLocal, name


def main(argv: list[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    child: list[str] = []
    if "--" in args_in:
        split = args_in.index("--")
        args_in, child = args_in[:split], args_in[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "session"):
        p = sub.add_parser(name)
        p.add_argument("--role", default="ejecutivo", choices=ALLOWED_ROLES)
        p.add_argument("--i-know", action="store_true", help="confirma el rol admin")
    sub.add_parser("cleanup")
    args = parser.parse_args(args_in)

    if args.command in ("create", "session") and not child:
        fail("falta el comando hijo tras '--': la contrasena nunca se muestra, solo viaja al hijo por el entorno.")
    session_factory, db_name = _bootstrap_sandbox()
    print(f"Base: {db_name} (sandbox).")
    if args.command == "cleanup":
        print(f"Usuarios temporales borrados: {_cleanup_with_new_session(session_factory)}.")
        return 0
    return run_session(session_factory, child, args.role, args.i_know, keep=args.command == "create")


if __name__ == "__main__":
    raise SystemExit(main())
