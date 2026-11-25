"""ML-11 synthetic API. No inference, uploads, training, batch dispatch or providers."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.routes.billing_changes import _NoEchoRoute
from app.core.config import settings
from app.core.security import get_current_user, get_db, require_csrf
from app.ml.annotation_contract import (
    CONTEXT_COLUMNS,
    AnnotationContext,
    Decision,
    Rationale,
    ReviewRequest,
)
from app.ml.artifacts import VerifiedArtifact, verify_artifact
from app.ml.export_files import load_key
from app.ml.taxonomy import Category, Severity
from app.models.auth import User
from app.models.ml_artifact import MlArtifact, MlArtifactRelease
from app.models.ml_batch import MlBatch, MlBatchItem, MlBatchResult
from app.models.rejection_annotation import (
    RejectionReasonLabel,
    RejectionReasonLabelRevision,
)
from app.services.ml_artifacts import (
    RegistryConflict,
    approve_artifact,
    simulate_release,
)
from app.services.ml_permissions import required_permissions
from app.services.rbac import permission_codes
from app.services.rejection_annotations import (
    AnnotationConflict,
    apply_review_batch,
    latest_review,
)

Source = Literal["virtualpos1", "virtualpos2", "toku", "payku", "tch"]
Resource = Literal["charge", "payment", "transaction", "subscription_state"]
Task = Literal["p1", "p2"]
Hash64 = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")]
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


def error(status, code, message):
    raise HTTPException(status, {"code": code, "message": message})


class MlRoute(_NoEchoRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                response = await original(request)
                if response.status_code == 422:
                    # Even an arbitrary extra field name can contain personal data.
                    response = JSONResponse(status_code=422, content={"detail": {
                        "code": "ml_invalid_request", "message": "Revisa los campos y usa solo los datos solicitados."}})
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise
            except (SQLAlchemyError, ResponseValidationError, ValidationError, KeyError):
                # Dependency cleanup rolls back pending work; never expose SQL/input/path.
                response = JSONResponse(status_code=503, content={"detail": {
                    "code": "ml_storage_unavailable", "message": "No fue posible completar la consulta de ML."}})
            response.headers["Cache-Control"] = "no-store"
            return response
        return handler


def synthetic_api(actor: Actor, db: DB):
    if not settings.ml_rejections_api_enabled:
        error(503, "ml_api_disabled", "La API de ML esta deshabilitada.")
    name = db.scalar(select(func.current_database()))
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,57}_test", name):
        error(503, "ml_synthetic_only", "Esta entrega solo admite pruebas sinteticas aisladas.")


router = APIRouter(route_class=MlRoute, dependencies=[Depends(synthetic_api)], tags=["ML synthetic"])


def authorize(actor, operation, source, resource=None):
    if not required_permissions(operation, source, resource).issubset(permission_codes(actor)):
        error(403, "permission_denied", "No tienes permiso para este recurso de ML.")


class SyntheticBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    synthetic: StrictBool

    @field_validator("synthetic")
    @classmethod
    def synthetic_only(cls, value):
        if value is not True:
            raise ValueError("Se requiere modo sintetico explicito")
        return value


class LabelBody(SyntheticBody):
    request_id: UUID
    processor: str = Field(min_length=1, max_length=40)
    code: str = Field(default="", max_length=32)
    processor_code: str = Field(default="", max_length=3)
    normalized_text: str = Field(default="", max_length=200)
    privacy_reviewed: StrictBool
    category: Category | None = None
    severity: Severity = Severity.UNKNOWN


class RevisionBody(SyntheticBody):
    request_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    decision: Decision
    category: Category | None = None
    severity: Severity = Severity.UNKNOWN
    rationale: Rationale


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    label_id: UUID
    revision: int
    decision: Decision
    category: Category | None
    severity: Severity
    rationale: Rationale
    actor_id: UUID


class LabelOut(BaseModel):
    id: UUID
    source: Source
    resource_type: Resource
    processor: str
    code: str
    processor_code: str
    normalized_text: str
    latest: RevisionOut | None
    history: list[RevisionOut]


def label_in_scope(db, label_id, source, resource):
    label = db.scalar(select(RejectionReasonLabel).where(RejectionReasonLabel.id == label_id,
        RejectionReasonLabel.source == source, RejectionReasonLabel.resource_type == resource))
    if label is None:
        error(404, "ml_not_found", "Registro de ML no encontrado.")
    return label


def save_review(db, actor, request):
    try:
        revision = apply_review_batch(db, actor_id=actor.id, requests=[request])[0]
        response = RevisionOut.model_validate(revision)
        db.commit()
        return response
    except AnnotationConflict:
        db.rollback()
        error(409, "ml_review_conflict", "La revision cambio o requiere una propuesta y otro revisor. Recarga el registro.")


def label_out(label, current, history=()):
    return LabelOut(id=label.id, source=label.source, resource_type=label.resource_type, processor=label.processor,
        code=label.code, processor_code=label.processor_code, normalized_text=label.normalized_text,
        latest=RevisionOut.model_validate(current) if current else None,
        history=[RevisionOut.model_validate(row) for row in history])


@router.get("/{source}/{resource}/labels", response_model=list[LabelOut])
def labels(source: Source, resource: Resource, db: DB, actor: Actor,
           limit: Annotated[int, Query(ge=1, le=100)] = 50,
           offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    authorize(actor, "ml.labels.read", source, resource)
    page = db.scalars(select(RejectionReasonLabel).where(RejectionReasonLabel.source == source,
        RejectionReasonLabel.resource_type == resource).order_by(RejectionReasonLabel.created_at.desc(),
        RejectionReasonLabel.id.desc()).offset(offset).limit(limit)).all()
    if not page:
        return []
    latest = select(RejectionReasonLabelRevision.label_id, func.max(RejectionReasonLabelRevision.revision).label("rev")).where(
        RejectionReasonLabelRevision.label_id.in_([label.id for label in page])).group_by(RejectionReasonLabelRevision.label_id).subquery()
    revisions = db.scalars(select(RejectionReasonLabelRevision).join(latest,
        (latest.c.label_id == RejectionReasonLabelRevision.label_id) & (latest.c.rev == RejectionReasonLabelRevision.revision))).all()
    by_label = {revision.label_id: revision for revision in revisions}
    return [label_out(label, by_label.get(label.id)) for label in page]


@router.get("/{source}/{resource}/labels/{label_id}", response_model=LabelOut)
def get_label(source: Source, resource: Resource, label_id: UUID, db: DB, actor: Actor,
              limit: Annotated[int, Query(ge=1, le=100)] = 50,
              offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    authorize(actor, "ml.labels.read", source, resource)
    label = label_in_scope(db, label_id, source, resource)
    history = db.scalars(select(RejectionReasonLabelRevision).where(RejectionReasonLabelRevision.label_id == label.id)
                        .order_by(RejectionReasonLabelRevision.revision).offset(offset).limit(limit)).all()
    current = latest_review(db, label.id)
    return label_out(label, current, history)


@router.post("/{source}/{resource}/labels", response_model=RevisionOut, dependencies=[Depends(require_csrf)])
def propose_label(source: Source, resource: Resource, body: LabelBody, db: DB, actor: Actor):
    authorize(actor, "ml.labels.propose", source, resource)
    try:
        context = AnnotationContext(source=source, resource_type=resource, processor=body.processor, code=body.code,
            processor_code=body.processor_code, normalized_text=body.normalized_text, privacy_reviewed=body.privacy_reviewed)
        request = ReviewRequest(context, body.request_id, 0, Decision.DRAFT, body.category, body.severity, Rationale.ANNOTATION)
    except ValueError:
        error(422, "ml_invalid_context", "Revisa el contexto, su normalizacion y la revision de privacidad.")
    return save_review(db, actor, request)


@router.post("/{source}/{resource}/labels/{label_id}/revisions", response_model=RevisionOut, dependencies=[Depends(require_csrf)])
def revise_label(source: Source, resource: Resource, label_id: UUID, body: RevisionBody, db: DB, actor: Actor):
    operation = "ml.labels.propose" if body.decision == Decision.DRAFT else "ml.labels.review"
    authorize(actor, operation, source, resource)
    label = label_in_scope(db, label_id, source, resource)
    try:
        context = AnnotationContext(**{key: getattr(label, key) for key in CONTEXT_COLUMNS}, privacy_reviewed=True)
        request = ReviewRequest(context, body.request_id, body.expected_revision, body.decision,
                                body.category, body.severity, body.rationale)
    except ValueError:
        error(422, "ml_invalid_revision", "La decision, categoria o motivo de revision no son compatibles.")
    return save_review(db, actor, request)


class ResultOut(BaseModel):
    id: Hash64
    source: Source
    purpose: Literal["synthetic"]
    category: Category | None
    advice: str
    method: str
    classification_state: str
    rules_state: str
    severity: str
    matched_rules: list[str]
    as_of: str
    reasons: list[str]
    restrictions: list[str]
    engine_version: str
    policy_version: str
    rules_version: str
    taxonomy_version: str
    recovery_probability: None = None
    confidence: None = None
    execution_allowed: Literal[False] = False


def result_query(source, resource):
    return select(MlBatchResult).join(MlBatchItem, MlBatchItem.result_id == MlBatchResult.id).where(
        MlBatchResult.source == source, MlBatchResult.purpose == "synthetic",
        MlBatchItem.source == source, MlBatchItem.resource_type == resource, MlBatchItem.state == "succeeded")


def result_out(row):
    keys = set(ResultOut.model_fields) - {"id", "source", "purpose"}
    return ResultOut(id=row.id, source=row.source, purpose=row.purpose,
                     **{key: row.result[key] for key in keys})


@router.get("/{source}/{resource}/results", response_model=list[ResultOut])
def results(source: Source, resource: Resource, db: DB, actor: Actor,
            limit: Annotated[int, Query(ge=1, le=100)] = 50,
            offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    authorize(actor, "ml.rejections.read", source, resource)
    rows = db.scalars(result_query(source, resource).distinct().order_by(
        MlBatchResult.created_at.desc(), MlBatchResult.id.desc()).offset(offset).limit(limit)).all()
    return [result_out(row) for row in rows]


@router.get("/{source}/{resource}/results/{result_id}", response_model=ResultOut)
def result_detail(source: Source, resource: Resource, result_id: Hash64, db: DB, actor: Actor):
    authorize(actor, "ml.rejections.read", source, resource)
    row = db.scalar(result_query(source, resource).where(MlBatchResult.id == result_id).limit(1))
    if row is None:
        error(404, "ml_not_found", "Registro de ML no encontrado.")
    return result_out(row)


class BatchOut(BaseModel):
    id: Hash64
    source: Source
    resource_type: Resource
    purpose: Literal["synthetic"]
    total: int
    states: dict[str, int]


@router.get("/{source}/{resource}/batches/{batch_id}", response_model=BatchOut)
def batch_detail(source: Source, resource: Resource, batch_id: Hash64, db: DB, actor: Actor):
    authorize(actor, "ml.rejections.read", source, resource)
    items = db.execute(select(MlBatchItem.state, func.count()).join(MlBatch, MlBatch.id == MlBatchItem.batch_id).where(
        MlBatch.id == batch_id, MlBatch.source == source, MlBatch.purpose == "synthetic",
        MlBatchItem.source == source, MlBatchItem.resource_type == resource).group_by(MlBatchItem.state)).all()
    counts = dict(items)
    if not counts:
        error(404, "ml_not_found", "Registro de ML no encontrado.")
    return BatchOut(id=batch_id, source=source, resource_type=resource, purpose="synthetic",
                    total=sum(counts.values()), states=counts)


def artifact_in_scope(db, artifact_id, source, task=None):
    row = db.scalar(select(MlArtifact).where(MlArtifact.id == artifact_id, MlArtifact.source == source))
    if row is None or (task is not None and row.task != task):
        error(404, "ml_not_found", "Registro de ML no encontrado.")
    if row.descriptor.get("purpose") != "synthetic":
        error(409, "ml_real_artifact_disabled", "Los artefactos reales no estan habilitados en esta entrega.")
    return row


def artifact_verifier():
    # No client-provided paths or keys, and no file I/O until scope checks have passed.
    def verify(row):
        root = Path(__file__).resolve().parents[4] / ".local/ml-private"
        return verify_artifact(root, row.manifest_relative, secret=load_key(root, "keys/export.key"))
    return verify


def reverify(row, verifier):
    try:
        verified = verifier(row)
        if (verified.artifact_id != row.id or verified.manifest_sha256 != row.manifest_sha256
                or verified.descriptor["source"] != row.source or verified.descriptor["purpose"] != "synthetic"
                or not verified.compatible):
            raise ValueError("Mismatch")
        return verified
    except (ValueError, OSError, KeyError, ImportError):
        error(409, "ml_artifact_unavailable", "El artefacto no supera la verificacion privada de integridad y compatibilidad.")


class ArtifactOut(BaseModel):
    id: Hash64
    source: Source
    task: Task
    candidate_id: str
    purpose: Literal["synthetic"]
    training_status: str


@router.get("/{source}/artifacts/{artifact_id}", response_model=ArtifactOut)
def artifact_detail(source: Source, artifact_id: Hash64, db: DB, actor: Actor):
    authorize(actor, "ml.artifacts.read", source)
    row = artifact_in_scope(db, artifact_id, source)
    return ArtifactOut(id=row.id, source=source, task=row.task, candidate_id=row.descriptor["candidate_id"],
                       purpose="synthetic", training_status=row.descriptor["training_status"])


class ApprovalBody(SyntheticBody):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    approval_sha256: Hash64


Verifier = Annotated[Callable[[MlArtifact], VerifiedArtifact], Depends(artifact_verifier)]


class ReleaseBody(ApprovalBody):
    action: Literal["promoted", "rolled_back", "disabled"]
    target_id: Hash64 | None = None


class ReleaseOut(BaseModel):
    source: Source
    task: Task
    revision: int
    active_artifact_id: Hash64 | None
    simulation: Literal[True] = True


def release_out(row):
    return ReleaseOut(source=row.source, task=row.task, revision=row.revision, active_artifact_id=row.active_artifact_id)


@router.get("/{source}/releases/{task}", response_model=ReleaseOut)
def release_detail(source: Source, task: Task, db: DB, actor: Actor):
    authorize(actor, "ml.artifacts.read", source)
    release = db.get(MlArtifactRelease, (task, source))
    if release is None:
        return ReleaseOut(source=source, task=task, revision=0, active_artifact_id=None)
    if release.active_artifact_id:
        artifact_in_scope(db, release.active_artifact_id, source, task)
    return release_out(release)


@router.post("/{source}/artifacts/{artifact_id}/approval", response_model=ReleaseOut, dependencies=[Depends(require_csrf)])
def approve(source: Source, artifact_id: Hash64, body: ApprovalBody, db: DB, actor: Actor, verifier: Verifier):
    authorize(actor, "ml.artifacts.review", source)
    row = artifact_in_scope(db, artifact_id, source)
    verified = reverify(row, verifier)
    try:
        release = approve_artifact(db, verified, actor=actor.id, expected_revision=body.expected_revision,
                                   approval_sha256=body.approval_sha256, simulation=True)
        response = release_out(release)
        db.commit()
        return response
    except RegistryConflict:
        db.rollback()
        error(409, "ml_registry_conflict", "Recarga la revision y comprueba la aprobacion independiente.")


@router.post("/{source}/releases/{task}/simulation", response_model=ReleaseOut, dependencies=[Depends(require_csrf)])
def simulate(source: Source, task: Task, body: ReleaseBody, db: DB, actor: Actor, verifier: Verifier):
    authorize(actor, "ml.artifacts.simulate", source)
    if (body.target_id is None) != (body.action == "disabled"):
        error(422, "ml_invalid_target", "Revisa la version elegida y el tipo de simulacion.")
    target_id = body.target_id
    if target_id is None:
        current = db.get(MlArtifactRelease, (task, source))
        target_id = current.active_artifact_id if current else None
    if target_id is not None:
        reverify(artifact_in_scope(db, target_id, source, task), verifier)
    try:
        release = simulate_release(db, task=task, source=source, target_id=body.target_id, actor=actor.id,
            expected_revision=body.expected_revision, approval_sha256=body.approval_sha256, action=body.action, simulation=True)
        response = release_out(release)
        db.commit()
        return response
    except RegistryConflict:
        db.rollback()
        error(409, "ml_registry_conflict", "Recarga la revision y comprueba las versiones aprobadas del canal.")
