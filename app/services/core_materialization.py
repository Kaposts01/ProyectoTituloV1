"""Materialize provider customer identities into the additive Core.

This deliberately performs no cross-provider matching: every source identity gets
its own Core client until an approved identity-review workflow links it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import CoreClient, ExternalIdentity
from app.models.payku_channel import PaykuClient
from app.models.tch import TchCliente
from app.models.toku_channel import TokuCustomer
from app.models.vp import VpClient


def _materialize_identity(db: Session, source: str, external_id: str) -> bool:
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.source == source,
            ExternalIdentity.resource_type == "client",
            ExternalIdentity.external_id == external_id,
        )
    )
    if identity is not None:
        return False
    client = CoreClient()
    db.add(client)
    db.flush()
    db.add(
        ExternalIdentity(
            client_id=client.id,
            source=source,
            resource_type="client",
            external_id=external_id,
            link_reason="source_identity",
        )
    )
    return True


def materialize_core_clients(db: Session, sources: list[str] | None = None) -> int:
    """Create one Core client per previously unseen provider identity.

    A later reviewed identity workflow may associate several external identities
    with a single client. This safe first pass never uses personal attributes.
    """
    requested = set(sources or ["virtualpos", "toku", "payku", "tch"])
    records = []
    if "virtualpos" in requested:
        records.extend((row.platform, row.external_id) for row in db.scalars(select(VpClient)))
    if "toku" in requested:
        records.extend(("toku", row.external_id) for row in db.scalars(select(TokuCustomer)))
    if "payku" in requested:
        records.extend(("payku", row.external_id) for row in db.scalars(select(PaykuClient)))
    if "tch" in requested:
        records.extend(("tch", row.rut) for row in db.scalars(select(TchCliente)))

    created = sum(_materialize_identity(db, source, external_id) for source, external_id in records)
    db.commit()
    return created
