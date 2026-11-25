"""ML-09 bounded Core projection, on caller-owned read-only repeatable snapshot.

No Settings, ORM/session imports, provider tables, personal attributes or free text.
Raw statuses are deliberately not interpreted: source-specific mapping/coverage must
be audited before creating recommendation.CoreSnapshot. This is not a history extractor.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.ml.annotation_contract import AnnotationContext
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import token
from app.ml.recommendation import SOURCES, CoreSnapshot, State


@dataclass(frozen=True, slots=True, repr=False)
class CoreEvidence:
    source: str
    resource_type: str
    resource_id: UUID
    evidence_id: UUID | None
    subscription_id: UUID | None
    charge_id: UUID | None
    source_status: str | None
    subscription_status: str | None
    rejection_code: str | None = field(repr=False)
    rejection_at: datetime | None
    updated_at: datetime
    subscription_updated_at: datetime | None
    links_consistent: bool


_CHARGE = """
SELECT c.source, 'charge' AS resource_type, c.id AS resource_id,
       c.latest_rejection_payment_id AS evidence_id, c.subscription_id,
       c.id AS charge_id, c.source_status, s.status AS subscription_status,
       c.latest_rejection_code AS rejection_code, c.latest_rejection_at AS rejection_at,
       c.updated_at, s.updated_at AS subscription_updated_at,
       COALESCE((s.id IS NOT NULL AND s.source = c.source AND p.id IS NOT NULL
        AND p.source = c.source AND p.charge_id = c.id
        AND p.subscription_id = c.subscription_id), FALSE) AS links_consistent
FROM core_charges c
LEFT JOIN core_subscriptions s ON s.id = c.subscription_id
LEFT JOIN core_payments p ON p.id = c.latest_rejection_payment_id
WHERE c.id = :resource_id AND c.source = :source
"""
_PAYMENT = """
SELECT p.source, 'payment' AS resource_type, p.id AS resource_id,
       p.id AS evidence_id, p.subscription_id, p.charge_id, p.source_status,
       s.status AS subscription_status, p.rejection_code,
       p.rejection_reported_at AS rejection_at, p.updated_at,
       s.updated_at AS subscription_updated_at,
       COALESCE((s.id IS NOT NULL AND s.source = p.source AND
        (p.charge_id IS NULL OR (c.id IS NOT NULL AND c.source = p.source
         AND c.subscription_id = p.subscription_id))), FALSE) AS links_consistent
FROM core_payments p
LEFT JOIN core_subscriptions s ON s.id = p.subscription_id
LEFT JOIN core_charges c ON c.id = p.charge_id
WHERE p.id = :resource_id AND p.source = :source
"""


def read_core_evidence(connection: Connection, *, source: str, resource_type: str,
                       resource_id: UUID) -> CoreEvidence | None:
    """Read exactly one scoped entity. Never start, commit or change a transaction.

    Caller must BEGIN with REPEATABLE READ READ ONLY (or serializable read only).
    updated_at is a row revision, NOT source completeness or mandate verification.
    """
    if source not in SOURCES or resource_type not in {"charge", "payment"} or not isinstance(resource_id, UUID):
        raise ValueError("Recurso centralizado invalido")
    if not connection.in_transaction():
        raise ValueError("Se requiere transaccion de lectura explicita")
    if connection.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
        raise ValueError("Se requiere transaccion de solo lectura")
    if connection.execute(text("SHOW transaction_isolation")).scalar_one() not in {"repeatable read", "serializable"}:
        raise ValueError("Se requiere snapshot consistente")
    row = connection.execute(text(_CHARGE if resource_type == "charge" else _PAYMENT),
                             {"resource_id": resource_id, "source": source}).mappings().one_or_none()
    return CoreEvidence(**row) if row is not None else None


@dataclass(frozen=True, slots=True)
class ReviewedStateMapping:
    """Caller-supplied audited vocabulary, never a built-in guess per provider."""

    source: str
    resource_type: str
    review_sha256: str
    states: tuple[tuple[str, State], ...]
    subscription_states: tuple[tuple[str, bool], ...]

    def __post_init__(self):
        token(self.review_sha256)
        if self.source not in SOURCES or self.resource_type not in {"charge", "payment"}:
            raise ValueError("Mapeo de otro ambito")
        for pairs, kind in ((self.states, State), (self.subscription_states, bool)):
            if not isinstance(pairs, tuple) or len(pairs) > 100:
                raise ValueError("Vocabulario invalido")
            keys = set()
            for key, value in pairs:
                if (not isinstance(key, str) or not 0 < len(key) <= 100 or key in keys
                        or not isinstance(value, kind)):
                    raise ValueError("Estado duplicado o invalido")
                keys.add(key)


def map_core_evidence(row: CoreEvidence, mapping: ReviewedStateMapping, *, as_of: datetime,
                      verified_through: datetime | None = None,
                      context: AnnotationContext | None = None,
                      mandate_active: bool | None = None,
                      retry_limit_reached: bool | None = None) -> CoreSnapshot:
    """Missing vocab/coverage stays unknown. Review hash is provenance, not authorization.

    A context must describe this exact code; matching text/evidence provenance still
    requires the caller's audited ML-03 join. No raw glosa is read by this adapter.
    This projection does NOT reconcile all payments/reversals/partial settlements:
    settlement_verified remains False, so it cannot produce collection advice.
    """
    if not isinstance(row, CoreEvidence) or not isinstance(mapping, ReviewedStateMapping):
        raise ValueError("Proyeccion invalida")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Corte sin reloj con zona")
    for clock in (as_of, row.updated_at, row.subscription_updated_at):
        if clock is not None and (not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None):
            raise ValueError("Proyeccion sin reloj con zona")
    if (row.source, row.resource_type) != (mapping.source, mapping.resource_type):
        raise ValueError("Mapeo de otro recurso o canal")
    if row.evidence_id is None or row.rejection_at is None:
        raise ValueError("Evidencia sin identificador o reloj verificable")
    if context is not None and context.code != (row.rejection_code or ""):
        raise ValueError("Contexto no corresponde al codigo centralizado")
    if row.updated_at > as_of or (row.subscription_updated_at is not None and row.subscription_updated_at > as_of):
        raise ValueError("Proyeccion posterior al corte; no reconstruir pasado con Core actual")
    data = asdict(row)
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        elif isinstance(value, UUID):
            data[key] = str(value)
    state_sha = hashlib.sha256(canonical_json(asdict(mapping))).hexdigest()
    return CoreSnapshot(
        source=row.source, resource_type=row.resource_type, resource_id=row.resource_id,
        evidence_id=row.evidence_id, evidence_at=row.rejection_at, as_of=as_of,
        verified_through=verified_through, state=dict(mapping.states).get(row.source_status, State.UNKNOWN),
        state_mapping_sha256=state_sha, data_sha256=hashlib.sha256(canonical_json(data)).hexdigest(),
        context=context, mandate_active=mandate_active, retry_limit_reached=retry_limit_reached,
        subscription_active=dict(mapping.subscription_states).get(row.subscription_status),
        links_verified=row.links_consistent,
    )
