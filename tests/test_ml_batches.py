"""Durability, restart and concurrency in guarded disposable PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from test_ml_batch_contract import NOW, snapshot

from app.db.session import Base, engine
from app.models.ml_batch import (
    MlBatch,
    MlBatchEvent,
    MlBatchItem,
    MlBatchResult,
    MlCoreReceipt,
)
from app.services import ml_batches as jobs

FACTORY = sessionmaker(bind=engine, expire_on_commit=False)
ON = {"enabled": True, "synthetic": True}


def receipt(source="tch", *, receipt_id=None):
    reference = receipt_id or uuid4()
    with FACTORY() as session, session.begin():
        jobs.stage_core_receipt(session, receipt_id=reference, source=source, cutoff=NOW, core_sha256="a"*64, **ON)
    return reference


def batch(rows=None, *, source="tch", max_attempts=3):
    rows = rows if rows is not None else (snapshot(uuid4().int % 10**12, source),)
    identity = jobs.prepare_batch(FACTORY, receipt_id=receipt(source), snapshots=rows, max_attempts=max_attempts, **ON)
    return identity, {jobs.snapshot_hash(row): row for row in rows}


def resolve(rows):
    return lambda ref: rows[ref.input_sha256]


def expire(claim):
    with FACTORY() as session, session.begin():
        session.execute(text("UPDATE ml_batch_items SET lease_until=clock_timestamp()-interval '1 second' WHERE batch_id=:id AND ordinal=:ordinal"),
                        {"id": claim.batch_id, "ordinal": claim.item.ordinal})


def ready(batch_id):
    with FACTORY() as session, session.begin():
        session.execute(text("UPDATE ml_batch_items SET retry_at=clock_timestamp()-interval '1 second' WHERE batch_id=:id AND state='queued'"), {"id": batch_id})


def test_disabled_is_a_true_noop_and_real_execution_is_blocked():
    def forbidden():
        raise AssertionError("Must not open any DB")
    assert jobs.prepare_batch(forbidden, receipt_id=uuid4(), snapshots=()) is None
    assert jobs.claim_next(forbidden, "a"*64) is None
    assert jobs.process_claim(forbidden, None, forbidden) == "disabled"
    assert jobs.stage_core_receipt(None, receipt_id=uuid4(), source="tch", cutoff=NOW, core_sha256="a"*64) is None
    with pytest.raises(jobs.BatchBlocked):
        jobs.prepare_batch(forbidden, receipt_id=uuid4(), snapshots=(), enabled=True)
    from app.core.config import Settings
    assert Settings.model_fields["ml_rejections_batches_enabled"].default is False


def test_guard_rejects_operational_database_names_without_connecting():
    for name in ("crm", "crm_qa_local_20261118", "crm_sandbox", "personal-test", None):
        fake = SimpleNamespace(scalar=lambda statement, name=name: name)
        with pytest.raises(jobs.BatchBlocked):
            jobs._safe(fake)


def test_worker_entrypoint_respects_runtime_flag_and_still_requires_synthetic_mode(monkeypatch):
    from app.core.config import settings
    def forbidden():
        raise AssertionError("Disabled worker must not connect")
    monkeypatch.setattr(settings, "ml_rejections_batches_enabled", False)
    assert jobs.process_next(forbidden, "a"*64, None) == "disabled"
    monkeypatch.setattr(settings, "ml_rejections_batches_enabled", True)
    with pytest.raises(jobs.BatchBlocked):
        jobs.process_next(forbidden, "a"*64, None)
    identity, rows = batch()
    assert jobs.process_next(FACTORY, identity, resolve(rows), synthetic=True) == "succeeded"
    assert jobs.process_next(FACTORY, identity, resolve(rows), synthetic=True) == "idle"


def test_receipt_and_synthetic_core_change_are_atomic_and_not_visible_before_commit():
    reference, core_id = uuid4(), uuid4()
    with FACTORY() as session:
        session.execute(text("INSERT INTO core_clients(id) VALUES (:id)"), {"id": core_id})
        jobs.stage_core_receipt(session, receipt_id=reference, source="tch", cutoff=NOW, core_sha256="a"*64, **ON)
        with pytest.raises(jobs.BatchBlocked, match="visible"):
            jobs.prepare_batch(FACTORY, receipt_id=reference, snapshots=(), **ON)
        session.rollback()
    with FACTORY() as session:
        assert session.get(MlCoreReceipt, reference) is None
        assert session.scalar(text("SELECT count(*) FROM core_clients WHERE id=:id"), {"id": core_id}) == 0
    receipt(receipt_id=reference)
    identity = jobs.prepare_batch(FACTORY, receipt_id=reference, snapshots=(), **ON)
    with FACTORY() as session:
        assert session.get(MlBatch, identity).state == "completed"


@pytest.mark.parametrize("source", ["virtualpos1", "virtualpos2", "toku", "payku", "tch"])
def test_every_channel_has_same_committed_core_gate_and_persistent_result(source):
    identity, rows = batch(source=source)
    claim = jobs.claim_next(FACTORY, identity, **ON)
    assert jobs.process_claim(FACTORY, claim, resolve(rows), **ON) == "succeeded"
    assert jobs.process_claim(FACTORY, claim, resolve(rows), **ON) == "stale_claim"
    assert jobs.claim_next(FACTORY, identity, **ON) is None
    with FACTORY() as session:
        saved = session.get(MlBatch, identity)
        result = session.get(MlBatchResult, session.get(MlBatchItem, (identity, 0)).result_id)
        assert saved.state == "completed" and saved.finished_at is not None
        assert result.source == source and result.result["recovery_probability"] is None
        assert result.result["execution_allowed"] is False
        assert "normalized_text" not in str(result.result)
        assert session.scalar(select(func.count()).select_from(MlBatchEvent).where(MlBatchEvent.batch_id == identity)) == 2


def test_concurrent_dispatch_is_idempotent_and_result_shared_across_batches():
    rows = (snapshot(uuid4().int % 10**12),)
    reference = receipt()
    def dispatch(_):
        return jobs.prepare_batch(FACTORY, receipt_id=reference, snapshots=rows, **ON)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(dispatch, range(2)))
    assert first == second
    claim = jobs.claim_next(FACTORY, first, **ON)
    jobs.process_claim(FACTORY, claim, resolve({jobs.snapshot_hash(rows[0]): rows[0]}), **ON)
    other, data = batch(rows)
    jobs.process_claim(FACTORY, jobs.claim_next(FACTORY, other, **ON), resolve(data), **ON)
    with FACTORY() as session:
        one, two = session.get(MlBatchItem, (first, 0)), session.get(MlBatchItem, (other, 0))
        assert one.result_id == two.result_id
        assert session.scalar(select(func.count()).select_from(MlBatchItem).where(MlBatchItem.batch_id == first)) == 1


def test_crash_recovery_fences_old_owner_and_new_process_resumes():
    identity, rows = batch()
    old = jobs.claim_next(FACTORY, identity, **ON)
    assert jobs.claim_next(FACTORY, identity, **ON) is None
    expire(old)
    replacement = sessionmaker(bind=engine, expire_on_commit=False)
    new = jobs.claim_next(replacement, identity, **ON)
    assert new.attempt == 2 and new.lease_token != old.lease_token
    def forbidden(_):
        raise AssertionError("Previous owner must not recompute")
    assert jobs.process_claim(FACTORY, old, forbidden, **ON) == "stale_claim"
    assert jobs.process_claim(replacement, new, resolve(rows), **ON) == "succeeded"
    with FACTORY() as session:
        assert "lease_expired" in session.scalars(select(MlBatchEvent.error_code).where(
            MlBatchEvent.batch_id == identity)).all()


def test_partial_failure_has_bounded_retry_and_sanitized_append_only_events():
    identity, rows = batch((snapshot(uuid4().int % 10**12), snapshot(uuid4().int % 10**12)), max_attempts=2)
    def broken(_):
        raise RuntimeError("secret=synthetic-sensitive-message-never-store")
    first = jobs.claim_next(FACTORY, identity, **ON)
    assert jobs.process_claim(FACTORY, first, broken, **ON) == "retry"
    second = jobs.claim_next(FACTORY, identity, **ON)
    assert second.item.ordinal != first.item.ordinal
    assert jobs.process_claim(FACTORY, second, resolve(rows), **ON) == "succeeded"
    ready(identity)
    last = jobs.claim_next(FACTORY, identity, **ON)
    assert jobs.process_claim(FACTORY, last, broken, **ON) == "failed"
    with FACTORY() as session:
        assert session.get(MlBatch, identity).state == "completed_with_errors"
        errors = session.scalars(select(MlBatchEvent.error_code).where(MlBatchEvent.batch_id == identity)).all()
        assert errors.count("calculation_failed") == 2
        assert "secret" not in str(errors)


def test_changed_snapshot_fails_without_retry_or_using_stale_recommendation():
    identity, rows = batch()
    claim = jobs.claim_next(FACTORY, identity, **ON)
    original = rows[claim.item.input_sha256]
    assert jobs.process_claim(FACTORY, claim, lambda _: replace(original, data_sha256="f"*64), **ON) == "failed"
    with FACTORY() as session:
        item = session.get(MlBatchItem, (identity, 0))
        assert item.attempts == 1 and item.result_id is None


def test_expired_last_attempt_is_terminal_and_running_process_cannot_finish_late():
    identity, rows = batch(max_attempts=1)
    claim = jobs.claim_next(FACTORY, identity, **ON)
    expire(claim)
    assert jobs.claim_next(FACTORY, identity, **ON) is None
    assert jobs.process_claim(FACTORY, claim, resolve(rows), **ON) == "stale_claim"
    with FACTORY() as session:
        assert session.get(MlBatch, identity).state == "completed_with_errors"
        assert session.get(MlBatchItem, (identity, 0)).state == "failed"


def test_concurrent_claimers_do_not_share_ownership():
    identity, _ = batch()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: jobs.claim_next(FACTORY, identity, **ON), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_conflicting_receipt_and_modified_claim_or_bundle_are_rejected():
    reference = receipt()
    with FACTORY() as session, pytest.raises(jobs.BatchBlocked):
        jobs.stage_core_receipt(session, receipt_id=reference, source="tch", cutoff=NOW, core_sha256="f"*64, **ON)
    identity, rows = batch()
    claim = jobs.claim_next(FACTORY, identity, **ON)
    with pytest.raises(jobs.BatchBlocked):
        jobs.process_claim(FACTORY, replace(claim, max_age_seconds=10), resolve(rows), **ON)


def test_bundle_drift_is_blocked_before_computation(monkeypatch):
    identity, _ = batch()
    claim = jobs.claim_next(FACTORY, identity, **ON)
    monkeypatch.setattr(jobs, "bundle_sha256", lambda: "f"*64)
    with pytest.raises(jobs.BatchBlocked, match="incompatible"):
        jobs.process_claim(FACTORY, claim, lambda _: None, **ON)


def test_unexpected_process_crash_leaves_recoverable_lease():
    identity, rows = batch()
    claim = jobs.claim_next(FACTORY, identity, **ON)
    def unexpected(_):
        raise AssertionError("Unanticipated process failure")
    with pytest.raises(AssertionError):
        jobs.process_claim(FACTORY, claim, unexpected, **ON)
    expire(claim)
    replacement = jobs.claim_next(FACTORY, identity, **ON)
    assert jobs.process_claim(FACTORY, replacement, resolve(rows), **ON) == "succeeded"


def test_result_item_and_audit_roll_back_together_on_storage_failure():
    identity, rows = batch()
    claim = jobs.claim_next(FACTORY, identity, **ON)
    def reject_audit(mapper, connection, target):
        if target.batch_id == identity and target.action == "succeeded":
            raise RuntimeError("Synthetic storage failure")
    event.listen(MlBatchEvent, "before_insert", reject_audit)
    try:
        with pytest.raises(RuntimeError):
            jobs.process_claim(FACTORY, claim, resolve(rows), **ON)
    finally:
        event.remove(MlBatchEvent, "before_insert", reject_audit)
    with FACTORY() as session:
        item = session.get(MlBatchItem, (identity, 0))
        assert item.state == "running" and item.result_id is None
        assert session.scalar(select(func.count()).select_from(MlBatchResult).where(
            MlBatchResult.input_sha256 == claim.item.input_sha256)) == 0
    expire(claim)
    assert jobs.process_claim(FACTORY, jobs.claim_next(FACTORY, identity, **ON), resolve(rows), **ON) == "succeeded"


def test_ml_failure_does_not_rewrite_operational_runs():
    def counts():
        with FACTORY() as session:
            return tuple(session.scalar(text(f"SELECT count(*) FROM {name}"))
                         for name in ("etl_runs", "sync_runs", "write_runs"))
    before = counts()
    identity, _ = batch(max_attempts=1)
    assert jobs.process_claim(FACTORY, jobs.claim_next(FACTORY, identity, **ON), lambda _: None, **ON) == "failed"
    assert counts() == before


def test_database_immutability_metadata_and_preserving_downgrade(monkeypatch):
    identity, rows = batch()
    jobs.process_claim(FACTORY, jobs.claim_next(FACTORY, identity, **ON), resolve(rows), **ON)
    for sql in ("UPDATE ml_core_receipts SET source='toku'", "DELETE FROM ml_batch_results", "DELETE FROM ml_batch_events",
                "UPDATE ml_batches SET total=9", "UPDATE ml_batch_items SET input_sha256='wrong'"):
        with FACTORY() as session, session.begin(), pytest.raises(IntegrityError):
            session.execute(text(sql))
    targets = {"ml_core_receipts", "ml_batches", "ml_batch_items", "ml_batch_results", "ml_batch_events"}
    metadata = MetaData()
    for name in sorted(targets):
        Base.metadata.tables[name].to_metadata(metadata)
    with FACTORY() as session:
        context = MigrationContext.configure(session.connection(), opts={
            "include_object": lambda obj, name, kind, reflected, compared: kind != "table" or name in targets})
        assert compare_metadata(context, metadata) == []
        path = Path(__file__).resolve().parents[1] / "alembic/versions/20261125_0085_ml_shadow_batches.py"
        spec = spec_from_file_location("ml_batch_migration", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "op", Operations(context))
        with pytest.raises(RuntimeError, match="Downgrade blocked"):
            module.downgrade()
