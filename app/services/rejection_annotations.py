"""ML-03 persistence. Caller owns commit and authenticated/authorized actor selection.

No HTTP or CLI entrypoint is enabled here. ML-11 must enforce session-bound permissions.
"""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ml.annotation_contract import CONTEXT_COLUMNS, Decision, ReviewRequest
from app.models.auth import User
from app.models.rejection_annotation import (
    RejectionReasonLabel,
    RejectionReasonLabelRevision,
)


class AnnotationConflict(ValueError):
    """Safe domain conflict; contains no source evidence or SQL parameters."""


def _apply(session: Session, actor_id: UUID, request: ReviewRequest) -> RejectionReasonLabelRevision:
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_active:
        raise AnnotationConflict("Se requiere un anotador activo")
    context = {key: getattr(request.context, key) for key in CONTEXT_COLUMNS}
    session.execute(insert(RejectionReasonLabel).values(
        id=uuid4(), **context, privacy_reviewed_by=actor_id,
    ).on_conflict_do_nothing(constraint="uq_rejection_label_context"))
    label = session.scalar(select(RejectionReasonLabel).filter_by(**context).with_for_update())
    previous = session.get(RejectionReasonLabelRevision, request.request_id)
    payload = dict(decision=request.decision.value, category=request.category.value if request.category else None,
                   severity=request.severity.value, rationale=request.rationale.value)
    if previous:
        if (previous.label_id != label.id or previous.actor_id != actor_id
                or previous.revision != request.expected_revision + 1
                or any(getattr(previous, key) != value for key, value in payload.items())):
            raise AnnotationConflict("Identificador de solicitud reutilizado con otra decision")
        return previous
    latest = session.scalar(select(RejectionReasonLabelRevision).where(
        RejectionReasonLabelRevision.label_id == label.id,
    ).order_by(RejectionReasonLabelRevision.revision.desc()).limit(1))
    if request.expected_revision != (latest.revision if latest else 0):
        raise AnnotationConflict("La glosa cambio; recargue su revision antes de continuar")
    if latest is None and request.decision != Decision.DRAFT:
        raise AnnotationConflict("La primera revision debe ser una propuesta")
    if request.decision in {Decision.APPROVED, Decision.REJECTED, Decision.ABSTAINED}:
        if latest is None or latest.decision != Decision.DRAFT or latest.actor_id == actor_id:
            raise AnnotationConflict("Se requiere una propuesta y un segundo revisor")
    if request.decision == Decision.APPROVED:
        if request.context.processor == "unresolved":
            raise AnnotationConflict("Resuelva el alcance del procesador antes de aprobar")
        if (latest.category, latest.severity) != (payload["category"], payload["severity"]):
            raise AnnotationConflict("Corrija la propuesta antes de aprobar una etiqueta diferente")
    if request.decision == Decision.WITHDRAWN and (latest is None or latest.decision not in {Decision.DRAFT, Decision.APPROVED}):
        raise AnnotationConflict("Solo puede retirar una propuesta o aprobacion vigente")
    revision = RejectionReasonLabelRevision(
        id=request.request_id, label_id=label.id, revision=request.expected_revision + 1,
        actor_id=actor_id, **payload,
    )
    session.add(revision)
    session.flush()
    return revision


def apply_review_batch(session: Session, *, actor_id: UUID,
                       requests: list[ReviewRequest]) -> list[RejectionReasonLabelRevision]:
    """Atomic batch; no commit. Requires a clean session to avoid savepoint autoflush surprises.

    CSV does not supply actor identity. A replay returns the original event even if later
    reviews exist. Sort contexts consistently in callers if concurrent multi-row imports
    overlap; PostgreSQL deadlocks must roll back and be retried by the authorized caller.
    """
    if session.new or session.dirty or session.deleted:
        raise AnnotationConflict("Guarde o revierta otros cambios antes de importar revisiones")
    if not isinstance(actor_id, UUID) or len(requests) > 1000 or any(not isinstance(r, ReviewRequest) for r in requests):
        raise AnnotationConflict("Lote invalido")
    try:
        with session.begin_nested():
            return [_apply(session, actor_id, request) for request in requests]
    except IntegrityError:
        raise AnnotationConflict("Conflicto de integridad; revise las solicitudes y recargue sus revisiones") from None


def latest_review(session: Session, label_id: UUID) -> RejectionReasonLabelRevision | None:
    """Read current state; never resurrect a historical approval after correction/withdrawal."""
    return session.scalar(select(RejectionReasonLabelRevision).where(
        RejectionReasonLabelRevision.label_id == label_id,
    ).order_by(RejectionReasonLabelRevision.revision.desc()).limit(1))
