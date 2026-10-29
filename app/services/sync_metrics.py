"""Instrumentacion por fase y recurso de una corrida de sync (SYNC-O-01 / SYNC-O-16), sin migracion.

`etl_runs`/`sync_runs` no tienen columnas JSON, asi que cada corrida deja:
  * una linea de log estructurada (logger ``sync.metrics``, JSON en una linea) y
  * una fila en ``source_records`` (``source='sync_metrics'``, ``resource_type='run'``, ``external_id=<run_id>``)
    con las fases: ``{"run_id", "phases": [{"phase", "resource", "seconds", ...}], "notes": {...}}``.
Solo se guardan nombres de fase/recurso, duraciones y conteos: nada personal, nada del proveedor. Un fallo al
registrar metricas nunca interrumpe la corrida.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord

logger = logging.getLogger("sync.metrics")

SOURCE = "sync_metrics"
RESOURCE_TYPE = "run"


def _clean(value: Any) -> Any:
    if isinstance(value, bool | int | float):
        return value
    if value is None:
        return None
    return str(value)[:100]


class RunMetrics:
    def __init__(self, run_id: str) -> None:
        self.run_id = str(run_id)
        self.phases: list[dict[str, Any]] = []
        self.notes: dict[str, Any] = {}

    def add(self, phase: str, resource: str | None = None, seconds: float | None = None, **extra: Any) -> None:
        entry: dict[str, Any] = {"phase": phase, "resource": resource}
        if seconds is not None:
            entry["seconds"] = round(seconds, 3)
        entry.update({k: _clean(v) for k, v in extra.items()})
        self.phases.append(entry)

    @contextmanager
    def timed(self, phase: str, resource: str | None = None, **extra: Any) -> Iterator[dict[str, Any]]:
        """Cronometra un bloque; el dict cedido admite completar conteos (p. ej. ``info['records'] = n``)."""
        info: dict[str, Any] = dict(extra)
        started = time.perf_counter()
        try:
            yield info
        finally:
            self.add(phase, resource, time.perf_counter() - started, **info)

    def note(self, key: str, value: Any) -> None:
        self.notes[key] = _clean(value)

    def payload(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "phases": self.phases, "notes": self.notes}

    def persist(self, db: Session) -> None:
        """Log estructurado + fila en source_records. No hace commit y nunca lanza."""
        payload = self.payload()
        try:
            logger.info("sync_metrics %s", json.dumps(payload, default=str, ensure_ascii=False))
        except Exception:  # noqa: BLE001  # pragma: no cover - defensivo
            return
        try:
            statement = insert(SourceRecord).values(
                source=SOURCE, resource_type=RESOURCE_TYPE, external_id=self.run_id, payload=payload
            )
            db.execute(
                statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload})
            )
            db.flush()
        except Exception as exc:  # noqa: BLE001 - las metricas nunca rompen la corrida
            logger.warning("No se pudieron persistir las metricas del run %s (%s).", self.run_id, type(exc).__name__)


# --- colector activo (evita cambiar la firma de los sync_*) -------------------------------------------------

_current: ContextVar[RunMetrics | None] = ContextVar("sync_metrics_current", default=None)


def activate(metrics: RunMetrics) -> Token:
    """Activa `metrics` para el contexto actual: los sync_* lo encuentran con `resource_timer`."""
    return _current.set(metrics)


def deactivate(token: Token) -> None:
    _current.reset(token)


class ResourceTimer:
    """Acumula, para un recurso de un canal, el tiempo de extraccion (API) y el de upsert (staging/canal)."""

    def __init__(self, metrics: RunMetrics | None, channel: str, resource: str) -> None:
        self._metrics = metrics
        self.channel = channel
        self.resource = resource
        self.api_seconds = 0.0
        self.upsert_seconds = 0.0
        self.pages = 0
        self.records = 0

    @contextmanager
    def api(self) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.api_seconds += time.perf_counter() - started
            self.pages += 1

    @contextmanager
    def upsert(self, records: int = 0) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.upsert_seconds += time.perf_counter() - started
            self.records += records

    def finish(self) -> None:
        if self._metrics is not None:
            self._metrics.add(
                "sync_resource",
                f"{self.channel}.{self.resource}",
                api_seconds=round(self.api_seconds, 3),
                upsert_seconds=round(self.upsert_seconds, 3),
                pages=self.pages,
                records=self.records,
            )


def resource_timer(channel: str, resource: str) -> ResourceTimer:
    """Cronometro del recurso; sin colector activo no registra nada (los sync_* corren igual)."""
    return ResourceTimer(_current.get(), channel, resource)
