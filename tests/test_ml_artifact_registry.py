"""PostgreSQL registry tests: synthetic artifacts in a guarded disposable *_test DB."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_ml_artifacts import fixture_artifact

from app.db.session import Base, engine
from app.ml import export_files
from app.models.auth import User
from app.models.ml_artifact import MlArtifact, MlArtifactEvent, MlArtifactRelease
from app.services.ml_artifacts import (
    RegistryConflict,
    approve_artifact,
    register_artifact,
    simulate_release,
)


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def actors(db):
    keys = (uuid4(), uuid4())
    db.add_all([User(id=key, username=f"ml08-synthetic-{key}", password_hash="not-a-login", is_active=True) for key in keys])
    db.flush()
    return keys


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(export_files, "_permissions", lambda *a, **k: None)
    root = tmp_path / "private"
    return fixture_artifact(root), fixture_artifact(root, serial=2)


def approve(db, artifact, actors, revision):
    register_artifact(db, artifact, actor=actors[0], expected_revision=revision)
    return approve_artifact(db, artifact, actor=actors[1], expected_revision=revision+1,
                            approval_sha256="a"*64, simulation=True)


def switch(db, artifact, actors, revision, action="promoted"):
    return simulate_release(db, task="p2", source="virtualpos1", target_id=artifact.artifact_id if artifact else None,
                            actor=actors[1], expected_revision=revision, approval_sha256="b"*64,
                            action=action, simulation=True)


def test_register_approve_simulate_replace_rollback_and_disable_with_audit(db, actors, artifacts):
    first, second = artifacts
    approve(db, first, actors, 0)
    release = switch(db, first, actors, 2)
    assert release.active_artifact_id == first.artifact_id and release.revision == 3
    approve(db, second, actors, 3)
    switch(db, second, actors, 5)
    release = switch(db, first, actors, 6, "rolled_back")
    assert release.active_artifact_id == first.artifact_id
    release = switch(db, None, actors, 7, "disabled")
    assert release.active_artifact_id is None and release.revision == 8
    events = db.scalars(select(MlArtifactEvent).order_by(MlArtifactEvent.revision)).all()
    assert [event.revision for event in events] == list(range(1, 9))
    assert len(db.scalars(select(MlArtifactRelease)).all()) == 1
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_idempotent_registration_does_not_replace_metadata_or_history(db, actors, artifacts):
    first = artifacts[0]
    original = register_artifact(db, first, actor=actors[0], expected_revision=0)
    replay = register_artifact(db, first, actor=actors[0], expected_revision=0)
    assert replay.id == original.id and db.get(MlArtifactRelease, ("p2", "virtualpos1")).revision == 1
    with pytest.raises(RegistryConflict):
        register_artifact(db, replace(first, manifest_sha256="0"*64), actor=actors[0], expected_revision=0)
    altered = deepcopy(first.descriptor)
    altered["source"] = "toku"
    with pytest.raises(RegistryConflict, match="modificado"):
        register_artifact(db, replace(first, descriptor=altered), actor=actors[0], expected_revision=0)


def test_independent_approval_and_explicit_simulation_required(db, actors, artifacts):
    first = artifacts[0]
    register_artifact(db, first, actor=actors[0], expected_revision=0)
    with pytest.raises(RegistryConflict, match="segundo"):
        approve_artifact(db, first, actor=actors[0], expected_revision=1, approval_sha256="a"*64, simulation=True)
    with pytest.raises(RegistryConflict):
        approve_artifact(db, first, actor=actors[1], expected_revision=1, approval_sha256="a"*64)
    with pytest.raises(RegistryConflict):
        approve_artifact(db, replace(first, compatible=False), actor=actors[1], expected_revision=1, approval_sha256="a"*64, simulation=True)
    approve_artifact(db, first, actor=actors[1], expected_revision=1, approval_sha256="a"*64, simulation=True)
    with pytest.raises(RegistryConflict):
        simulate_release(db, task="p2", source="virtualpos1", target_id=first.artifact_id,
                         actor=actors[1], expected_revision=2, approval_sha256="a"*64, action="promoted")
    with pytest.raises(RegistryConflict):
        switch(db, first, actors, 1)
    assert db.get(MlArtifactRelease, ("p2", "virtualpos1")).revision == 2


def test_no_unapproved_wrong_channel_or_never_published_rollback(db, actors, artifacts, tmp_path):
    first = artifacts[0]
    register_artifact(db, first, actor=actors[0], expected_revision=0)
    with pytest.raises(RegistryConflict):
        switch(db, first, actors, 1)
    approve_artifact(db, first, actor=actors[1], expected_revision=1, approval_sha256="a"*64, simulation=True)
    with pytest.raises(RegistryConflict):
        switch(db, first, actors, 2, "rolled_back")
    other = fixture_artifact(tmp_path / "other", serial=3, source="toku", candidate="char_tfidf_logistic")
    approve(db, other, actors, 0)
    with pytest.raises(RegistryConflict):
        switch(db, other, actors, 2)
    assert db.get(MlArtifactRelease, ("p2", "virtualpos1")).active_artifact_id is None


def test_outer_rollback_keeps_caller_in_control(db, actors, artifacts):
    first = artifacts[0]
    register_artifact(db, first, actor=actors[0], expected_revision=0)
    db.rollback()
    assert db.get(MlArtifact, first.artifact_id) is None
    assert db.get(User, actors[0]) is None


def test_database_enforces_immutability_scope_and_matching_audit(db, actors, artifacts, tmp_path):
    first = artifacts[0]
    approve(db, first, actors, 0)
    other = fixture_artifact(tmp_path / "other", serial=3, source="toku", candidate="char_tfidf_logistic")
    approve(db, other, actors, 0)
    for command, params in [
        ("UPDATE ml_artifacts SET manifest_sha256='changed' WHERE id=:id", {"id": first.artifact_id}),
        ("DELETE FROM ml_artifact_events WHERE task='p2' AND source='virtualpos1'", {}),
        ("UPDATE ml_artifact_releases SET active_artifact_id=:id WHERE task='p2' AND source='virtualpos1'", {"id": other.artifact_id}),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text(command), params)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text("UPDATE ml_artifact_releases SET revision=99 WHERE task='p2' AND source='virtualpos1'"))
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert db.get(MlArtifactRelease, ("p2", "virtualpos1")).revision == 2


def test_migration_metadata_matches_and_downgrade_preserves_history(db, actors, artifacts, monkeypatch):
    register_artifact(db, artifacts[0], actor=actors[0], expected_revision=0)
    metadata = MetaData()
    targets = {"ml_artifacts", "ml_artifact_releases", "ml_artifact_events"}
    for name in ("users", *sorted(targets)):
        Base.metadata.tables[name].to_metadata(metadata)
    context = MigrationContext.configure(db.connection(), opts={
        "include_object": lambda obj, name, kind, reflected, compared: kind != "table" or name in targets})
    assert compare_metadata(context, metadata) == []
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261125_0084_ml_artifact_registry.py"
    spec = spec_from_file_location("registry_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "op", Operations(context))
    with pytest.raises(RuntimeError, match="Downgrade blocked"):
        migration.downgrade()


def test_concurrent_simulated_promotions_have_one_winner(artifacts):
    first, second = artifacts
    ids = (uuid4(), uuid4())
    with Session(engine) as db:
        db.add_all([User(id=key, username=f"ml08-race-{key}", password_hash="not-a-login", is_active=True) for key in ids])
        db.flush()
        approve(db, first, ids, 0)
        approve(db, second, ids, 2)
        db.commit()

    def publish(artifact):
        with Session(engine) as db:
            try:
                switch(db, artifact, ids, 4)
                db.commit()
                return True
            except RegistryConflict:
                db.rollback()
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(publish, (first, second))) == 1
    with Session(engine) as db:
        state = db.get(MlArtifactRelease, ("p2", "virtualpos1"))
        assert state.revision == 5 and state.active_artifact_id in {first.artifact_id, second.artifact_id}
