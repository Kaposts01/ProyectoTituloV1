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
JOB_WEBHOOK_PROCESSOR = "webhook_processor"
JOB_TARGETED_RECONCILE = "reconcile_targeted"


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

    # BILL-10: controles de consistencia de la Opcion A (03:30, despues del chequeo de renovacion). Detras de
    # BILLING_CONSISTENCY_CHECK_ENABLED (apagada por defecto): con la bandera apagada el job no hace nada.
    from app.scheduler.jobs.billing_jobs import (
        JOB_BILLING_CONSISTENCY,
        billing_consistency_check,
    )

    if not scheduler.get_job(JOB_BILLING_CONSISTENCY):
        scheduler.add_job(
            billing_consistency_check,
            trigger="cron",
            hour=3,
            minute=30,
            id=JOB_BILLING_CONSISTENCY,
            name="Controles de consistencia de cambios de cobro",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (03:30; detras de BILLING_CONSISTENCY_CHECK_ENABLED).", JOB_BILLING_CONSISTENCY)

    # Bajas de suscripcion (MGT-07..10): expiracion de solicitudes `pending` (cada hora, :25) y barredor de `applying`
    # atascadas (cada 15 min, :08/:23/:38/:53; no chocan con los de la Opcion A en :05/:10/:20/:35/:50). Filas en
    # `sync_runs` con el prefijo `cancellation_`, excluido de los KPI de canales.
    from app.scheduler.jobs.cancellation_jobs import (
        JOB_CANCELLATION_EXPIRE,
        JOB_CANCELLATION_SWEEP,
        cancellation_expire_requests,
        cancellation_sweep_applying,
    )

    if not scheduler.get_job(JOB_CANCELLATION_EXPIRE):
        scheduler.add_job(
            cancellation_expire_requests,
            trigger="cron",
            minute=25,
            id=JOB_CANCELLATION_EXPIRE,
            name="Expiración de solicitudes de baja",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada hora, minuto 25).", JOB_CANCELLATION_EXPIRE)
    if not scheduler.get_job(JOB_CANCELLATION_SWEEP):
        scheduler.add_job(
            cancellation_sweep_applying,
            trigger="cron",
            minute="8,23,38,53",
            id=JOB_CANCELLATION_SWEEP,
            name="Barrido de bajas atascadas en 'applying'",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada 15 min: :08/:23/:38/:53).", JOB_CANCELLATION_SWEEP)

    # RT-05: procesador de la cola de webhooks (cada minuto). Detras de WEBHOOK_PROCESSOR_ENABLED (apagada por defecto);
    # la exclusion entre workers la da FOR UPDATE SKIP LOCKED dentro del procesador.
    from app.scheduler.jobs.webhook_jobs import process_webhook_queue

    if not scheduler.get_job(JOB_WEBHOOK_PROCESSOR):
        scheduler.add_job(
            process_webhook_queue,
            trigger="interval",
            minutes=1,
            id=JOB_WEBHOOK_PROCESSOR,
            name="Procesador de webhooks",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada minuto; detras de WEBHOOK_PROCESSOR_ENABLED).", JOB_WEBHOOK_PROCESSOR)

    # RT-06: reconciliacion dirigida (cada 3 h de 07:00 a 22:00, D10). Detras de TARGETED_RECONCILE_ENABLED (apagada).
    from app.scheduler.jobs.reconcile_targeted import reconcile_targeted

    if not scheduler.get_job(JOB_TARGETED_RECONCILE):
        scheduler.add_job(
            reconcile_targeted,
            trigger="cron",
            hour="7,10,13,16,19,22",
            minute=0,
            id=JOB_TARGETED_RECONCILE,
            name="Reconciliación dirigida por ventana de riesgo",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (07,10,13,16,19,22 h; detras de TARGETED_RECONCILE_ENABLED).", JOB_TARGETED_RECONCILE)

    # SYNC-D-08: alertas por correo (cada 15 min; :02/:17/:32/:47 para no chocar con los barridos de :05/:20/:35/:50).
    # Detras de ALERTS_ENABLED (apagada por defecto): con la bandera apagada el job no hace nada.
    from app.scheduler.jobs.alert_jobs import JOB_ALERTS, check_alerts

    if not scheduler.get_job(JOB_ALERTS):
        scheduler.add_job(
            check_alerts,
            trigger="cron",
            minute="2,17,32,47",
            id=JOB_ALERTS,
            name="Alertas de sincronización por correo",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (cada 15 min; detras de ALERTS_ENABLED).", JOB_ALERTS)

    # VP-PAR-11: paridad diaria reportes PAT vs base (solo lectura, al log). 06:40, despues de la sync de las 02:00 y del
    # reintento. Detras de VP_PARITY_CHECK_ENABLED (apagada por defecto): con la bandera apagada el job no hace nada.
    from app.scheduler.jobs.vp_parity_job import JOB_VP_PARITY, vp_parity_check

    if not scheduler.get_job(JOB_VP_PARITY):
        scheduler.add_job(
            vp_parity_check,
            trigger="cron",
            hour=6,
            minute=40,
            id=JOB_VP_PARITY,
            name="Paridad VirtualPOS reportes PAT vs base",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (06:40; detras de VP_PARITY_CHECK_ENABLED).", JOB_VP_PARITY)

    # SYNC-O-09: niveles caliente y frio (D10). La tibia es `sync_all_channels` de las 02:00. Detras de SYNC_TIERS_ENABLED
    # (apagada por defecto): con la bandera apagada los dos jobs no hacen nada. La caliente exige ademas las ventanas.
    from app.scheduler.jobs.sync_tiers import HOT_HOURS, JOB_SYNC_COLD, JOB_SYNC_HOT, sync_cold, sync_hot

    if not scheduler.get_job(JOB_SYNC_HOT):
        scheduler.add_job(
            sync_hot,
            trigger="cron",
            hour=HOT_HOURS,
            minute=30,
            id=JOB_SYNC_HOT,
            name="Sincronización caliente (por ventana)",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (%s h, minuto 30; detras de SYNC_TIERS_ENABLED).", JOB_SYNC_HOT, HOT_HOURS)
    if not scheduler.get_job(JOB_SYNC_COLD):
        scheduler.add_job(
            sync_cold,
            trigger="cron",
            day_of_week="sun",
            hour=1,
            minute=0,
            id=JOB_SYNC_COLD,
            name="Sincronización fría (lectura completa)",
            replace_existing=True,
        )
        logger.info("Job '%s' registrado (domingo 01:00; detras de SYNC_TIERS_ENABLED).", JOB_SYNC_COLD)
