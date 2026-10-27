"""Informacion del ambiente y selector Produccion/Sandbox (solo navegacion entre dos instancias)."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import access_cookie_name, require_permissions
from app.models.auth import User
from app.scheduler.jobs.sync_all import channel_is_enabled

router = APIRouter()

_LABELS = {"production": "Producción", "sandbox": "Sandbox", "qa": "QA"}


_CHANNEL_ORDER = ("virtualpos1", "virtualpos2", "toku", "payku")


def enabled_channels() -> list[str]:
    """Canales habilitados en el ambiente actual (misma regla que el scheduler). TCH es Excel: siempre."""
    return [c for c in _CHANNEL_ORDER if channel_is_enabled(c)] + ["tch"]


def _safe_url(raw: str) -> str | None:
    value = (raw or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return value


@router.get("/environment")
def get_environment() -> dict:
    mode = settings.env_mode
    return {
        "app_env": mode,
        "label": _LABELS[mode],
        "is_production": settings.is_production,
        "access_cookie_name": access_cookie_name(mode),
        "enabled_channels": enabled_channels(),
    }


@router.get("/environment/switch")
def get_environment_switch(
    _: Annotated[User, Depends(require_permissions("system.environment.switch"))],
) -> dict:
    if settings.is_production:
        target, raw = "sandbox", settings.sandbox_app_url
    else:
        target, raw = "production", settings.production_app_url
    return {"target_env": target, "target_label": _LABELS[target], "url": _safe_url(raw)}
