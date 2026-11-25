"""Synthetic-only prospectively registered ledger. Fresh sessions own transactions.

Internal preparation, not an HTTP ingestion/authentication surface. Future adapters
must derive actor from session and enforce study/channel/resource permissions.
"""

import re
from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.ml.batch_contract import digest
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import instant, token
from app.ml.prospective import MAX_EVENTS, event_record, protocol, replay
from app.models.auth import User
from app.models.ml_prospective import MlProspectiveEvent, MlProspectiveStudy


class ProspectiveConflict(ValueError):
    pass


def _gate(enabled, synthetic):
    if type(enabled) is not bool or (enabled and synthetic is not True):
        raise ProspectiveConflict("Solo preparacion sintetica explicita")
    return enabled


def _safe(session, actor_id):
    name = session.scalar(select(func.current_database()))
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,57}_test", name):
        raise ProspectiveConflict("Se requiere base descartable *_test")
    actor = session.get(User, actor_id) if isinstance(actor_id, UUID) else None
    if actor is None or not actor.is_active:
        raise ProspectiveConflict("Se requiere actor activo")


def _now(session, fixture_clock):
    # Fixture clock is reachable only behind explicit synthetic and *_test guards.
    return instant(fixture_clock).isoformat() if fixture_clock is not None else session.scalar(select(func.clock_timestamp())).isoformat()


def _study(session, study_id):
    token(study_id)
    study = session.scalar(select(MlProspectiveStudy).where(MlProspectiveStudy.id == study_id).with_for_update())
    if study is None or study.purpose != "synthetic":
        raise ProspectiveConflict("Estudio sintetico no encontrado")
    return study


def _records(session, study):
    records = session.scalars(select(MlProspectiveEvent.record).where(MlProspectiveEvent.study_id == study.id)
                              .order_by(MlProspectiveEvent.revision).limit(MAX_EVENTS+1)).all()
    if len(records) != study.revision or (records[-1]["event_id"] if records else None) != study.head_event_id:
        raise ProspectiveConflict("Historial incompleto")
    return records


def register_study(factory, config, *, actor_id: UUID, enabled=False, synthetic=False, fixture_clock=None):
    if not _gate(enabled, synthetic):
        return None
    if type(config) is not dict:
        raise ProspectiveConflict("Protocolo invalido")
    with factory() as session, session.begin():
        _safe(session, actor_id)
        token(config.get("study_id"))
        existing = session.get(MlProspectiveStudy, config["study_id"])
        if existing is not None:
            expected = protocol(config, registered_at=existing.registered_at.isoformat())
            if digest(expected) != existing.protocol_sha256 or existing.created_by != actor_id:
                raise ProspectiveConflict("Identidad de estudio reutilizada con otro protocolo/registrante")
            return existing.id
        registered = _now(session, fixture_clock)
        definition = protocol(config, registered_at=registered)
        session.execute(insert(MlProspectiveStudy).values(id=definition["study_id"], source=definition["source"],
            resource_type=definition["resource_type"], purpose="synthetic", protocol=definition, protocol_sha256=digest(definition),
            registered_at=instant(registered), created_by=actor_id, revision=0).on_conflict_do_nothing())
        study = _study(session, definition["study_id"])
        expected = protocol(config, registered_at=study.registered_at.isoformat())
        if digest(expected) != study.protocol_sha256 or study.created_by != actor_id:
            raise ProspectiveConflict("Identidad de estudio reutilizada con otro protocolo/registrante")
        return study.id


def append_event(factory, study_id, *, expected_revision: int, request_id: UUID, actor_id: UUID,
                 case_id: str, kind: str, occurred_at: str, payload: dict,
                 enabled=False, synthetic=False, fixture_clock=None):
    if not _gate(enabled, synthetic):
        return None
    if type(expected_revision) is not int or expected_revision < 0 or not isinstance(request_id, UUID):
        raise ProspectiveConflict("Revision o solicitud invalida")
    token(case_id)
    with factory() as session, session.begin():
        _safe(session, actor_id)
        study = _study(session, study_id)
        previous = session.scalar(select(MlProspectiveEvent).where(MlProspectiveEvent.study_id == study_id,
                                                                   MlProspectiveEvent.request_id == request_id))
        if previous is not None:
            old = previous.record
            if (previous.actor_id != actor_id or old["case_id"] != case_id or old["kind"] != kind
                    or old["occurred_at"] != instant(occurred_at).isoformat()
                    or canonical_json(old["payload"]) != canonical_json(payload)):
                raise ProspectiveConflict("Solicitud reutilizada con otro evento")
            return deepcopy(old)
        if study.revision != expected_revision or study.revision >= MAX_EVENTS:
            raise ProspectiveConflict("Revision cambio o limite de estudio alcanzado")
        recorded = _now(session, fixture_clock)
        record = event_record(study_id=study_id, protocol_sha256=study.protocol_sha256, revision=study.revision+1,
            previous_id=study.head_event_id, request_id=request_id, actor_id=actor_id, kind=kind,
            case_id=case_id, occurred_at=occurred_at, recorded_at=recorded, payload=deepcopy(payload))
        replay(study.protocol, [*_records(session, study), record], as_of=recorded)
        study.revision, study.head_event_id = record["revision"], record["event_id"]
        session.flush()
        session.add(MlProspectiveEvent(id=record["event_id"], study_id=study_id, revision=record["revision"],
            request_id=request_id, actor_id=actor_id, kind=kind, recorded_at=instant(recorded), record=record))
        return deepcopy(record)


def export_study(factory, study_id, *, actor_id: UUID, enabled=False, synthetic=False):
    if not _gate(enabled, synthetic):
        return None
    with factory() as session, session.begin():
        _safe(session, actor_id)
        study = _study(session, study_id)
        records = _records(session, study)
        return deepcopy({"protocol": study.protocol, "events": records})
