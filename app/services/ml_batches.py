"""ML-10 synthetic-only durable runner; no scheduler, ETL hook, models or providers.

Public factory operations own short transactions. Core receipt staging deliberately
does not commit: it belongs in the same transaction as the synthetic Core changes.
All writes require an explicit opt-in and a disposable *_test PostgreSQL database.
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.ml.batch_contract import ItemRef, bundle_sha256, digest, instant, plan_batch
from app.ml.evaluation_protocol import token
from app.ml.recommendation import SOURCES, CoreSnapshot, recommend, snapshot_hash
from app.models.ml_batch import (
    MlBatch,
    MlBatchEvent,
    MlBatchItem,
    MlBatchResult,
    MlCoreReceipt,
)


class BatchBlocked(ValueError):
    pass


def _gate(enabled, synthetic):
    if type(enabled) is not bool:
        raise BatchBlocked("Bandera ML invalida")
    if not enabled:
        return False
    if synthetic is not True:
        raise BatchBlocked("Solo ejecucion sintetica explicita; operacion real deshabilitada")
    return True


def _safe(session):
    name = session.scalar(select(func.current_database()))
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,57}_test", name):
        raise BatchBlocked("ML-10 solo admite una base descartable *_test")


def stage_core_receipt(session, *, receipt_id: UUID, source: str, cutoff: datetime,
                       core_sha256: str, enabled: bool = False, synthetic: bool = False) -> UUID | None:
    """Caller commits Core + receipt together; a rollback must remove both.

    Receipt is an internal assertion of successful Core materialization, not evidence
    of provider coverage. No existing ETL/sync/write status is updated or inferred.
    """
    if not _gate(enabled, synthetic):
        return None
    if not isinstance(receipt_id, UUID) or source not in SOURCES:
        raise BatchBlocked("Confirmacion de Core invalida")
    cutoff = instant(cutoff)
    token(core_sha256)
    _safe(session)
    session.execute(insert(MlCoreReceipt).values(id=receipt_id, source=source, cutoff=cutoff,
                                               core_sha256=core_sha256).on_conflict_do_nothing())
    saved = session.get(MlCoreReceipt, receipt_id, populate_existing=True)
    if (saved.source, saved.cutoff, saved.core_sha256) != (source, cutoff, core_sha256):
        raise BatchBlocked("Confirmacion Core contradictoria")
    return receipt_id


def prepare_batch(factory, *, receipt_id: UUID, snapshots: tuple[CoreSnapshot, ...],
                  max_age_seconds: int = 3600, max_attempts: int = 3,
                  enabled: bool = False, synthetic: bool = False) -> str | None:
    """Fresh transaction observes only COMMITTED receipts; entire manifest is atomic."""
    if not _gate(enabled, synthetic):
        return None
    if not isinstance(receipt_id, UUID):
        raise BatchBlocked("Confirmacion Core invalida")
    with factory() as session, session.begin():
        _safe(session)
        receipt = session.get(MlCoreReceipt, receipt_id)
        if receipt is None:
            raise BatchBlocked("Core no tiene confirmacion comprometida visible")
        plan = plan_batch(receipt_id=receipt_id, source=receipt.source, cutoff=receipt.cutoff,
                          core_sha256=receipt.core_sha256, snapshots=snapshots,
                          max_age_seconds=max_age_seconds, max_attempts=max_attempts)
        # Insert-only idempotence also works when two dispatchers race.
        created = session.execute(insert(MlBatch).values(
            id=plan.id, receipt_id=receipt_id, source=receipt.source, purpose="synthetic", cutoff=receipt.cutoff,
            bundle_sha256=plan.bundle_sha256, total=len(plan.items), max_age_seconds=max_age_seconds,
            max_attempts=max_attempts, state="queued" if plan.items else "completed",
            finished_at=None if plan.items else func.clock_timestamp()).on_conflict_do_nothing().returning(MlBatch.id)).scalar_one_or_none()
        if created:
            session.add_all(MlBatchItem(batch_id=plan.id, ordinal=item.ordinal, source=item.source,
                resource_type=item.resource_type, resource_id=item.resource_id, evidence_id=item.evidence_id,
                input_sha256=item.input_sha256, state="queued", attempts=0) for item in plan.items)
        return plan.id


@dataclass(frozen=True, slots=True)
class Claim:
    batch_id: str
    item: ItemRef
    lease_token: UUID
    attempt: int
    max_age_seconds: int


def _batch(session, batch_id):
    token(batch_id)
    batch = session.scalar(select(MlBatch).where(MlBatch.id == batch_id).with_for_update())
    if batch is None or batch.purpose != "synthetic" or batch.bundle_sha256 != bundle_sha256():
        raise BatchBlocked("Lote ausente o bundle incompatible; no reanudar con otra version")
    return batch


def _event(session, item, action, *, code=None):
    session.add(MlBatchEvent(batch_id=item.batch_id, ordinal=item.ordinal, attempt=item.attempts,
                            lease_token=item.lease_token, action=action, error_code=code))


def _settle(session, batch):
    session.flush()
    states = dict(session.execute(select(MlBatchItem.state, func.count()).where(
        MlBatchItem.batch_id == batch.id).group_by(MlBatchItem.state)).all())
    if not states.get("queued") and not states.get("running"):
        batch.state = "completed_with_errors" if states.get("failed") else "completed"
        batch.finished_at = session.scalar(select(func.clock_timestamp()))


def claim_next(factory, batch_id: str, *, lease_seconds: int = 60,
               enabled: bool = False, synthetic: bool = False) -> Claim | None:
    if not _gate(enabled, synthetic):
        return None
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
        raise BatchBlocked("Lease ML invalido")
    with factory() as session, session.begin():
        _safe(session)
        batch = _batch(session, batch_id)
        if batch.state in {"completed", "completed_with_errors"}:
            return None
        now = session.scalar(select(func.clock_timestamp()))
        # Short batch lock serializes claims/finalization across processes, never computation.
        for _ in range(batch.total + 1):
            item = session.scalar(select(MlBatchItem).where(MlBatchItem.batch_id == batch_id, or_(
                and_(MlBatchItem.state == "queued", or_(MlBatchItem.retry_at.is_(None), MlBatchItem.retry_at <= now)),
                and_(MlBatchItem.state == "running", MlBatchItem.lease_until <= now))).order_by(MlBatchItem.ordinal).limit(1).with_for_update())
            if item is None:
                _settle(session, batch)
                return None
            if item.attempts >= batch.max_attempts:
                _event(session, item, "lease_exhausted", code="lease_expired")
                item.state, item.lease_token, item.lease_until = "failed", None, None
                session.flush()
                continue
            if item.state == "running":
                _event(session, item, "retry", code="lease_expired")
            item.attempts += 1
            item.state, item.lease_token, item.lease_until = "running", uuid4(), now + timedelta(seconds=lease_seconds)
            item.retry_at = None
            batch.state = "running"
            _event(session, item, "claimed")
            return Claim(batch_id, ItemRef(item.ordinal, item.source, item.resource_type,
                         item.resource_id, item.evidence_id, item.input_sha256), item.lease_token,
                         item.attempts, batch.max_age_seconds)
    return None


def _owned(batch, item, claim, now):
    if (item is None or item.state != "running" or item.lease_token != claim.lease_token
            or item.attempts != claim.attempt or item.lease_until <= now):
        return False
    expected = ItemRef(item.ordinal, item.source, item.resource_type, item.resource_id,
                       item.evidence_id, item.input_sha256)
    if claim.item != expected or claim.max_age_seconds != batch.max_age_seconds:
        raise BatchBlocked("Claim no corresponde al manifiesto")
    return True


def _complete(factory, claim, *, result=None, error_code=None, retry_seconds=30):
    with factory() as session, session.begin():
        _safe(session)
        batch = _batch(session, claim.batch_id)
        item = session.get(MlBatchItem, (claim.batch_id, claim.item.ordinal), with_for_update=True)
        now = session.scalar(select(func.clock_timestamp()))
        if not _owned(batch, item, claim, now):
            return "stale_claim"  # Fenced: no result/event can be written by a previous owner.
        if result is not None:
            # Result is computed internally below, never accepted from HTTP or arbitrary model output.
            value = asdict(result)
            if result.input_sha256 != item.input_sha256 or result.source != item.source:
                raise BatchBlocked("Resultado de otro snapshot")
            sha = digest(value)
            session.execute(insert(MlBatchResult).values(id=result.logical_id, source=item.source, purpose="synthetic",
                input_sha256=item.input_sha256, result_sha256=sha, result=value).on_conflict_do_nothing())
            saved = session.get(MlBatchResult, result.logical_id)
            if saved.result_sha256 != sha or saved.input_sha256 != item.input_sha256 or saved.source != item.source:
                raise BatchBlocked("Resultado existente contradictorio")
            item.result_id, item.state = result.logical_id, "succeeded"
            _event(session, item, "succeeded")
            outcome = "succeeded"
        else:
            terminal = error_code == "snapshot_changed" or item.attempts >= batch.max_attempts
            item.state = "failed" if terminal else "queued"
            item.retry_at = None if terminal else now + timedelta(seconds=retry_seconds)
            _event(session, item, "failed" if terminal else "retry", code=error_code)
            outcome = "failed" if terminal else "retry"
        item.lease_token, item.lease_until = None, None
        _settle(session, batch)
        return outcome


def process_claim(factory, claim: Claim, resolver, *, enabled: bool = False, synthetic: bool = False) -> str:
    """Resolver reconstructs the EXACT synthetic snapshot from its private fixture.

    There is no durable raw snapshot here. A changed Core snapshot requires a NEW
    batch; this worker must not reconstruct historical truth from mutable current rows.
    Exceptions become bounded codes, never their text/SQL/PII or a provider response.
    """
    if not _gate(enabled, synthetic):
        return "disabled"
    if not isinstance(claim, Claim):
        raise BatchBlocked("Claim ML invalido")
    with factory() as session, session.begin():
        _safe(session)
        batch = _batch(session, claim.batch_id)
        item = session.get(MlBatchItem, (claim.batch_id, claim.item.ordinal))
        if not _owned(batch, item, claim, session.scalar(select(func.clock_timestamp()))):
            return "stale_claim"
    code, result = None, None
    try:
        snapshot = resolver(claim.item)
        if not isinstance(snapshot, CoreSnapshot):
            code = "invalid_snapshot"
        elif (snapshot_hash(snapshot) != claim.item.input_sha256 or snapshot.source != claim.item.source
              or snapshot.resource_type != claim.item.resource_type or snapshot.resource_id != claim.item.resource_id
              or snapshot.evidence_id != claim.item.evidence_id):
            code = "snapshot_changed"
        else:
            result = recommend(snapshot, max_age_seconds=claim.max_age_seconds)
    except (ValueError, TypeError, RuntimeError, ArithmeticError, LookupError, OSError):
        code = "calculation_failed"
    return _complete(factory, claim, result=result, error_code=code)


def process_next(factory, batch_id: str, resolver, *, synthetic: bool = False) -> str:
    """Bounded worker entry point honoring the OFF-by-default runtime flag.

    Not scheduled or exposed over HTTP. Low-level opt-ins above exist for the
    isolated synthetic harness, never as permission to activate operational ML.
    """
    from app.core.config import settings

    if not settings.ml_rejections_batches_enabled:
        return "disabled"
    claim = claim_next(factory, batch_id, enabled=True, synthetic=synthetic)
    if claim is None:
        return "idle"  # Includes waiting retries/leases; does not mean batch completed.
    return process_claim(factory, claim, resolver, enabled=True, synthetic=synthetic)
