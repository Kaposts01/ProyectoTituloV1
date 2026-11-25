"""PostgreSQL integration: synthetic users/evidence in a guarded disposable database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from itertools import count
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base, engine
from app.ml.annotation_contract import (
    Decision,
    Rationale,
    ReviewRequest,
    prepare_context,
    read_requests_csv,
    write_requests_csv,
)
from app.ml.taxonomy import Category, Severity
from app.models.auth import User
from app.models.rejection_annotation import (
    RejectionReasonLabel,
    RejectionReasonLabelRevision,
)
from app.services.rejection_annotations import (
    AnnotationConflict,
    apply_review_batch,
    latest_review,
)

_CODES = count(10000)


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def actors(db):
    ids = (uuid4(), uuid4())
    db.add_all([User(id=key, username=f"ml-synthetic-{key}", password_hash="not-a-login", is_active=True) for key in ids])
    db.flush()
    return ids


def request(**overrides):
    values = dict(
        context=prepare_context(source="tch", resource_type="charge", processor="bank-12",
                                reason="Sin fondos", code=str(next(_CODES)), privacy_reviewed=True),
        request_id=uuid4(), expected_revision=0, decision=Decision.DRAFT,
        category=Category.FUNDS, severity=Severity.TEMPORARY, rationale=Rationale.ANNOTATION,
    )
    return ReviewRequest(**(values | overrides))


def apply(db, actor, req):
    return apply_review_batch(db, actor_id=actor, requests=[req])[0]


def approved(req):
    return replace(req, request_id=uuid4(), expected_revision=1,
                   decision=Decision.APPROVED, rationale=Rationale.REVIEW)


def test_independent_review_correction_withdrawal_and_replay(db, actors):
    proposal = request()
    draft = apply(db, actors[0], proposal)
    approval = approved(proposal)
    with pytest.raises(AnnotationConflict, match="segundo"):
        apply(db, actors[0], approval)
    with pytest.raises(AnnotationConflict, match="Corrija"):
        apply(db, actors[1], replace(approval, category=Category.TECH))
    result = apply(db, actors[1], approval)
    assert result.revision == 2 and result.category == "FUNDS"
    correction = replace(proposal, request_id=uuid4(), expected_revision=2,
                         category=Category.TECH, rationale=Rationale.CORRECTION)
    apply(db, actors[0], correction)
    assert latest_review(db, draft.label_id).decision == "draft"
    # Old-file replay neither reinstates approval nor adds a revision.
    assert apply(db, actors[1], approval).id == result.id
    assert latest_review(db, draft.label_id).revision == 3
    withdrawal = replace(correction, request_id=uuid4(), expected_revision=3, decision=Decision.WITHDRAWN,
                         category=None, severity=Severity.UNKNOWN, rationale=Rationale.WITHDRAWAL)
    apply(db, actors[0], withdrawal)
    assert latest_review(db, draft.label_id).decision == "withdrawn"
    assert db.scalar(select(func.count()).select_from(RejectionReasonLabelRevision).where(
        RejectionReasonLabelRevision.label_id == draft.label_id)) == 4


@pytest.mark.parametrize("decision,rationale", [(Decision.ABSTAINED, Rationale.INSUFFICIENT), (Decision.REJECTED, Rationale.CONFLICT)])
def test_review_can_abstain_or_reject_without_forcing_category(db, actors, decision, rationale):
    proposal = request(category=None, severity=Severity.UNKNOWN)
    draft = apply(db, actors[0], proposal)
    result = apply(db, actors[1], replace(proposal, request_id=uuid4(), expected_revision=1,
                                        decision=decision, rationale=rationale))
    assert result.category is None and latest_review(db, draft.label_id).decision == decision.value


def test_context_deduplication_and_source_isolation(db, actors):
    proposal = request()
    first = apply(db, actors[0], proposal)
    corrected = replace(proposal, request_id=uuid4(), expected_revision=1, rationale=Rationale.CORRECTION)
    assert apply(db, actors[1], corrected).label_id == first.label_id
    other = replace(proposal, request_id=uuid4(), context=replace(proposal.context, processor="bank-13"))
    assert apply(db, actors[0], other).label_id != first.label_id
    with pytest.raises(AnnotationConflict, match="cambio"):
        apply(db, actors[0], replace(proposal, request_id=uuid4()))
    with pytest.raises(AnnotationConflict, match="reutilizado"):
        apply(db, actors[0], replace(proposal, category=Category.TECH))


def test_batch_rolls_back_all_rows_and_does_not_commit_caller_work(db, actors):
    first, second = request(), request(expected_revision=5)
    with pytest.raises(AnnotationConflict):
        apply_review_batch(db, actor_id=actors[0], requests=[first, second])
    assert db.get(RejectionReasonLabelRevision, first.request_id) is None
    assert db.scalar(select(RejectionReasonLabel).where(RejectionReasonLabel.code == first.context.code)) is None
    assert db.get(User, actors[0]) is not None
    apply(db, actors[0], first)
    db.rollback()
    assert db.get(RejectionReasonLabelRevision, first.request_id) is None
    assert db.get(User, actors[0]) is None


def test_csv_proposal_and_independent_review_are_replayable(db, actors):
    proposal = request()
    commands = read_requests_csv(write_requests_csv([proposal]))
    first = apply_review_batch(db, actor_id=actors[0], requests=commands)[0]
    approval = approved(proposal)
    reviewed = read_requests_csv(write_requests_csv([approval]))
    result = apply_review_batch(db, actor_id=actors[1], requests=reviewed)[0]
    assert apply_review_batch(db, actor_id=actors[0], requests=commands)[0].id == first.id
    assert apply_review_batch(db, actor_id=actors[1], requests=reviewed)[0].id == result.id
    assert latest_review(db, first.label_id).revision == 2


def test_actor_and_initial_or_unresolved_approval_guards(db, actors):
    proposal = request(context=replace(request().context, processor="unresolved"))
    with pytest.raises(AnnotationConflict):
        apply(db, uuid4(), proposal)
    with pytest.raises(AnnotationConflict, match="primera"):
        apply(db, actors[0], replace(approved(proposal), expected_revision=0))
    apply(db, actors[0], proposal)
    with pytest.raises(AnnotationConflict, match="alcance"):
        apply(db, actors[1], approved(proposal))
    db.get(User, actors[1]).is_active = False
    with pytest.raises(AnnotationConflict, match="otros cambios"):
        apply(db, actors[1], approved(proposal))
    db.flush()
    with pytest.raises(AnnotationConflict, match="activo"):
        apply(db, actors[1], approved(proposal))


@pytest.mark.parametrize("table,operation", [
    ("rejection_reason_labels", "UPDATE rejection_reason_labels SET processor = 'other' WHERE id = :id"),
    ("rejection_reason_label_revisions", "DELETE FROM rejection_reason_label_revisions WHERE id = :id"),
])
def test_database_history_cannot_be_rewritten(db, actors, table, operation):
    revision = apply(db, actors[0], request())
    key = revision.label_id if table == "rejection_reason_labels" else revision.id
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(operation), {"id": key})
    assert db.get(RejectionReasonLabelRevision, revision.id) is not None


def test_database_rejects_revision_gaps_and_self_approval(db, actors):
    revision = apply(db, actors[0], request())
    for number, actor in [(3, actors[1]), (2, actors[0])]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(RejectionReasonLabelRevision(id=uuid4(), label_id=revision.label_id, revision=number,
                   decision="approved", category="FUNDS", severity="temporary", rationale="independent_review", actor_id=actor))
            db.flush()


def test_schema_has_context_and_revision_constraints():
    inspector = inspect(engine)
    assert "uq_rejection_label_context" in {r["name"] for r in inspector.get_unique_constraints("rejection_reason_labels")}
    assert "uq_rejection_label_revision" in {r["name"] for r in inspector.get_unique_constraints("rejection_reason_label_revisions")}
    with engine.connect() as connection:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
        targets = {"rejection_reason_labels", "rejection_reason_label_revisions"}
        context = MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, kind, reflected, compared: kind != "table" or name in targets,
        })
        affected_metadata = MetaData()
        for table in ("users", *sorted(targets)):
            Base.metadata.tables[table].to_metadata(affected_metadata)
        assert compare_metadata(context, affected_metadata) == []


def test_downgrade_refuses_to_erase_any_annotation(db, actors, monkeypatch):
    revision = apply(db, actors[0], request())
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261124_0083_rejection_annotations.py"
    spec = spec_from_file_location("annotation_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(db.connection())))
    with pytest.raises(RuntimeError, match="Downgrade blocked"):
        migration.downgrade()
    assert db.get(RejectionReasonLabelRevision, revision.id) is not None


def test_concurrent_review_one_winner_and_idempotent_replay():
    # Committed synthetic setup is confined to *_test. No QA or operational DB.
    ids = (uuid4(), uuid4())
    proposal = request()
    with Session(engine) as session:
        session.add_all([User(id=key, username=f"ml-race-{key}", password_hash="not-a-login", is_active=True) for key in ids])
        session.flush()
        apply(session, ids[0], proposal)
        session.commit()
    commands = [approved(proposal), approved(proposal)]

    def review(command):
        with Session(engine) as session:
            try:
                result = apply(session, ids[1], command)
                session.commit()
                return result.id
            except AnnotationConflict:
                session.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, commands))
    assert sum(value is not None for value in results) == 1
    winner = next(command for command in commands if command.request_id in results)
    assert review(winner) == winner.request_id
