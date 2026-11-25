"""Native PostgreSQL evidence and concurrency, only guarded disposable synthetic DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_ml_prospective import (
    END,
    START,
    checks,
    config,
    enrollment,
    exposure,
    outcome,
)

from app.db.session import Base, engine
from app.ml.batch_contract import digest
from app.ml.prospective import measure
from app.models.auth import User
from app.models.ml_prospective import MlProspectiveEvent, MlProspectiveStudy
from app.services.ml_prospective import (
    ProspectiveConflict,
    append_event,
    export_study,
    register_study,
)

FLAGS = dict(enabled=True, synthetic=True)


def factory():
    return Session(engine)


@pytest.fixture
def study():
    actor = uuid4()
    with factory() as db, db.begin():
        db.add(User(id=actor, username=f"ml14-synthetic-{actor}", password_hash="not-a-login", is_active=True))
    settings = config(study_id=digest(str(uuid4())))
    identifier = register_study(factory, settings, actor_id=actor, fixture_clock=START.isoformat(), **FLAGS)
    return identifier, actor, settings


def append(study, *, revision=0, kind="enrolled", at=None, payload=None, request=None, case=1):
    identifier, actor, _ = study
    at = at or START+timedelta(days=1)
    return append_event(factory, identifier, expected_revision=revision, request_id=request or uuid4(), actor_id=actor,
        case_id=f"{case:064x}", kind=kind, occurred_at=at.isoformat(), payload=payload or enrollment(at, case),
        fixture_clock=at.isoformat(), **FLAGS)


def exported(study):
    return export_study(factory, study[0], actor_id=study[1], **FLAGS)


def test_default_off_never_opens_connection():
    def unavailable():
        raise AssertionError("DB should not open")
    assert register_study(unavailable, {}, actor_id=None) is None
    assert export_study(unavailable, "", actor_id=None) is None
    assert append_event(unavailable, "", expected_revision=0, request_id=None, actor_id=None,
        case_id="", kind="", occurred_at="", payload={}) is None
    with pytest.raises(ProspectiveConflict):
        register_study(unavailable, {}, actor_id=None, enabled=True)


def test_registration_idempotency_and_immutable_identity(study):
    identifier, actor, settings = study
    assert register_study(factory, settings, actor_id=actor, fixture_clock=START.isoformat(), **FLAGS) == identifier
    assert register_study(factory, settings, actor_id=actor, fixture_clock=END.isoformat(), **FLAGS) == identifier
    with pytest.raises(ProspectiveConflict):
        register_study(factory, settings | {"minimum_units": 3}, actor_id=actor, fixture_clock=START.isoformat(), **FLAGS)
    assert exported(study)["events"] == []


def test_active_actor_and_test_database_required(study, monkeypatch):
    with factory() as db, db.begin():
        db.get(User, study[1]).is_active = False
    with pytest.raises(ProspectiveConflict, match="activo"):
        append(study)
    from app.services import ml_prospective
    class WrongDatabase:
        def scalar(self, statement):
            return "crm"
    with pytest.raises(ProspectiveConflict, match="descartable"):
        ml_prospective._safe(WrongDatabase(), study[1])


def test_idempotent_request_conflict_and_stale_revision(study):
    request = uuid4()
    first = append(study, request=request)
    assert append(study, request=request) == first
    with pytest.raises(ProspectiveConflict, match="otro evento"):
        append(study, request=request, case=2)
    with pytest.raises(ProspectiveConflict, match="Revision"):
        append(study, case=2)
    assert len(exported(study)["events"]) == 1


def test_export_roundtrip_preserves_unexposed_denominator_and_corrections(study):
    first, second = START+timedelta(days=1), START+timedelta(days=2)
    append(study, at=first)
    shown = append(study, revision=1, kind="exposed", at=first+timedelta(hours=1), payload=exposure(first))
    at = first+timedelta(hours=2)
    append(study, revision=2, kind="decision", at=at, payload=checks(at) | dict(
        choice="defer", exposure_event_id=shown["event_id"], supersedes=None))
    append(study, revision=3, at=second, case=2)
    old = append(study, revision=4, kind="outcome", at=first+timedelta(days=31), payload=outcome(first))
    append(study, revision=5, kind="outcome", at=second+timedelta(days=31), case=2, payload=outcome(second, paid=False))
    data = exported(study)
    result = measure(data["protocol"], data["events"], as_of=END.isoformat())
    assert result["counts"]["eligible"] == 2 and result["observed_recovery_rate"] == .5
    append(study, revision=6, kind="outcome", at=END+timedelta(days=1), payload=old["payload"] | {
        "status": "reversed", "supersedes": old["event_id"]})
    data = exported(study)
    assert measure(data["protocol"], data["events"], as_of=END.isoformat())["observed_recovery_rate"] == .5


def test_failed_event_insert_rolls_back_head_atomically(study):
    def fail(*args):
        raise RuntimeError("synthetic fault")
    event.listen(MlProspectiveEvent, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic fault"):
            append(study)
    finally:
        event.remove(MlProspectiveEvent, "before_insert", fail)
    with factory() as db:
        row = db.get(MlProspectiveStudy, study[0])
        assert row.revision == 0 and row.head_event_id is None
    assert append(study)["revision"] == 1


@pytest.mark.parametrize("sql", [
    "UPDATE ml_prospective_events SET kind='outcome' WHERE study_id=:id",
    "DELETE FROM ml_prospective_events WHERE study_id=:id",
    "UPDATE ml_prospective_studies SET source='toku' WHERE id=:id",
    "DELETE FROM ml_prospective_studies WHERE id=:id",
    "UPDATE ml_prospective_studies SET revision=2, head_event_id=repeat('a',64) WHERE id=:id",
])
def test_native_immutability_and_incomplete_head_rejected(study, sql):
    append(study)
    with pytest.raises(IntegrityError):
        with factory() as db, db.begin():
            db.execute(text(sql), {"id": study[0]})
    assert len(exported(study)["events"]) == 1


def test_concurrent_writers_have_one_winner_and_no_missing_revision(study):
    def attempt(case):
        try:
            return append(study, case=case)["revision"]
        except ProspectiveConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(map(str, results)) == ["1", "conflict"]
    assert len(exported(study)["events"]) == 1


def test_concurrent_same_request_is_exactly_one_persisted_event(study):
    request = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: append(study, request=request), [1, 2]))
    assert results[0] == results[1]
    assert len(exported(study)["events"]) == 1


def test_invalid_event_does_not_advance_ledger(study):
    at = START-timedelta(days=1)
    with pytest.raises(ValueError):
        append(study, at=at)
    append(study)
    at = START+timedelta(days=2)
    with pytest.raises(ValueError):
        append(study, revision=1, kind="decision", at=at, payload=checks(at, state="paid") | dict(
            choice="refer_existing_workflow", exposure_event_id=None, supersedes=None))
    assert len(exported(study)["events"]) == 1


def test_schema_matches_metadata_and_downgrade_refuses_history(study):
    metadata = MetaData()
    for name in ("users", "ml_prospective_studies", "ml_prospective_events"):
        Base.metadata.tables[name].to_metadata(metadata)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"include_object": lambda obj, name, kind, reflected, other:
            kind != "table" or name in metadata.tables})
        assert compare_metadata(context, metadata) == []
        path = Path("alembic/versions/20261125_0087_ml_prospective_ledger.py")
        spec = spec_from_file_location("ml14_migration", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(context), pytest.raises(RuntimeError, match="Downgrade blocked"):
            module.downgrade()
    with factory() as db:
        assert db.scalar(select(MlProspectiveStudy.id).where(MlProspectiveStudy.id == study[0])) == study[0]
