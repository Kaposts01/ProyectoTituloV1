"""Motor APScheduler: singleton AsyncIOScheduler con persistencia en PostgreSQL."""

from __future__ import annotations

import logging

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

JOB_SYNC_ALL = "sync_all_channels"
JOB_SYNC_RETRY = "retry_failed_channels"


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)},
            executors={"default": AsyncIOExecutor()},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
            timezone="America/Santiago",
        )
    return _scheduler


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    from app.scheduler.jobs.retry_failed import retry_failed_channels
    from app.scheduler.jobs.sync_all import sync_all_channels

    if not scheduler.get_job(JOB_SYNC_ALL):
        scheduler.add_job(
            sync_all_channels,
            trigger="cron",
            hour=2,
            minute=0,
            id=JOB_SYNC_ALL,
            name="Sincronización diaria de canales",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (02:00 America/Santiago).", JOB_SYNC_ALL)
    else:
        logger.info("Job '%s' ya registrado en DB, omitiendo.", JOB_SYNC_ALL)

    if not scheduler.get_job(JOB_SYNC_RETRY):
        scheduler.add_job(
            retry_failed_channels,
            trigger="cron",
            hour=4,
            minute=0,
            id=JOB_SYNC_RETRY,
            name="Reintento canales fallidos",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (04:00 America/Santiago).", JOB_SYNC_RETRY)
    else:
        logger.info("Job '%s' ya registrado en DB, omitiendo.", JOB_SYNC_RETRY)

    # Facturacion gestionada (solo lectura hacia el proveedor). 03:00: despues del sync de las 02:00 (datos frescos
    # para JB-36) y antes del reintento de las 04:00.
    from app.scheduler.jobs.billing_jobs import (
        JOB_BILLING_EXPIRE,
        JOB_BILLING_RENEWAL,
        JOB_BILLING_SWEEP,
        billing_expire_requests,
        billing_renewal_check,
        billing_sweep_applying,
    )

    if not scheduler.get_job(JOB_BILLING_RENEWAL):
        scheduler.add_job(
            billing_renewal_check,
            trigger="cron",
            hour=3,
            minute=0,
            id=JOB_BILLING_RENEWAL,
            name="Chequeo de renovación de calendario",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (03:00 America/Santiago).", JOB_BILLING_RENEWAL)
    if not scheduler.get_job(JOB_BILLING_EXPIRE):
        scheduler.add_job(
            billing_expire_requests,
            trigger="cron",
            minute=10,
            id=JOB_BILLING_EXPIRE,
            name="Expiración de solicitudes de cambio",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada hora, minuto 10).", JOB_BILLING_EXPIRE)
    if not scheduler.get_job(JOB_BILLING_SWEEP):
        # :05/:20/:35/:50 para no chocar con la expiracion de :10 (ambos tocan billing_change_requests).
        scheduler.add_job(
            billing_sweep_applying,
            trigger="cron",
            minute="5,20,35,50",
            id=JOB_BILLING_SWEEP,
            name="Barrido de solicitudes atascadas en 'aplicando'",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada 15 min: :05/:20/:35/:50).", JOB_BILLING_SWEEP)
