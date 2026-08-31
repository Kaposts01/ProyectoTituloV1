from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.payku.client import PaykuClient
from app.models.sync_run import SyncRun
from app.services.read_only_provider_sync import Resource, sync_read_only_provider

SOURCE = "payku"


async def sync_payku(db: Session) -> SyncRun:
    resources: list[Resource] = [
        ("client", 100, True, lambda client, page: client.list_clients(page=page, per_page=100)),
        ("plan", 100, False, lambda client, _: client.list_plans()),
        ("subscription", 100, True, lambda client, page: client.list_subscriptions(page=page, per_page=100)),
        ("transaction", 100, True, lambda client, page: client.list_transactions(page=page, per_page=100)),
    ]
    return await sync_read_only_provider(
        db,
        source=SOURCE,
        client_factory=PaykuClient,
        resources=resources,
        secrets=(settings.payku_api_key, settings.payku_secret_key),
    )
