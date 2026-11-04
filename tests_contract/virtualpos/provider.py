"""Acceso crudo al sandbox usando VirtualPOSClient (mismas cabeceras/firma que la app). Sin BD."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.integrations.virtualpos.client import VirtualPOSClient

PAUSE_SECONDS = 0.3
READ_BACKOFF = (1.0, 2.0, 4.0)


def chile_today() -> datetime:
    """'Hoy' conservador (UTC-4, el mas atrasado de Chile) para no caer en 'ayer' por zona horaria."""
    return datetime.now(UTC) - timedelta(hours=4)


@dataclass
class Resp:
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    transport_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def error_code(self) -> str | None:
        err = self.body.get("error") if isinstance(self.body, dict) else None
        return str(err.get("error_code")) if isinstance(err, dict) and err.get("error_code") else None


async def _request(method: str, path: str, params: dict[str, Any] | None, payload: dict[str, Any] | None) -> Resp:
    try:
        async with VirtualPOSClient() as client:
            raw = await client._client.request(method, path, params=params, json=payload)
    except httpx.HTTPError as exc:
        return Resp(status=None, transport_error=type(exc).__name__)
    try:
        body = raw.json()
    except ValueError:
        body = None
    return Resp(status=raw.status_code, headers={k.lower(): v for k, v in raw.headers.items()}, body=body)


def call(
    method: str, path: str, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None
) -> Resp:
    """Una llamada. Pausa de ~300 ms antes. Reintenta con backoff SOLO lecturas (GET) ante 429/5xx/transporte."""
    method = method.upper()
    attempts = len(READ_BACKOFF) + 1 if method == "GET" else 1
    resp = Resp(status=None)
    for attempt in range(attempts):
        time.sleep(PAUSE_SECONDS)
        resp = asyncio.run(_request(method, path, params, payload))
        retryable = resp.status is None or resp.status == 429 or resp.status >= 500
        if not retryable or attempt == attempts - 1:
            break
        time.sleep(READ_BACKOFF[attempt])
    return resp


def records(body: Any, *keys: str) -> list[dict[str, Any]]:
    """Lista de registros de una respuesta: lista directa, `keys` o la primera lista de dicts que aparezca."""
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in keys:
            if isinstance(body.get(key), list):
                return [r for r in body[key] if isinstance(r, dict)]
        for value in body.values():
            if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
                return list(value)
    return []


def charge_obj(body: Any) -> dict[str, Any]:
    """Objeto charge de una respuesta (`charge` o el propio cuerpo)."""
    if isinstance(body, dict):
        inner = body.get("charge")
        return inner if isinstance(inner, dict) else body
    return {}


def charge_id_of(body: Any) -> str | None:
    cid = charge_obj(body).get("id")
    return str(cid) if cid else None
