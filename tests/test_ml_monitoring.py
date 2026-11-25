"""Synthetic monitoring only: hand-written predictions/outcomes, no estimator loading."""

import copy
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from app.ml import export_files
from app.ml.batch_contract import digest
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import parse_protocol
from app.ml.monitoring import (
    CLASSES,
    VERSION,
    analyze,
    candidate_request,
    policy_template,
    tvd,
)
from app.ml.pipelines import recipe
from scripts.ml import monitor_rejections, prepare_evaluation

SECRET = b"synthetic-ml13-only-key-32-bytes"
AS_OF = datetime(2026, 12, 15, tzinfo=UTC)


def policy(**changes):
    return policy_template() | dict(criteria_status="reviewed", review_sha256="a"*64,
        minimum_rows=4, minimum_units=4, minimum_labels=4, minimum_class_rows=1) | changes


def observation(task, index, moment):
    label = CLASSES[index % len(CLASSES)] if task == "p1" else index % 2
    return dict(event_id=f"{index:064x}", unit_id=f"{index+1000:064x}", source="tch",
        predicted_at=moment.isoformat(), available_at=(moment-timedelta(hours=1)).isoformat(),
        prediction=label if task == "p1" else (0.9 if label else 0.1), label=label,
        label_available_at=(moment+timedelta(days=1 if task == "p1" else 30)).isoformat(),
        label_origin="independent_human_review" if task == "p1" else "verified_obligation_outcome",
        label_provenance_sha256="b"*64, outcome_link_verified=task == "p2",
        outcome_verified_through=(moment+timedelta(days=30)).isoformat() if task == "p2" else None,
        input_missing=False, context_unseen=False, failed=False, latency_ms=4,
        amount_clp=1000 if task == "p2" else None, elapsed_days=1 if task == "p2" else None,
        days_from_due=2 if task == "p2" else None)


def snapshot(task="p2"):
    count = 8 if task == "p1" else 4
    return dict(version=VERSION, purpose="synthetic", source="tch", task=task, as_of=AS_OF.isoformat(),
        source_verified_at=AS_OF.isoformat(), coverage_verified=True,
        reference_start="2026-09-01T00:00:00Z", reference_end="2026-09-10T00:00:00Z",
        current_start="2026-11-01T00:00:00Z", current_end="2026-11-10T00:00:00Z",
        model_mode="rules_only" if task == "p1" else "synthetic_predictions",
        artifact_id=None if task == "p1" else "c"*64,
        model_feature_schema_sha256=recipe("char_tfidf_logistic" if task == "p1" else "logistic")["schema_sha256"],
        baseline_protocol_sha256="d"*64,
        reference=[observation(task, i+1, datetime(2026, 9, 2, tzinfo=UTC)) for i in range(count)],
        current=[observation(task, i+101, datetime(2026, 11, 2, tzinfo=UTC)) for i in range(count)])


def protocol_data(task="p2"):
    return prepare_evaluation.template(task) | dict(expected_sources=["tch"], criteria_status="agreed",
        practical_margin="0.02", minimum_prediction_coverage="0.8", criteria_reference_sha256="e"*64,
        train_start="2026-01-01T00:00:00Z", train_end="2026-08-01T00:00:00Z",
        calibration_end="2026-10-01T00:00:00Z", selection_end="2027-02-01T00:00:00Z", test_end="2027-04-01T00:00:00Z")


def test_no_threshold_crossing_is_not_training_or_promotion_approval():
    result = analyze(snapshot(), policy())
    assert result["status"] == "no_threshold_crossing" and not result["alerts"]
    assert result["current"]["verified_labels"] == 4 and result["current"]["quality_ready"]
    assert result["current"]["metrics"]["brier"] == pytest.approx(0.01)
    assert result["brier_increase"] == pytest.approx(0)
    assert result["training_authorized"] is result["promotion_authorized"] is False


def test_p1_rules_metrics_are_not_probabilities_and_review_is_independent():
    data = snapshot("p1")
    result = analyze(data, policy())
    assert result["model_mode"] == "rules_only" and result["artifact_id"] is None
    assert result["current"]["metrics"]["primary"] == 1
    assert "brier" not in result["current"]["metrics"]
    request = candidate_request(result, report_id=digest(result), candidate_id="char_tfidf_logistic",
                                protocol=parse_protocol(canonical_json(protocol_data("p1"))))
    assert request["status"] == "awaiting_human_review" and request["previous_artifact_id"] is None
    data["current"][0]["label_origin"] = "ml02_rules"
    with pytest.raises(ValueError):
        analyze(data, policy())


def test_quality_degradation_with_unchanged_prediction_distribution_is_detected():
    data = snapshot()
    for row in data["current"]:
        row["prediction"] = 0.1 if row["label"] else 0.9
    result = analyze(data, policy())
    assert result["distribution_tvd"]["prediction"] == 0
    assert result["brier_increase"] == pytest.approx(0.8)
    assert "review_calibration" in result["alerts"] and result["status"] == "review_required"
    data = snapshot("p1")
    for row in data["current"]:
        row["prediction"] = CLASSES[(CLASSES.index(row["label"])+1) % len(CLASSES)]
    result = analyze(data, policy())
    assert result["distribution_tvd"]["prediction"] == 0 and result["f1_drop"] == 1
    assert "review_reason_classifier" in result["alerts"]


def test_drift_uses_fixed_bins_missing_included_not_current_quantiles():
    data = snapshot()
    for row in data["current"]:
        row["amount_clp"] = 100000
    result = analyze(data, policy())
    assert result["distribution_tvd"]["amount_clp"] == 1
    assert "investigate_distribution_shift" in result["alerts"]
    data["current"][0]["amount_clp"] = None
    result = analyze(data, policy())
    assert result["current"]["missing_input_rate"] == 0.25
    assert "audit_missing_features" in result["alerts"]
    assert tvd({}, {"a": 3}) is None and tvd({"a": 1}, {"b": 1}) == 1


def test_recent_positive_and_negative_both_excluded_until_full_horizon():
    data = snapshot()
    data["as_of"] = data["source_verified_at"] = "2026-11-20T00:00:00Z"
    for row in data["current"]:
        row["label_available_at"] = "2026-11-15T00:00:00Z"
        row["outcome_verified_through"] = "2026-11-20T00:00:00Z"
    result = analyze(data, policy())
    assert result["current"]["verified_labels"] == 0 and result["current"]["metrics"] is None
    assert result["current"]["exclusions"] == {"immature_30_day_window": 4}
    assert result["status"] == "insufficient_data"


@pytest.mark.parametrize("change,reason", [
    ({"label": None, "label_available_at": None, "label_origin": None, "label_provenance_sha256": None}, "label_missing"),
    ({"outcome_link_verified": False}, "outcome_link_or_coverage_unverified"),
    ({"outcome_verified_through": None}, "outcome_link_or_coverage_unverified"),
    ({"label_available_at": "2027-01-01T00:00:00Z"}, "label_not_available_at_cutoff"),
])
def test_missing_unknown_or_unavailable_outcomes_never_become_negatives(change, reason):
    data = snapshot()
    for row in data["current"]:
        row.update(change)
    result = analyze(data, policy())
    assert result["current"]["verified_labels"] == 0 and result["current"]["exclusions"][reason] == 4
    assert result["current"]["metrics"] is None and not result["quality_ready"]


def test_premature_negative_and_insufficient_class_support_block_quality_claim():
    data = snapshot()
    for row in data["current"]:
        row["label"] = 0
        row["label_available_at"] = "2026-11-03T00:00:00Z"
    result = analyze(data, policy())
    assert result["current"]["exclusions"]["premature_negative_label"] == 4
    for row in data["current"]:
        row["label_available_at"] = "2026-12-02T00:00:00Z"
    result = analyze(data, policy())
    assert result["current"]["verified_labels"] == 4 and not result["quality_ready"]
    assert "review_calibration" not in result["alerts"]


def test_repeated_units_and_unverified_or_stale_coverage_are_not_sufficient_evidence():
    for changes in ({"coverage_verified": False}, {"source_verified_at": None}, {"source_verified_at": "2026-11-01T00:00:00Z"}):
        result = analyze(snapshot() | changes, policy())
        assert not result["quality_ready"] and result["status"] == "insufficient_data"
    data = snapshot()
    for row in data["current"]:
        row["unit_id"] = "f"*64
    result = analyze(data, policy())
    assert result["current"]["distinct_units"] == 1 and not result["quality_ready"]
    data = snapshot()
    data["reference"][0].update(label=None, label_available_at=None, label_origin=None, label_provenance_sha256=None)
    result = analyze(data, policy(minimum_labels=2, minimum_units=2))
    assert result["reference"]["label_coverage"] == 0.75 and not result["quality_ready"]
    assert "review_calibration" not in result["alerts"]


@pytest.mark.parametrize("change", [
    {"purpose": "reviewed-real"}, {"source": "virtualpos"}, {"task": "p3"}, {"artifact_id": None},
    {"model_mode": "trained"}, {"as_of": "2026-12-15"}, {"current_start": "2026-09-01T00:00:00Z"},
    {"source_verified_at": "2027-01-01T00:00:00Z"}, {"model_feature_schema_sha256": "f"*64},
])
def test_incompatible_scopes_times_and_versions_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        analyze(snapshot() | change, policy())


@pytest.mark.parametrize("change", [{"prediction": True}, {"prediction": float("nan")}, {"label": False},
    {"amount_clp": 1.5}, {"elapsed_days": 30}, {"source": "toku"}, {"failed": True},
    {"name": "MUST NOT STORE"}, {"available_at": "2026-12-01T00:00:00Z"}])
def test_bad_rows_and_extra_personal_fields_rejected(change):
    data = snapshot()
    data["current"][0].update(change)
    with pytest.raises((ValueError, TypeError)):
        analyze(data, policy())


def test_reports_are_order_independent_aggregate_only_and_do_not_change_inputs():
    data, criteria = snapshot(), policy()
    saved = copy.deepcopy(data)
    a = analyze(data, criteria)
    assert data == saved
    data["reference"].reverse()
    data["current"].reverse()
    assert canonical_json(analyze(data, criteria)) == canonical_json(a)
    encoded = canonical_json(a).decode()
    assert "event_id" not in encoded and "unit_id" not in encoded and "label_provenance_sha256" not in encoded
    assert "label_available_at" not in encoded


def test_empty_windows_do_not_manufacture_zero_error_or_zero_drift():
    data = snapshot() | {"reference": [], "current": []}
    result = analyze(data, policy())
    assert result["status"] == "insufficient_data"
    assert result["current"]["metrics"] is None and result["current"]["prediction_coverage"] is None
    assert all(value is None for value in result["distribution_tvd"].values())


def test_prediction_abstention_failure_unknown_context_and_label_coverage_are_distinct():
    data = snapshot()
    for row in data["current"][:2]:
        row.update(prediction=None, failed=True, context_unseen=True)
    result = analyze(data, policy())
    assert result["current"]["prediction_coverage"] == result["current"]["failure_rate"] == 0.5
    assert result["current"]["label_coverage"] == 1
    assert {"review_prediction_coverage", "investigate_calculation_failures", "review_unknown_contexts"} <= set(result["alerts"])
    request = candidate_request(result, report_id=digest(result), candidate_id="logistic", protocol=parse_protocol(canonical_json(protocol_data())))
    assert request["status"] == "blocked_data"


def test_event_duplicates_extra_fields_and_resource_budget_rejected():
    data = snapshot()
    data["current"][0]["event_id"] = data["reference"][0]["event_id"]
    with pytest.raises(ValueError, match="repetido"):
        analyze(data, policy())
    with pytest.raises(ValueError):
        analyze(snapshot() | {"personal_data": "MUST NOT STORE"}, policy())
    with pytest.raises(ValueError, match="excesiva"):
        analyze(snapshot() | {"current": [snapshot()["current"][0]] * 5001}, policy())
    for source in ("virtualpos1", "virtualpos2", "toku", "payku", "tch"):
        data = snapshot() | {"source": source}
        for row in data["reference"] + data["current"]:
            row["source"] = source
        assert analyze(data, policy())["source"] == source
        data["current"][0]["source"] = "virtualpos2" if source != "virtualpos2" else "virtualpos1"
        with pytest.raises(ValueError):
            analyze(data, policy())


@pytest.mark.parametrize("change", [{"maximum_ece": float("nan")}, {"minimum_rows": True},
    {"amount_edges_clp": [5000, 1000]}, {"due_edges_days": [-1, -1]}, {"review_sha256": None}])
def test_invalid_monitor_criteria_do_not_run(change):
    with pytest.raises(ValueError):
        analyze(snapshot(), policy(**change))


def test_candidate_is_pending_human_review_and_never_equivalent_to_a_fitted_artifact():
    result = analyze(snapshot(), policy())
    request = candidate_request(result, report_id=digest(result), candidate_id="logistic", protocol=parse_protocol(canonical_json(protocol_data())))
    assert request["status"] == "awaiting_human_review"
    assert request["training_authorized"] is request["promotion_authorized"] is False
    assert request["recipe"]["training_executed"] is False and request["previous_artifact_id"] == "c"*64
    draft = analyze(snapshot(), policy(criteria_status="draft", review_sha256=None))
    assert draft["status"] == "criteria_pending"
    assert candidate_request(draft, report_id=digest(draft), candidate_id="logistic", protocol=parse_protocol(canonical_json(protocol_data())))["status"] == "blocked_criteria"
    data = analyze(snapshot() | {"coverage_verified": False}, policy())
    assert candidate_request(data, report_id=digest(data), candidate_id="logistic", protocol=parse_protocol(canonical_json(protocol_data())))["status"] == "blocked_data"


def test_candidate_rejects_reused_holdout_or_other_task_source():
    report = analyze(snapshot(), policy())
    for change in ({"expected_sources": ["toku"]}, {"selection_end": "2026-11-01T00:00:00Z"}):
        with pytest.raises(ValueError):
            candidate_request(report, report_id=digest(report), candidate_id="logistic", protocol=parse_protocol(canonical_json(protocol_data() | change)))
    with pytest.raises(ValueError):
        candidate_request(report, report_id=digest(report), candidate_id="char_tfidf_logistic", protocol=parse_protocol(canonical_json(protocol_data())))
    protocol = parse_protocol(canonical_json(protocol_data()))
    with pytest.raises(ValueError):
        candidate_request(report | {"baseline_protocol_sha256": protocol.fingerprint},
                          report_id=digest(report), candidate_id="logistic", protocol=protocol)


def test_private_report_and_request_signatures_match_input_policy_and_new_protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(export_files, "_permissions", lambda *a, **k: None)
    root = tmp_path / "private"
    for relative, value in (("input.json", snapshot()), ("policy.json", policy()), ("protocol.json", protocol_data())):
        export_files.write_private_document(root, relative, canonical_json(value))
    monitor_rejections.prepare_report(root, input_relative="input.json", policy_relative="policy.json", destination="report.json", secret=SECRET)
    report = monitor_rejections.verify_record(root, "report.json", kind="report", secret=SECRET)
    assert report["status"] == "no_threshold_crossing"
    monitor_rejections.prepare_candidate(root, input_relative="input.json", policy_relative="policy.json", report_relative="report.json",
        protocol_relative="protocol.json", candidate_id="logistic", destination="candidate.json", secret=SECRET)
    request = monitor_rejections.verify_record(root, "candidate.json", kind="candidate", secret=SECRET)
    assert request["monitor_report_id"] == report["report_id"]
    with pytest.raises(ValueError):
        monitor_rejections.verify_record(root, "report.json", kind="candidate", secret=SECRET)
    with pytest.raises(ValueError):
        monitor_rejections.verify_record(root, "report.json", kind="report", secret=b"x"*32)
    (root / "policy.json").write_bytes(canonical_json(policy(maximum_ece=0.5)))
    with pytest.raises(ValueError):
        monitor_rejections.prepare_candidate(root, input_relative="input.json", policy_relative="policy.json", report_relative="report.json",
            protocol_relative="protocol.json", candidate_id="logistic", destination="different.json", secret=SECRET)


def test_monitor_import_has_no_scientific_runtime_db_settings_or_training():
    code = "import sys; import app.ml.monitoring; assert not any(x in sys.modules for x in ('sklearn','skops','app.db.session','app.core.config'))"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_report_reproducible_across_process_hash_seeds():
    data = snapshot()
    for row, amount in zip(data["reference"], (1000, 8000, 9000, 25000), strict=True):
        row["amount_clp"] = amount
    for row, amount in zip(data["current"], (1000, 1000, 30000, 40000), strict=True):
        row["amount_clp"] = amount
    code = "import sys,json; from app.ml.monitoring import analyze; from app.ml.dataset_export import canonical_json; d=json.load(sys.stdin); sys.stdout.buffer.write(canonical_json(analyze(d['snapshot'],d['policy'])))"
    outputs = [subprocess.run([sys.executable, "-c", code], input=canonical_json({"snapshot": data, "policy": policy()}),
                             env=os.environ | {"PYTHONHASHSEED": seed}, capture_output=True, check=True).stdout
               for seed in ("1", "99")]
    assert outputs[0] == outputs[1]
