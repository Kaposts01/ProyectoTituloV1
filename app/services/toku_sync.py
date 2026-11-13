from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.toku.client import TokuClient
from app.models.sync_run import SyncRun
from app.services.channel_store import store_toku_resources
from app.services.read_only_provider_sync import (
    Resource,
    WindowedRead,
    sync_read_only_provider,
)
from app.services.sync_progress import ProgressCallback

SOURCE = "toku"

# L7-CIERRE: recursos secundarios. Un 404 en ellos (el sandbox responde 404 en `/organization/payments`) los deja
# omitidos y la corrida sigue (`partial`). Clientes, suscripciones, facturas y transacciones son esenciales: su error
# (y cualquier 401/403) sigue haciendo fallar la corrida.
OPTIONAL_RESOURCES = frozenset({"payment", "payment_method"})

# CRM-14B: `/organization/payments` no figura en la referencia publica de Toku (docs/integrations/toku/resources/
# postman-audit.md, X1) y la organizacion de sandbox responde 404 siempre (docs/tasks.md, 2026-10-28). Fuera de
# produccion no se pide: la corrida termina `completed` y `resource_stats.payment` queda omitido con este motivo. En
# produccion no cambia nada (se sigue pidiendo y un 404 lo deja `partial`, L7-CIERRE).
SANDBOX_EXCLUDED_RESOURCES = {"payment": "not_available_in_sandbox"}


def excluded_resources() -> dict[str, str]:
    return {} if settings.is_production else dict(SANDBOX_EXCLUDED_RESOURCES)

# SYNC-O-02: solo las transacciones se leen por ventana (son ~80 % del tiempo de Toku). Detras de
# `SYNC_WINDOWED_READS_ENABLED`; DEC-03 sigue abierta (el filtro puede ser por fecha de transaccion o de
# inicializacion), por eso la guarda mira ambas fechas y la ventana se solapa 48 h con la corrida anterior.
WINDOWED: dict[str, WindowedRead] = {
    "transaction": WindowedRead(
        read_page=lambda client, page, window: client.list_transactions(
            page=page, page_size=100, start_date=window.start_date, end_date=window.end_date
        ),
        date_fields=("transaction_date", "initialization_date"),
    ),
}


async def sync_toku(db: Session, progress_callback: ProgressCallback | None = None) -> SyncRun:
    resources: list[Resource] = [
        ("customer", 100, True, lambda client, page: client.list_customers(page=page, page_size=100)),
        ("subscription", 100, True, lambda client, page: client.list_subscriptions(page=page, page_size=100)),
        ("invoice", 100, True, lambda client, page: client.list_invoices(page=page, page_size=100)),
        ("transaction", 100, True, lambda client, page: client.list_transactions(page=page, page_size=100)),
        ("payment", 100, True, lambda client, page: client.list_payments(page=page, page_size=100)),
        ("payment_method", 100, True, lambda client, page: client.list_payment_methods(page=page, page_size=100)),
    ]
    return await sync_read_only_provider(
        db,
        source=SOURCE,
        client_factory=TokuClient,
        resources=resources,
        secrets=(settings.toku_api_key,),
        channel_store_fn=store_toku_resources,
        progress_callback=progress_callback,
        windowed=WINDOWED,
        optional_resources=OPTIONAL_RESOURCES,
        excluded_resources=excluded_resources(),
    )
