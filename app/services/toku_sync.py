from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.toku.client import TokuClient
from app.models.sync_run import SyncRun
from app.services.channel_store import store_toku_resources
from app.services.read_only_provider_sync import Resource, sync_read_only_provider
from app.services.sync_progress import ProgressCallback

SOURCE = "toku"


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
    )
