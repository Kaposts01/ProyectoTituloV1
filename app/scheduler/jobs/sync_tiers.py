"""SYNC-O-09: corredor por niveles caliente / tibio / frio (decision D10). Detras de `SYNC_TIERS_ENABLED` (apagada).

- Caliente (`sync_hot`): cada 3 h de 07:00 a 22:00 (minuto 30, para no chocar con la reconciliacion dirigida de las
  horas en punto). Solo los canales API (VirtualPOS 1 y 2, Toku, Payku) y SOLO por ventana de fecha: sin
  `SYNC_WINDOWED_READS_ENABLED` no corre (seria una lectura completa cada 3 h). Sin captura de glosas ni TCH.
- Tibio: la corrida diaria de las 02:00 (`sync_all_channels`, sin cambios).
- Frio (`sync_cold`): domingo 01:00. Todos los canales con lectura completa forzada (ignora las ventanas: cubre los
  cambios de estado de registros viejos), consolidacion completa (sin lectura diferencial) y TCH aunque no haya
  carga nueva. El domingo la tibia de las 02:00 encuentra la fria en curso y se omite (lock de corrida, SYNC-O-11).

Los niveles comparten el lock atomico de corrida: nunca corren dos a la vez, ni junto a un ETL Core o una importacion
TCH. Los reintentos son los de siempre (SYNC-D-10): reintento HTTP con `Retry-After` en los clientes y, para la tibia y
la fria, el job `retry_failed_channels` de las 04:00 sobre los canales fallidos de la ultima corrida. Un fallo de la
caliente no se reintenta: la siguiente caliente (3 h despues) vuelve a leer la ventana, que se solapa.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.scheduler.jobs.sync_all import TIER_COLD, TIER_HOT, sync_all_channels

logger = logging.getLogger(__name__)

JOB_SYNC_HOT = "sync_tier_hot"
JOB_SYNC_COLD = "sync_tier_cold"

HOT_CHANNELS = ["virtualpos1", "virtualpos2", "toku", "payku"]
HOT_HOURS = "7,10,13,16,19,22"  # D10: cada 3 h entre 07:00 y 22:00


async def sync_hot() -> None:
    """Nivel caliente. No hace nada con `SYNC_TIERS_ENABLED` o `SYNC_WINDOWED_READS_ENABLED` apagadas."""
    if not settings.sync_tiers_enabled:
        return
    if not settings.sync_windowed_reads_enabled:
        logger.warning(
            "sync_hot omitida: requiere SYNC_WINDOWED_READS_ENABLED (sin ventanas seria una lectura completa cada 3 h)."
        )
        return
    await sync_all_channels(channels=list(HOT_CHANNELS), tier=TIER_HOT)


async def sync_cold() -> None:
    """Nivel frio. No hace nada con `SYNC_TIERS_ENABLED` apagada."""
    if not settings.sync_tiers_enabled:
        return
    await sync_all_channels(tier=TIER_COLD)
