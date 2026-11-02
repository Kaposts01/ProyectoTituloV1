"""Bus SSE en memoria para transmitir eventos de sincronización en tiempo real.

Cada run activo tiene un RunBus con:
- historial completo de eventos (para replay al conectarse tarde)
- una asyncio.Queue por suscriptor SSE activo

Cambios de estado (RT-11): el SSE de `status_change_events` (`app/api/v1/routes/events.py`) NO depende de este bus
en memoria: relee la tabla, asi que funciona con varios workers. Aqui solo vive un contador de proceso
(`notify_status_changes`) que adelanta esa relectura cuando el cambio se registro en el mismo proceso. Es seguro
llamarlo desde cualquier hilo (los jobs y endpoints sincronos corren fuera del event loop).
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from dataclasses import dataclass, field


@dataclass
class RunBus:
    events: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: bool = False


_buses: dict[str, RunBus] = {}

_status_lock = threading.Lock()
_status_counter = itertools.count(1)
_status_seq = 0


def notify_status_changes() -> None:
    """Avisa (dentro del proceso) que hay filas nuevas en `status_change_events`. Nunca lanza."""
    global _status_seq
    with _status_lock:
        _status_seq = next(_status_counter)


def status_change_seq() -> int:
    """Numero que cambia cada vez que se llama a `notify_status_changes`."""
    return _status_seq


def create_bus(run_id: str) -> RunBus:
    bus = RunBus()
    _buses[run_id] = bus
    return bus


def close_bus(run_id: str) -> None:
    bus = _buses.get(run_id)
    if bus:
        bus.done = True
        for q in bus.subscribers:
            q.put_nowait(None)  # señal de fin


def emit(run_id: str, event: dict) -> None:
    bus = _buses.get(run_id)
    if not bus:
        return
    bus.events.append(event)
    for q in bus.subscribers:
        q.put_nowait(event)


async def subscribe(run_id: str) -> asyncio.Queue | None:
    """Crea un suscriptor; replaya eventos pasados antes de retornar la queue."""
    bus = _buses.get(run_id)
    if not bus:
        return None
    q: asyncio.Queue = asyncio.Queue()
    for event in bus.events:
        q.put_nowait(event)
    if bus.done:
        q.put_nowait(None)
    else:
        bus.subscribers.append(q)
    return q


def unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    bus = _buses.get(run_id)
    if bus and q in bus.subscribers:
        bus.subscribers.remove(q)


def get_bus(run_id: str) -> RunBus | None:
    return _buses.get(run_id)


def cleanup_bus(run_id: str) -> None:
    _buses.pop(run_id, None)
