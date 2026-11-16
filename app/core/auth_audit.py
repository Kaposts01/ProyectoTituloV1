"""Registro de accesos y fallos de autenticacion (CRM-16A) SIN datos personales.

Cada linea lleva el evento, el id interno del usuario (si se conoce) o una referencia seudonima del nombre
(HMAC truncado, `username_ref`) y la IP truncada (/24 o /48). Nunca el nombre de usuario, la clave ni el token.
"""

import logging

from app.core.rate_limit import truncate_ip, username_ref

logger = logging.getLogger("crm.auth.audit")


def log_auth_event(
    event: str,
    *,
    ip: str,
    user_id: object | None = None,
    username: str | None = None,
    detail: str | None = None,
) -> None:
    fields = [f"event={event}", f"ip={truncate_ip(ip)}"]
    if user_id is not None:
        fields.append(f"user_id={user_id}")
    elif username is not None:
        fields.append(f"user_ref={username_ref(username)}")
    if detail:
        fields.append(f"detail={detail}")
    level = logging.INFO if event in {"login_success", "logout", "password_changed"} else logging.WARNING
    logger.log(level, "auth %s", " ".join(fields))
