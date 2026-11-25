"""ML-09 synthetic shadow decisions, never a model or provider operation."""

import json
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.ml.annotation_contract import AnnotationContext
from app.ml.recommendation import (
    Advice,
    CoreSnapshot,
    Simulation,
    State,
    recommend,
    snapshot_hash,
)
from app.ml.taxonomy import Category, Restriction
from app.services.ml_core_reader import (
    CoreEvidence,
    ReviewedStateMapping,
    map_core_evidence,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def snapshot(**kwargs):
    base = CoreSnapshot(
        source="virtualpos1", resource_type="charge", resource_id=UUID(int=1), evidence_id=UUID(int=2),
        evidence_at=NOW - timedelta(days=1), as_of=NOW, verified_through=NOW,
        state=State.REJECTED, state_mapping_sha256="a"*64, data_sha256="b"*64,
        context=AnnotationContext(source="virtualpos1", resource_type="charge", processor="unknown", code="-4", privacy_reviewed=True),
        mandate_active=True, retry_limit_reached=False, subscription_active=True, links_verified=True, settlement_verified=True,
    )
    return replace(base, **kwargs)


def test_rule_fallback_has_no_invented_probability_or_permission():
    result = recommend(snapshot())
    assert result.category == Category.INVALID and result.advice == Advice.MANUAL
    assert result.method == "rule" and result.matched_rules
    assert result.confidence is None and result.recovery_probability is None
    assert result.p1_artifact_id is None and result.p2_artifact_id is None
    assert not result.execution_allowed and not result.simulation
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions


@pytest.mark.parametrize("changes,advice", [
    ({"state": State.PAID}, Advice.NONE),
    ({"state": State.CANCELLED}, Advice.NONE),
    ({"subscription_active": False}, Advice.NONE),
    ({"verified_through": None}, Advice.REFRESH),
    ({"verified_through": NOW - timedelta(hours=2)}, Advice.REFRESH),
    ({"verified_through": NOW - timedelta(days=2)}, Advice.REFRESH),
    ({"state": State.UNKNOWN}, Advice.REVIEW),
    ({"state": State.PENDING}, Advice.REVIEW),
    ({"links_verified": False}, Advice.REVIEW),
    ({"settlement_verified": False}, Advice.REVIEW),
    ({"mandate_active": None}, Advice.REVIEW),
    ({"retry_limit_reached": None}, Advice.REVIEW),
    ({"subscription_active": None}, Advice.REVIEW),
    ({"retry_limit_reached": True}, Advice.REVIEW),
    ({"mandate_active": False}, Advice.MANDATE),
    ({"context": None}, Advice.REVIEW),
])
def test_current_state_coverage_and_unknown_constraints_override_advice(changes, advice):
    result = recommend(snapshot(**changes))
    assert result.advice == advice and not result.execution_allowed


@pytest.mark.parametrize("code,expected", [("-5", Advice.SECURITY), ("-7", Advice.MANDATE)])
def test_dangerous_signals_are_not_collection_instructions(code, expected):
    ctx = replace(snapshot().context, code=code)
    result = recommend(snapshot(context=ctx))
    assert result.advice == expected
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions


def test_conflict_unknown_and_processor_code_abstain():
    context = replace(snapshot().context, code="-4", normalized_text="Tarjeta expirada")
    result = recommend(snapshot(context=context))
    assert result.category is None and result.classification_state == "conflict"
    assert result.advice in {Advice.MANDATE, Advice.REVIEW}
    result = recommend(snapshot(context=replace(snapshot().context, code="ZZZ")))
    assert result.category is None and result.advice == Advice.REVIEW
    result = recommend(snapshot(context=replace(snapshot().context, processor_code="51")))
    assert result.advice == Advice.REVIEW and "processor_code_requires_review" in result.reasons


def test_logical_identity_tracks_inputs_policy_and_outputs_without_null_model_key():
    original = snapshot()
    assert recommend(original) == recommend(original)
    baseline = recommend(original).logical_id
    variants = [replace(original, state=State.PAID), replace(original, data_sha256="c"*64),
                replace(original, evidence_id=UUID(int=3)), replace(original, resource_type="payment", context=None),
                replace(original, state_mapping_sha256="d"*64), replace(original, as_of=NOW+timedelta(seconds=1))]
    assert all(recommend(row).logical_id != baseline for row in variants)
    assert recommend(original, max_age_seconds=20).logical_id != baseline
    assert recommend(original, simulation=True).logical_id != baseline
    other = replace(original, source="virtualpos2", context=replace(original.context, source="virtualpos2"))
    assert recommend(other).logical_id != baseline


def test_synthetic_outputs_are_bound_to_snapshot_and_do_not_authorize_actions():
    row = snapshot()
    low = Simulation("p2", row.source, "c"*64, snapshot_hash(row), score=0.01)
    high = replace(low, score=0.99)
    a = recommend(row, simulations=(low,), simulation=True)
    b = recommend(row, simulations=(high,), simulation=True)
    assert a.advice == b.advice == Advice.REVIEW
    assert a.simulated_p2 == 0.01 and b.simulated_p2 == 0.99
    assert a.recovery_probability is None and b.recovery_probability is None
    assert a.logical_id != b.logical_id
    assert not a.execution_allowed
    for outputs in ((low, low), (replace(low, source="toku"),), (replace(low, input_sha256="d"*64),)):
        with pytest.raises(ValueError):
            recommend(row, simulations=outputs, simulation=True)
    with pytest.raises(ValueError):
        recommend(row, simulations=(low,))


def test_p1_simulation_only_fills_unmapped_and_preserves_rules_and_restrictions():
    row = snapshot(context=None)
    p1 = Simulation("p1", row.source, "c"*64, snapshot_hash(row), category=Category.FUNDS)
    result = recommend(row, simulations=(p1,), simulation=True)
    assert result.category == Category.FUNDS and result.method == "simulated_p1"
    assert result.advice == Advice.REVIEW and result.confidence is None
    dangerous = snapshot(context=replace(snapshot().context, code="-5"))
    result = recommend(dangerous, simulations=(replace(p1, input_sha256=snapshot_hash(dangerous)),), simulation=True)
    assert result.category == Category.FRAUD and result.advice == Advice.SECURITY
    assert "model_rule_disagreement" in result.reasons


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, True, "0.5", None])
def test_invalid_probability_is_rejected(score):
    with pytest.raises(ValueError):
        Simulation("p2", "toku", "a"*64, "b"*64, score=score)


@pytest.mark.parametrize("changes", [
    {"source": "virtualpos"}, {"resource_type": "client"}, {"resource_id": "personal-id"},
    {"state": "paid"}, {"as_of": NOW.replace(tzinfo=None)}, {"evidence_at": NOW+timedelta(seconds=1)},
    {"verified_through": NOW+timedelta(seconds=1)}, {"mandate_active": 1}, {"links_verified": "true"},
    {"context": replace(snapshot().context, source="toku")}, {"data_sha256": "not-a-hash"},
])
def test_invalid_snapshot_cannot_reach_policy(changes):
    with pytest.raises(ValueError):
        snapshot(**changes)


def test_output_does_not_echo_resource_ids_or_glosa_and_import_has_no_runtime():
    row = snapshot(context=replace(snapshot().context, normalized_text="Mensaje revisado desconocido"))
    encoded = json.dumps(asdict(recommend(row)))
    assert row.context.normalized_text not in encoded and str(row.resource_id) not in encoded
    code = "import sys; import app.ml.recommendation; import app.services.ml_core_reader; assert not any(k in sys.modules for k in ('sklearn', 'skops', 'app.core.config', 'app.db.session'))"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def evidence(**kwargs):
    row = CoreEvidence("virtualpos1", "charge", UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=1),
                       "raw-rejected", "raw-active", "-4", NOW-timedelta(days=1), NOW, NOW, True)
    return replace(row, **kwargs)


def mapping():
    return ReviewedStateMapping("virtualpos1", "charge", "a"*64,
                                (("raw-rejected", State.REJECTED), ("raw-paid", State.PAID)), (("raw-active", True),))


def test_core_mapper_does_not_invent_coverage_or_status_or_mandate():
    row = evidence()
    result = map_core_evidence(row, mapping(), as_of=NOW)
    assert result.state == State.REJECTED and result.subscription_active is True
    assert result.mandate_active is None and result.retry_limit_reached is None
    assert recommend(result).advice == Advice.REFRESH  # updated_at != provider coverage.
    unknown = map_core_evidence(replace(row, source_status="new-state", subscription_status="new-state"), mapping(), as_of=NOW)
    assert unknown.state == State.UNKNOWN and unknown.subscription_active is None
    paid = map_core_evidence(replace(row, source_status="raw-paid"), mapping(), as_of=NOW)
    assert recommend(paid).advice == Advice.NONE
    future = evidence(updated_at=NOW+timedelta(seconds=1))
    with pytest.raises(ValueError):
        map_core_evidence(future, mapping(), as_of=NOW)
    with pytest.raises(ValueError):
        map_core_evidence(row, replace(mapping(), source="toku"), as_of=NOW)
    with pytest.raises(ValueError):
        map_core_evidence(row, mapping(), as_of=NOW, context=replace(snapshot().context, code="-5"))


def test_mapping_provenance_and_missing_evidence_are_explicit():
    with pytest.raises(ValueError):
        replace(mapping(), states=(("raw-rejected", State.REJECTED), ("raw-rejected", State.PAID)))
    for change in ({"evidence_id": None}, {"rejection_at": None}):
        with pytest.raises(ValueError):
            map_core_evidence(evidence(**change), mapping(), as_of=NOW)
    a = map_core_evidence(evidence(), mapping(), as_of=NOW)
    b = map_core_evidence(evidence(), replace(mapping(), review_sha256="c"*64), as_of=NOW)
    assert recommend(a).logical_id != recommend(b).logical_id


def test_terminal_state_dominates_even_security_and_high_simulated_score():
    for state in (State.PAID, State.CANCELLED):
        row = snapshot(state=state, context=replace(snapshot().context, code="-5"), verified_through=None)
        output = Simulation("p2", row.source, "c"*64, snapshot_hash(row), score=0.99)
        result = recommend(row, simulations=(output,), simulation=True)
        assert result.advice == Advice.NONE and result.recovery_probability is None
        assert not result.execution_allowed


def test_model_simulation_cannot_resolve_conflicting_evidence():
    row = snapshot(context=replace(snapshot().context, normalized_text="Tarjeta expirada"))
    output = Simulation("p1", row.source, "c"*64, snapshot_hash(row), category=Category.FUNDS)
    result = recommend(row, simulations=(output,), simulation=True)
    assert result.category is None and result.rules_state == result.classification_state == "conflict"
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions


def test_equal_instants_in_different_timezones_have_equal_logical_identity():
    row = snapshot()
    zone = timezone(timedelta(hours=-3))
    other = replace(row, as_of=row.as_of.astimezone(zone), evidence_at=row.evidence_at.astimezone(zone),
                    verified_through=row.verified_through.astimezone(zone))
    assert recommend(row) == recommend(other)


def test_technical_fault_advice_has_no_retry_time_or_execution():
    row = snapshot(context=replace(snapshot().context, code="-2"))
    result = recommend(row)
    assert result.advice == Advice.TECHNICAL and result.category == Category.TECH
    assert not result.execution_allowed and not hasattr(result, "recommended_retry_date")
