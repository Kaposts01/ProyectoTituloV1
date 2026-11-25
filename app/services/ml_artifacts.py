"""Internal registry operations. Caller owns transactions; no runtime activation or model load.

Real promotion is deliberately disabled in ML-08. Synthetic transitions exercise the future
transactional release/rollback mechanism only in an explicitly selected simulation.
"""

import hashlib
from copy import deepcopy
from functools import wraps
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ml.artifacts import VerifiedArtifact
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import token
from app.ml.pipelines import environment
from app.models.auth import User
from app.models.ml_artifact import MlArtifact, MlArtifactEvent, MlArtifactRelease


class RegistryConflict(ValueError):
    pass


def _verified_descriptor(artifact: VerifiedArtifact) -> dict:
    descriptor = deepcopy(artifact.descriptor)
    record_id = descriptor.pop("artifact_id", None)
    if record_id != artifact.artifact_id or hashlib.sha256(canonical_json(descriptor)).hexdigest() != record_id:
        raise RegistryConflict("Descriptor modificado despues de verificacion")
    token(artifact.manifest_sha256)
    descriptor["artifact_id"] = record_id
    return descriptor


def _atomic(operation):
    @wraps(operation)
    def guarded(session, *args, **kwargs):
        if session.new or session.dirty or session.deleted:
            raise RegistryConflict("Guarde o revierta cambios pendientes antes de modificar el registro")
        try:
            with session.begin_nested():
                return operation(session, *args, **kwargs)
        except IntegrityError:
            raise RegistryConflict("Conflicto de integridad en registro; recargue la revision") from None
    return guarded


def _actor(session: Session, actor: UUID) -> None:
    user = session.get(User, actor)
    if user is None or not user.is_active:
        raise RegistryConflict("Se requiere un operador activo")


def _scope(session: Session, task: str, source: str, revision: int, *, check_revision: bool = True) -> MlArtifactRelease:
    if type(revision) is not int or revision < 0:
        raise RegistryConflict("Revision invalida")
    session.execute(insert(MlArtifactRelease).values(task=task, source=source, revision=0).on_conflict_do_nothing())
    release = session.scalar(select(MlArtifactRelease).filter_by(task=task, source=source).with_for_update().execution_options(populate_existing=True))
    if check_revision and release.revision != revision:
        raise RegistryConflict("El registro cambio; recargue la revision")
    return release


def _event(session: Session, release: MlArtifactRelease, *, action: str, artifact_id: str | None,
           actor: UUID, approval: str | None = None) -> None:
    release.revision += 1
    session.flush()
    session.add(MlArtifactEvent(task=release.task, source=release.source, revision=release.revision, action=action,
                               artifact_id=artifact_id, active_after_id=release.active_artifact_id,
                               actor_id=actor, approval_sha256=approval))
    session.flush()


@_atomic
def register_artifact(session: Session, artifact: VerifiedArtifact, *, actor: UUID, expected_revision: int) -> MlArtifact:
    """Persist immutable verified metadata; file storage is a prior independent operation."""
    _actor(session, actor)
    descriptor = _verified_descriptor(artifact)
    existing = session.get(MlArtifact, artifact.artifact_id)
    if existing is not None:
        if existing.manifest_sha256 != artifact.manifest_sha256:
            raise RegistryConflict("Misma identidad con otro manifiesto")
        return existing
    release = _scope(session, descriptor["task"], descriptor["source"], expected_revision, check_revision=False)
    # Recheck after the scope lock for concurrent idempotent registration.
    existing = session.get(MlArtifact, artifact.artifact_id)
    if existing is not None:
        return existing
    if release.revision != expected_revision:
        raise RegistryConflict("El registro cambio; recargue la revision")
    stored = MlArtifact(id=artifact.artifact_id, task=descriptor["task"], source=descriptor["source"],
                        manifest_relative=artifact.manifest_relative, manifest_sha256=artifact.manifest_sha256,
                        descriptor=descriptor, created_by=actor)
    session.add(stored)
    session.flush()
    _event(session, release, action="registered", artifact_id=stored.id, actor=actor)
    return stored


@_atomic
def approve_artifact(session: Session, artifact: VerifiedArtifact, *, actor: UUID, expected_revision: int,
                     approval_sha256: str, simulation: bool = False) -> MlArtifactRelease:
    """Reverify file/evidence before calling. Approval is independent of registration."""
    _actor(session, actor)
    token(approval_sha256)
    descriptor = _verified_descriptor(artifact)
    stored = session.get(MlArtifact, artifact.artifact_id)
    if stored is None or stored.manifest_sha256 != artifact.manifest_sha256 or stored.created_by == actor:
        raise RegistryConflict("Artefacto no registrado o falta segundo revisor")
    synthetic = stored.descriptor["purpose"] == "synthetic"
    if (not artifact.compatible or descriptor["environment"] != environment() or (synthetic and simulation is not True)
            or (not synthetic and not artifact.evaluation_verified)):
        raise RegistryConflict("Falta compatibilidad, evaluacion verificada o simulacion explicita")
    release = _scope(session, stored.task, stored.source, expected_revision)
    _event(session, release, action="approved", artifact_id=stored.id, actor=actor, approval=approval_sha256)
    return release


@_atomic
def simulate_release(session: Session, *, task: str, source: str, target_id: str | None,
                     actor: UUID, expected_revision: int, approval_sha256: str, action: str,
                     simulation: bool = False) -> MlArtifactRelease:
    """No consumer in CRM; synthetic metadata only. Real activation needs ML-09/11 approval."""
    _actor(session, actor)
    token(approval_sha256)
    if simulation is not True or action not in {"promoted", "rolled_back", "disabled"} or (target_id is None) != (action == "disabled"):
        raise RegistryConflict("Solo simulacion explicita; activacion real deshabilitada")
    release = _scope(session, task, source, expected_revision)
    if target_id is not None:
        target = session.get(MlArtifact, target_id)
        approved = session.scalar(select(MlArtifactEvent.id).filter_by(task=task, source=source, artifact_id=target_id, action="approved").limit(1))
        if (target is None or (target.task, target.source) != (task, source)
                or target.descriptor["purpose"] != "synthetic" or approved is None):
            raise RegistryConflict("Version no aprobada, real o de otro tipo/canal")
        if action == "rolled_back" and not session.scalar(select(MlArtifactEvent.id).filter_by(task=task, source=source, active_after_id=target_id, action="promoted").limit(1)):
            raise RegistryConflict("Rollback requiere una version publicada previamente en la simulacion")
    elif release.active_artifact_id is not None:
        active = session.get(MlArtifact, release.active_artifact_id)
        if active.descriptor["purpose"] != "synthetic":
            raise RegistryConflict("No deshabilitar registros reales desde simulacion")
    release.active_artifact_id = target_id
    _event(session, release, action=action, artifact_id=target_id, actor=actor, approval=approval_sha256)
    return release
