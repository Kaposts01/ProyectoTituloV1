"""Job de paridad diaria VirtualPOS (VP-PAR-11): reportes PAT importados vs `vp_charges`, SOLO LECTURA.

Detras de `VP_PARITY_CHECK_ENABLED` (apagada por defecto): con la bandera apagada no hace nada. Corre despues de la sync
nocturna; si todavia hay una corrida `running`, se omite ese dia (no espera ni expira corridas: no escribe nada).
El resultado (mes y cantidades, nada personal) va al log: WARNING si hay diferencias en la ventana, INFO si cuadra.
No escribe en `sync_runs` (un `source` nuevo apareceria como canal en los KPI) ni en `etl_runs`.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.services import vp_parity

logger = logging.getLogger(__name__)

JOB_VP_PARITY = "vp_parity_check"


def _run_parity() -> vp_parity.VpParityResult | None:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        if db.scalar(select(EtlRun.id).where(EtlRun.status == "running").limit(1)) is not None:
            logger.info("vp_parity_check: hay una sincronizacion en curso; se omite la paridad de hoy.")
            return None
        return vp_parity.compute_vp_parity(db)
    finally:
        db.rollback()
        db.close()


async def vp_parity_check() -> None:
    if not settings.vp_parity_check_enabled:
        return
    try:
        result = await asyncio.to_thread(_run_parity)
    except Exception as exc:  # noqa: BLE001 - un tick fallido no debe tumbar el scheduler
        logger.warning("vp_parity_check: fallo (%s)", type(exc).__name__)
        return
    if result is None:
        return
    if not result.has_report:
        logger.info("vp_parity_check: sin reportes PAT importados; nada que comparar.")
        return
    totals = result.totals()
    if result.ok:
        logger.info("vp_parity_check: paridad OK (%s a %s) %s", result.window_start, result.window_end, totals)
    else:
        logger.warning(
            "vp_parity_check: diferencias en %d mes(es) (%s a %s): meses=%s totales=%s",
            len(result.differences),
            result.window_start,
            result.window_end,
            [m.month for m in result.differences],
            totals,
        )
