"""API de revisión de candidatos de identidad centralizada.

Expone ClientMatchCandidate para revisión manual (ADR-001): confirmar o
rechazar la sugerencia de match sin ejecutar merge automático.

Permisos:
  core.identity.read   — listar candidatos
  core.identity.review — aprobar o rechazar

El merge técnico (reasignar ExternalIdentity.client_id) requiere una operación
separada con permiso core.identity.merge, no implementada en esta versión.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import get_current_user, require_permissions
from app.models.auth import User
from app.models.core import ClientMatchCandidate, ExternalIdentity

router = APIRouter(prefix="/identity", tags=["Identity"])

_VALID_REVIEW_STATUSES = frozenset({"confirmed", "rejected"})


class MatchCandidateSummary(BaseModel):
    id: uuid.UUID
    client_id_a: uuid.UUID
    client_id_b: uuid.UUID
    match_level: str
    match_signals: dict[str, Any]
    status: str
    reviewed_at: datetime | None
    reviewed_by: str | None
    notes: str | None
    identities_a: list[dict[str, Any]]
    identities_b: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    decision: str
    notes: str | None = None


def _identities_for(db: Session, client_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ExternalIdentity.source, ExternalIdentity.resource_type, ExternalIdentity.external_id).where(
            ExternalIdentity.client_id == client_id
        )
    ).all()
    return [{"source": r.source, "resource_type": r.resource_type, "external_id": r.external_id} for r in rows]


def _identities_map(db: Session, client_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Carga identidades externas de todos los client_ids en una sola query."""
    if not client_ids:
        return {}
    rows = db.execute(
        select(
            ExternalIdentity.client_id,
            ExternalIdentity.source,
            ExternalIdentity.resource_type,
            ExternalIdentity.external_id,
        ).where(ExternalIdentity.client_id.in_(client_ids))
    ).all()
    result: dict[uuid.UUID, list[dict[str, Any]]] = {cid: [] for cid in client_ids}
    for r in rows:
        if r.client_id in result:
            result[r.client_id].append({"source": r.source, "resource_type": r.resource_type, "external_id": r.external_id})
    return result


def _to_summary(
    db: Session,
    c: ClientMatchCandidate,
    ident_map: dict[uuid.UUID, list[dict[str, Any]]] | None = None,
) -> MatchCandidateSummary:
    return MatchCandidateSummary(
        id=c.id,
        client_id_a=c.client_id_a,
        client_id_b=c.client_id_b,
        match_level=c.match_level,
        match_signals=c.match_signals,
        status=c.status,
        reviewed_at=c.reviewed_at,
        reviewed_by=c.reviewed_by,
        notes=c.notes,
        identities_a=ident_map[c.client_id_a] if ident_map is not None else _identities_for(db, c.client_id_a),
        identities_b=ident_map[c.client_id_b] if ident_map is not None else _identities_for(db, c.client_id_b),
    )


@router.get(
    "/match-candidates",
    dependencies=[Depends(require_permissions("core.identity.read"))],
    response_model=dict[str, Any],
)
def list_match_candidates(
    status: str | None = None,
    match_level: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Lista candidatos de match de identidad con sus identidades externas."""
    q = select(ClientMatchCandidate)
    if status:
        q = q.where(ClientMatchCandidate.status == status)
    if match_level:
        q = q.where(ClientMatchCandidate.match_level == match_level)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(q.order_by(ClientMatchCandidate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()

    all_ids = {c.client_id_a for c in items} | {c.client_id_b for c in items}
    ident = _identities_map(db, all_ids)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_to_summary(db, c, ident).model_dump() for c in items],
    }


@router.get(
    "/match-candidates/{candidate_id}",
    dependencies=[Depends(require_permissions("core.identity.read"))],
    response_model=MatchCandidateSummary,
)
def get_match_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> MatchCandidateSummary:
    c = db.get(ClientMatchCandidate, candidate_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    return _to_summary(db, c)


@router.post(
    "/match-candidates/{candidate_id}/review",
    dependencies=[Depends(require_permissions("core.identity.review"))],
    response_model=MatchCandidateSummary,
)
def review_match_candidate(
    candidate_id: uuid.UUID,
    body: ReviewRequest,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MatchCandidateSummary:
    """Registra la decisión manual sobre un candidato de match.

    Solo actualiza el estado del candidato; no realiza merge de CoreClients.
    El merge técnico requiere una operación separada con permiso core.identity.merge.
    """
    if body.decision not in _VALID_REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"decision debe ser una de: {sorted(_VALID_REVIEW_STATUSES)}",
        )

    c = db.get(ClientMatchCandidate, candidate_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    if c.status not in ("pending", "confirmed", "rejected"):
        raise HTTPException(status_code=409, detail=f"El candidato tiene estado inesperado: {c.status}")

    c.status = body.decision
    c.reviewed_at = datetime.now(UTC)
    c.reviewed_by = current_user.username
    c.notes = body.notes
    db.commit()
    return _to_summary(db, c)
