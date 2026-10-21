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
