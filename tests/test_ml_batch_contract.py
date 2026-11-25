"""Bounded manifests without DB, input text storage, model imports or credentials."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.ml.batch_contract import plan_batch
from app.ml.recommendation import CoreSnapshot, State

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def snapshot(index=1, source="tch"):
    return CoreSnapshot(source=source, resource_type="charge", resource_id=UUID(int=index),
        evidence_id=UUID(int=index+100), evidence_at=NOW-timedelta(days=1), as_of=NOW,
        verified_through=None, state=State.UNKNOWN, state_mapping_sha256="a"*64, data_sha256="b"*64)


def plan(rows=(), **kwargs):
    args = dict(receipt_id=UUID(int=500), source="tch", cutoff=NOW, core_sha256="c"*64, snapshots=rows)
    args.update(kwargs)
    return plan_batch(**args)


def test_manifest_is_independent_of_input_order_and_has_no_glosa():
    a, b = snapshot(), snapshot(2)
    assert plan((a, b)) == plan((b, a))
    result = plan((a, b))
    assert [item.ordinal for item in result.items] == [0, 1]
    assert len(result.id) == 64 and len(result.bundle_sha256) == 64
    encoded = json.dumps(asdict(result), default=str)
    assert "context" not in encoded and "normalized_text" not in encoded
    assert not plan().items


@pytest.mark.parametrize("changes", [
    {"receipt_id": "id"}, {"source": "virtualpos"}, {"cutoff": NOW.replace(tzinfo=None)},
    {"core_sha256": "bad"}, {"snapshots": []}, {"max_age_seconds": True},
    {"max_age_seconds": 86401}, {"max_attempts": 0}, {"max_attempts": 6},
    {"snapshots": (snapshot(), snapshot())}, {"snapshots": (snapshot(source="toku"),)},
    {"snapshots": (replace(snapshot(), as_of=NOW+timedelta(seconds=1)),)},
])
def test_manifest_rejects_ambiguous_or_unbounded_input(changes):
    with pytest.raises(ValueError):
        plan(**changes)


def test_cutoffs_versions_and_core_receipts_change_identity():
    baseline = plan((snapshot(),))
    assert plan((snapshot(),), core_sha256="d"*64).id != baseline.id
    assert plan((snapshot(),), receipt_id=UUID(int=501)).id != baseline.id
    assert plan((snapshot(),), max_attempts=2).id != baseline.id
    assert plan((snapshot(),), max_age_seconds=100).id != baseline.id
    zone = timezone(timedelta(hours=-3))
    assert plan((snapshot(),), cutoff=NOW.astimezone(zone)) == baseline
