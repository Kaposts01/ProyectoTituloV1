from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.payku.client import PaykuClient
from app.models.sync_run import SyncRun
from app.services.channel_store import store_payku_resources
from app.services.read_only_provider_sync import Resource, sync_read_only_provider
from app.services.sync_progress import ProgressCallback

SOURCE = "payku"


async def sync_payku(
    db: Session,
    progress_callback: ProgressCallback | None = None,
    transaction_start_page: int = 1,
) -> SyncRun:
    if transaction_start_page < 1:
        raise ValueError("transaction_start_page must be at least 1")

    resources: list[Resource] = [
        ("client", 100, True, lambda client, page: client.list_clients(page=page, per_page=100)),
        ("plan", 100, False, lambda client, _: client.list_plans()),
        ("subscription", 100, True, lambda client, page: client.list_subscriptions(page=page, per_page=100)),
        (
            "transaction",
            4000,
            True,
            lambda client, page: client.list_transactions(
                page=transaction_start_page + page - 1,
                per_page=4000,
                date_init=settings.payku_date_init or None,
                date_end=settings.payku_date_end or None,
            ),
        ),
    ]
    return await sync_read_only_provider(
        db,
        source=SOURCE,
        client_factory=PaykuClient,
        resources=resources,
        secrets=(settings.payku_api_key, settings.payku_secret_key),
        channel_store_fn=store_payku_resources,
        progress_callback=progress_callback,
    )
