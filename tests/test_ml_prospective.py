"""Hand-written synthetic prospective events; no actual exposure or provider action."""

import copy
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.ml import export_files
from app.ml.batch_contract import digest
from app.ml.dataset_export import canonical_json
from app.ml.prospective import event_record, measure, protocol, replay, template
from scripts.ml.measure_prospective import prepare_report, verify_report

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 3, 1, tzinfo=UTC)
SECRET = b"s"*32


def config(**changes):
    return template() | dict(study_id="a"*64, source="tch", enrollment_end="2026-01-15T00:00:00Z",
        minimum_mature_cases=2, minimum_units=2, criteria_status="agreed",
        criteria_reference_sha256="b"*64, capture_frame_sha256="c"*64) | changes


def checks(at, **changes):
    return dict(state="rejected", mandate_active=True, retry_limit_reached=False,
                links_verified=True, settlement_verified=True, checked_at=at.isoformat(), state_check_sha256="d"*64) | changes


def enrollment(at, index=1, **changes):
    return checks(at) | {"obligation_id": f"{index:064x}", "unit_id": f"{index+100:064x}"} | changes


def exposure(at, **changes):
    return dict(recommendation_id="e"*64, input_sha256="f"*64, bundle_sha256="1"*64,
        content_sha256="2"*64, analysis_as_of=at.isoformat(), display_id="3"*64) | changes


def outcome(enrolled, *, paid=True, **changes):
    deadline = enrolled+timedelta(days=30)
    return dict(status="full_net_payment" if paid else "unpaid", assessment_at=deadline.isoformat(),
        coverage_through=deadline.isoformat(), link_verified=True, evidence_sha256="4"*64,
        payment_at=(enrolled+timedelta(days=5)).isoformat() if paid else None, supersedes=None) | changes


def add(events, definition, kind, case, at, payload, *, recorded=None):
    record = event_record(study_id=definition["study_id"], protocol_sha256=digest(definition), revision=len(events)+1,
        previous_id=events[-1]["event_id"] if events else None, request_id=UUID(int=len(events)+1),
        actor_id=UUID(int=500), case_id=f"{case:064x}", kind=kind, occurred_at=at.isoformat(),
        recorded_at=(recorded or at).isoformat(), payload=payload)
    events.append(record)
    return record


def ledger():
    definition = protocol(config(), registered_at=START.isoformat())
    first, second = START+timedelta(days=1), START+timedelta(days=2)
    events = []
    add(events, definition, "enrolled", 1, first, enrollment(first))
    shown = add(events, definition, "exposed", 1, first+timedelta(hours=1), exposure(first))
    at = first+timedelta(hours=2)
    add(events, definition, "decision", 1, at, checks(at) | dict(choice="refer_existing_workflow", exposure_event_id=shown["event_id"], supersedes=None))
    add(events, definition, "enrolled", 2, second, enrollment(second, 2))
    add(events, definition, "outcome", 1, first+timedelta(days=31), outcome(first))
    add(events, definition, "outcome", 2, second+timedelta(days=31), outcome(second, paid=False))
    return definition, events


def rehash(events):
    replacements = {}
    for index, event in enumerate(events):
        old = event["event_id"]
        for key in ("exposure_event_id", "supersedes"):
            if key in event["payload"]:
                value = event["payload"][key]
                event["payload"][key] = replacements.get(value, value)
        event["previous_id"] = events[index-1]["event_id"] if index else None
        event["event_id"] = digest({key: value for key, value in event.items() if key != "event_id"})
        replacements[old] = event["event_id"]


def test_denominator_includes_eligible_unexposed_cases_and_rate_is_not_causal():
    definition, events = ledger()
    result = measure(definition, events, as_of=END.isoformat())
    assert result["counts"]["eligible"] == result["counts"]["mature_eligible"] == 2
    assert result["counts"]["exposed_cases"] == 1 and result["counts"]["without_decision"] == 1
    assert result["observed_recovery_rate"] == 0.5 and result["followup_coverage"] == 1
    assert result["mature_recovery_bounds"] == [.5, .5]
    assert result["recovery_rate_denominator"] == "verified_mature_outcomes"
    assert result["exposure_coverage"] == result["decision_coverage"] == 0.5
    assert result["status"] == "descriptive_only"
    assert result["causal_effect"] is result["causal_comparison"] is None
    assert result["workflow_execution_confirmed"] is result["execution_authorized"] is False


def test_recent_paid_and_unpaid_not_classified_until_horizon():
    definition, events = ledger()
    result = measure(definition, events, as_of=(START+timedelta(days=10)).isoformat())
    assert result["counts"]["immature_eligible"] == 2
    assert result["observed_recovery_rate"] is None and result["followup_coverage"] is None


def test_recorded_time_prevents_using_late_arriving_information_in_past_report():
    definition, events = ledger()
    events[-1]["recorded_at"] = (END+timedelta(days=5)).isoformat()
    rehash(events)
    result = measure(definition, events, as_of=END.isoformat())
    assert result["verified_mature_outcomes"] == 1 and result["excluded_mature_outcomes"] == {"no_followup": 1}
    assert result["observed_recovery_rate"] == 1 and result["status"] == "insufficient_followup"
    assert result["mature_recovery_bounds"] == [.5, 1]


@pytest.mark.parametrize("changes", [{"link_verified": False}, {"coverage_through": None},
    {"evidence_sha256": None}, {"status": "partial"}, {"status": "reversed"}, {"status": "unknown", "payment_at": None}])
def test_unknown_partial_reversed_or_unverified_is_never_implicitly_unpaid(changes):
    definition, events = ledger()
    events[-2]["payload"].update(changes)
    rehash(events)
    result = measure(definition, events, as_of=END.isoformat())
    assert result["counts"]["verified_unpaid"] == 1 and result["counts"]["verified_paid"] == 0
    assert result["verified_mature_outcomes"] == 1 and result["followup_coverage"] == 0.5


def test_corrections_append_and_never_change_earlier_knowledge():
    definition, events = ledger()
    before = measure(definition, events, as_of=END.isoformat())
    old = events[-2]
    add(events, definition, "outcome", 1, END+timedelta(days=1), old["payload"] | {"status": "reversed", "supersedes": old["event_id"]})
    assert measure(definition, events, as_of=END.isoformat())["observed_recovery_rate"] == before["observed_recovery_rate"]
    after = measure(definition, events, as_of=(END+timedelta(days=2)).isoformat())
    assert after["verified_mature_outcomes"] == 1 and after["excluded_mature_outcomes"] == {"partial_reversed_or_unknown": 1}


def test_repeated_displays_do_not_multiply_case_denominator():
    definition, events = ledger()
    add(events, definition, "exposed", 1, END, exposure(START, display_id="5"*64))
    result = measure(definition, events, as_of=END.isoformat())
    assert result["counts"]["exposure_events"] == 2 and result["counts"]["exposed_cases"] == 1
    assert result["counts"]["eligible"] == 2


@pytest.mark.parametrize("changes", [{"state": "paid"}, {"state": "cancelled"}, {"mandate_active": None},
    {"mandate_active": False}, {"retry_limit_reached": True}, {"links_verified": False}, {"settlement_verified": False}])
def test_ineligible_screened_cases_are_preserved_but_not_counted_as_recovery(changes):
    definition, events = ledger()
    events[0]["payload"].update(changes)
    events[2]["payload"]["choice"] = "needs_review"
    rehash(events)
    result = measure(definition, events, as_of=END.isoformat())
    assert result["counts"]["screened"] == 2 and result["counts"]["eligible"] == 1
    assert result["counts"]["ineligible"] == 1 and result["counts"]["verified_paid"] == 0


def test_unsafe_decision_does_not_count_as_authorized_action():
    definition, events = ledger()
    events[2]["payload"]["state"] = "paid"
    rehash(events)
    with pytest.raises(ValueError, match="No derivar"):
        replay(definition, events, as_of=END.isoformat())


@pytest.mark.parametrize("mutation", [
    lambda e: e[0]["payload"].update(name="MUST NOT STORE"),
    lambda e: e[0].update(occurred_at="2025-12-01T00:00:00Z"),
    lambda e: e[3]["payload"].update(obligation_id=e[0]["payload"]["obligation_id"]),
    lambda e: e[2]["payload"].update(exposure_event_id="f"*64),
    lambda e: e[1]["payload"].update(analysis_as_of="2027-01-01T00:00:00Z"),
    lambda e: e[-1]["payload"].update(assessment_at="2026-01-10T00:00:00Z"),
    lambda e: e[-1]["payload"].update(coverage_through="2027-01-01T00:00:00Z"),
])
def test_backfill_future_clocks_duplicates_wrong_references_and_pii_rejected(mutation):
    definition, events = ledger()
    mutation(events)
    rehash(events)
    with pytest.raises(ValueError):
        measure(definition, events, as_of=END.isoformat())


def test_history_gaps_tampering_and_protocol_scope_rejected():
    definition, events = ledger()
    for damaged in ([*events[:2], *events[3:]], list(reversed(events)), copy.deepcopy(events)):
        if len(damaged) == len(events) and damaged == events:
            damaged[0]["payload"]["state"] = "unknown"
        with pytest.raises(ValueError):
            measure(definition, damaged, as_of=END.isoformat())
    with pytest.raises(ValueError):
        measure(definition | {"source": "virtualpos2"}, events, as_of=END.isoformat())
    for invalid in (None, [], definition | {"unexpected": "value"}):
        with pytest.raises(ValueError):
            measure(invalid, events, as_of=END.isoformat())


def test_late_registration_of_cases_is_not_prospective_capture():
    definition, events = ledger()
    events[0]["recorded_at"] = (START+timedelta(days=2)).isoformat()
    events = events[:1]
    rehash(events)
    with pytest.raises(ValueError, match="retrospectiva"):
        measure(definition, events, as_of=END.isoformat())


def test_no_data_draft_criteria_and_repeated_units_do_not_imply_sufficient_study():
    definition, _ = ledger()
    empty = measure(definition, [], as_of=END.isoformat())
    assert empty["counts"]["screened"] == 0 and empty["observed_recovery_rate"] is None
    definition = protocol(config(criteria_status="draft", criteria_reference_sha256=None), registered_at=START.isoformat())
    events = []
    for index in (1, 2):
        at = START+timedelta(days=index)
        add(events, definition, "enrolled", index, at, enrollment(at, index, unit_id="6"*64))
    for index in (1, 2):
        at = START+timedelta(days=index)
        add(events, definition, "outcome", index, at+timedelta(days=31), outcome(at))
    result = measure(definition, events, as_of=END.isoformat())
    assert result["distinct_verified_units"] == 1 and result["status"] == "insufficient_followup"


def test_private_report_signatures_and_domain_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(export_files, "_permissions", lambda *args, **kwargs: None)
    root = tmp_path / "private"
    definition, events = ledger()
    export_files.write_private_document(root, "input.json", canonical_json({"protocol": definition, "events": events}))
    prepare_report(root, "input.json", "report.json", as_of=END.isoformat(), secret=SECRET)
    report = verify_report(root, "report.json", secret=SECRET)
    assert report["observed_recovery_rate"] == 0.5 and report["causal_effect"] is None
    assert "actor_id" not in canonical_json(report).decode()
    with pytest.raises(ValueError):
        verify_report(root, "report.json", secret=b"x"*32)
    (root / "report.json").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_report(root, "report.json", secret=SECRET)


def test_module_import_has_no_db_config_model_runtime_or_provider():
    code = "import sys; import app.ml.prospective; assert not any(x in sys.modules for x in ('app.db.session','app.core.config','sklearn','skops'))"
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
