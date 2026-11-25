"""ML-10 bounded manifest: store references and hashes, never input glosas."""

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import token
from app.ml.recommendation import (
    ENGINE_VERSION,
    POLICY_VERSION,
    SOURCES,
    CoreSnapshot,
    snapshot_hash,
)
from app.ml.taxonomy import RULES_VERSION, TAXONOMY_VERSION

BATCH_VERSION = "ml-shadow-batch-v1"


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Corte ML sin zona")
    return value.astimezone(UTC)


def bundle_sha256() -> str:
    return digest({"batch": BATCH_VERSION, "engine": ENGINE_VERSION, "policy": POLICY_VERSION,
                   "rules": RULES_VERSION, "taxonomy": TAXONOMY_VERSION, "model_mode": "none"})


@dataclass(frozen=True, slots=True)
class ItemRef:
    ordinal: int
    source: str
    resource_type: str
    resource_id: UUID
    evidence_id: UUID
    input_sha256: str


@dataclass(frozen=True, slots=True)
class BatchPlan:
    id: str
    items: tuple[ItemRef, ...]
    bundle_sha256: str


def plan_batch(*, receipt_id: UUID, source: str, cutoff: datetime, core_sha256: str,
               snapshots: tuple[CoreSnapshot, ...], max_age_seconds: int = 3600,
               max_attempts: int = 3) -> BatchPlan:
    if not isinstance(receipt_id, UUID) or source not in SOURCES:
        raise ValueError("Confirmacion Core invalida")
    cutoff = instant(cutoff)
    token(core_sha256)
    if (not isinstance(snapshots, tuple) or len(snapshots) > 1000
            or type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400
            or type(max_attempts) is not int or not 1 <= max_attempts <= 5):
        raise ValueError("Limites de lote invalidos")
    unique, entities = {}, set()
    for snapshot in snapshots:
        if not isinstance(snapshot, CoreSnapshot) or snapshot.source != source or instant(snapshot.as_of) != cutoff:
            raise ValueError("Snapshot de otro canal o corte")
        sha = snapshot_hash(snapshot)
        identity = (snapshot.resource_type, snapshot.resource_id, snapshot.evidence_id)
        if sha in unique or identity in entities:
            raise ValueError("Evidencia duplicada en el lote")
        unique[sha] = snapshot
        entities.add(identity)
    items = tuple(ItemRef(i, source, row.resource_type, row.resource_id, row.evidence_id, sha)
                  for i, (sha, row) in enumerate(sorted(unique.items())))
    refs = []
    for item in items:
        value = asdict(item)
        value.update(resource_id=str(item.resource_id), evidence_id=str(item.evidence_id))
        refs.append(value)
    bundle = bundle_sha256()
    manifest = {"receipt": str(receipt_id), "source": source, "cutoff": cutoff.isoformat(),
                "core_sha256": core_sha256, "bundle": bundle, "items": refs,
                "max_age_seconds": max_age_seconds, "max_attempts": max_attempts, "purpose": "synthetic"}
    return BatchPlan(digest(manifest), items, bundle)
