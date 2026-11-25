"""ML-06: synthetic chronology, blind holdout and isolated package/CLI planning."""

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ml import evaluation_package, export_files
from app.ml.annotation_contract import prepare_context
from app.ml.dataset_export import ExportBundle, build_bundle, canonical_json, signature
from app.ml.evaluation_package import prepare_plan
from app.ml.evaluation_protocol import PlanningRow, build_plan, parse_protocol
from app.ml.export_snapshot import prepare_snapshot
from scripts.ml import prepare_evaluation

SECRET = b"synthetic-test-only-key-32-bytes"
PACKAGE = "a" * 64
FREEZE = datetime(2026, 1, 1, tzinfo=UTC)


def date(month, day=1):
    return datetime(2025, month, day, tzinfo=UTC)


def configuration(task="p2", **changes):
    result = prepare_evaluation.template(task)
    result.update(train_start=date(1).isoformat(), train_end=date(4).isoformat(),
                  calibration_end=date(7).isoformat(), selection_end=date(10).isoformat(),
                  test_end=date(12).isoformat(), expected_sources=["toku" if task == "p1" else "virtualpos1"],
                  criteria_status="agreed", practical_margin="0.02", minimum_prediction_coverage="0.8",
                  criteria_reference_sha256="b" * 64)
    # Criteria values are synthetic fixtures, never proposed operational thresholds.
    return result | changes


def protocol(task="p2", **changes):
    return parse_protocol(canonical_json(configuration(task, **changes)))


def planning_rows(task="p2"):
    return tuple(PlanningRow(f"{i:064x}", "toku" if task == "p1" else "virtualpos1",
                             date(month) + timedelta(hours=1), date(month) + timedelta(days=31),
                             date(month) + timedelta(days=30) if task == "p2" else None, f"{100+i:064x}")
                 for i, month in enumerate((1, 4, 7, 10), start=1))


def plan(rows=None, task="p2", **changes):
    return build_plan(tuple(rows) if rows is not None else planning_rows(task), protocol=protocol(task, **changes),
                      as_of=FREEZE, package_id=PACKAGE)


def snapshot(task="p2"):
    document = {
        "schema_version": "rejection-snapshot-v1", "task": task, "purpose": "synthetic",
        "as_of": FREEZE.isoformat(), "privacy_reviewed": True, "policy_reviewed": True,
        "provenance": {"adapter_version": "synthetic-ml06", "query_sha256": "c" * 64,
                       "source_snapshot_sha256": "d" * 64, "code_revision": "e" * 40,
                       "dependencies_sha256": "f" * 64, "study_mode": "retrospective-limited"},
    }
    if task == "p1":
        observations, reviews = [], []
        for i, (month, reason) in enumerate(zip((1, 4, 7, 10), ("Sin fondos", "Tarjeta bloqueada", "Error tecnico", "Tarjeta vencida"), strict=True), start=1):
            context = asdict(prepare_context(source="toku", resource_type="payment", processor="psp", reason=reason, privacy_reviewed=True))
            observations.append({"observation_id": str(UUID(int=i)), "context": context,
                                 "occurred_at": date(month).isoformat(), "available_at": (date(month)+timedelta(hours=1)).isoformat()})
            for revision, decision in [(1, "draft"), (2, "approved")]:
                reviews.append({"context": context, "revision": revision, "decision": decision,
                                "category": "FUNDS", "actor_id": str(UUID(int=revision)),
                                "reviewed_at": (date(month)+timedelta(days=revision)).isoformat()})
        document.update(observations=observations, reviews=reviews, review_history_complete=True)
    else:
        events, coverages = [], []
        for i, month in enumerate((1, 4, 7, 10), start=1):
            events.append({"event_id": str(UUID(int=i)), "source": "virtualpos1", "obligation_id": str(UUID(int=100+i)),
                           "kind": "rejection", "occurred_at": date(month).isoformat(),
                           "available_at": (date(month)+timedelta(hours=1)).isoformat(), "amount": "1000", "currency": "CLP",
                           "link_verified": True, "subscription_id": str(UUID(int=200+i)), "due_at": None, "due_available_at": None})
            coverages.append({"evidence_id": str(UUID(int=300+i)), "source": "virtualpos1", "obligation_id": str(UUID(int=100+i)),
                              "observed_from": date(month).isoformat(), "observed_through": (date(month)+timedelta(days=30)).isoformat(),
                              "available_at": (date(month)+timedelta(days=31)).isoformat(), "complete": True, "reconciled": True, "history_complete": True})
        document.update(events=events, coverages=coverages)
    return document


def bundle(document=None):
    return build_bundle(prepare_snapshot(canonical_json(document or snapshot())), secret=SECRET, scope="synthetic-ml06",
                        exporter_revision="e"*40, exporter_dependencies_sha256="f"*64, exporter_source_sha256="a"*64)


def repackage(original, name, data):
    """Trusted-producer malformed fixtures; recompute MAC so semantic guards are exercised."""
    files = dict(original.files)
    files[name] = data
    manifest = json.loads(original.manifest)
    manifest.pop("signature")
    manifest.pop("package_id")
    manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    manifest["package_id"] = hashlib.sha256(canonical_json(manifest)).hexdigest()
    manifest["signature"] = signature(canonical_json(manifest), SECRET, domain="manifest-v1")
    return ExportBundle(tuple(files.items()), canonical_json(manifest))


@pytest.fixture
def private(tmp_path, monkeypatch):
    # Native ACL is exercised separately; content guards do not need repeated ACL subprocesses.
    monkeypatch.setattr(export_files, "_permissions", lambda *args, **kwargs: None)
    return tmp_path / "private"


@pytest.mark.parametrize("task", ["p1", "p2"])
def test_four_disjoint_stages_deterministic_without_training(task):
    result = plan(task=task)
    assert result == plan(reversed(planning_rows(task)), task=task)
    assert result["status"] == "structural_preflight_passed"
    assert [len(values) for values in result["partitions"].values()] == [1, 1, 1, 1]
    assert len({key for values in result["partitions"].values() for key in values}) == 4
    assert result["comparison"]["benchmark_status"] == "not_run" and result["comparison"]["winner"] is None
    assert not result["training_executed"] and not result["test_labels_inspected"]


def test_purge_is_by_actual_inclusive_window_not_row_gap():
    rows = list(planning_rows())
    rows[0] = replace(rows[0], outcome_end=date(4), label_available_at=date(4))
    result = plan(rows)
    assert result["partitions"]["train"] == []
    assert result["exclusions"] == {"purged_overlapping_outcome": 1}
    rows[0] = replace(rows[0], outcome_end=date(4)-timedelta(microseconds=1))
    assert len(plan(rows)["partitions"]["train"]) == 1


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_labels_must_exist_at_their_own_fit_or_selection_cutoff(stage):
    rows = list(planning_rows("p1"))
    cutoff = protocol("p1").boundaries[stage+1]
    rows[stage] = replace(rows[stage], label_available_at=cutoff+timedelta(seconds=1))
    result = plan(rows, task="p1")
    assert result["exclusions"] == {"label_not_available_at_stage_cutoff": 1}
    rows[stage] = replace(rows[stage], label_available_at=cutoff)
    assert not plan(rows, task="p1")["exclusions"]


def test_grouped_test_is_forward_only_and_respects_pre_study_history():
    rows = list(planning_rows())
    rows[3] = replace(rows[3], group=rows[0].group)
    result = plan(rows, group_policy="unseen_subscription")
    assert result["partitions"]["train"] == [rows[0].row_key]
    assert result["partitions"]["test"] == []
    assert result["exclusions"] == {"group_previously_observed": 1}
    previous = replace(rows[0], row_key="9"*64, calculated_at=date(1)-timedelta(days=1))
    result = plan([previous, *rows], group_policy="unseen_subscription")
    assert not result["partitions"]["train"]
    rows[1] = replace(rows[1], group=None)
    assert plan(rows, group_policy="unseen_subscription")["exclusions"]["missing_group"] == 1


def test_missing_criteria_source_counts_and_maturity_block_structural_pass():
    for changes in ({"criteria_status": "draft"}, {"practical_margin": None}, {"criteria_reference_sha256": None}, {"minimum_prediction_coverage": None}):
        assert "acceptance_criteria_not_agreed" in plan(**changes)["blockers"]
    assert any("insufficient_rows" in value for value in plan(expected_sources=["virtualpos1", "tch"])["blockers"])
    assert "test_period_not_fully_mature" in plan(test_end="2025-12-20T00:00:00Z")["blockers"]


@pytest.mark.parametrize("changes", [
    {"test_end": "2024-01-01T00:00:00Z"}, {"train_end": "2025-04-01"}, {"group_policy": "random"},
    {"practical_margin": "NaN"}, {"minimum_prediction_coverage": "1.1"}, {"max_threads": 0}, {"seed": True},
    {"expected_sources": []}, {"expected_sources": ["virtualpos"]}, {"model_path": "untrusted.pkl"},
])
def test_invalid_preregistrations_are_rejected_without_echo(changes):
    with pytest.raises(ValueError) as error:
        protocol(**changes)
    assert "untrusted.pkl" not in str(error.value)


def test_metadata_duplicates_future_clocks_and_scope_fail_closed():
    rows = planning_rows()
    with pytest.raises(ValueError):
        plan([*rows, rows[0]])
    with pytest.raises(ValueError):
        plan([replace(rows[0], label_available_at=FREEZE+timedelta(days=1))])
    with pytest.raises(ValueError):
        plan([replace(rows[0], outcome_end=None)])


@pytest.mark.parametrize("task", ["p1", "p2"])
def test_verified_package_planning_never_parses_targets(private, monkeypatch, task):
    # Deliberately not JSON, but correctly authenticated. Planning must not decode labels.
    original = repackage(bundle(snapshot(task)), "targets.jsonl", b"SEALED-LABELS-NOT-JSON\n")
    export_files.write_bundle(private, "input", original)
    reads = []
    read = evaluation_package.read_private_file

    def spy(root, relative, **kwargs):
        reads.append(relative)
        return read(root, relative, **kwargs)

    monkeypatch.setattr(evaluation_package, "read_private_file", spy)
    result = prepare_plan(private, "input", secret=SECRET, protocol=protocol(task))
    assert result["status"] == "structural_preflight_passed"
    assert reads == ["input/metadata.jsonl"]
    assert not any("target" in name for name in reads)


def test_unseen_wording_groups_case_accent_and_punctuation_across_contexts(private):
    document = snapshot("p1")
    # Add a new test observation of training wording, different context/capitalization.
    duplicate = copy.deepcopy(document["observations"][0])
    duplicate.update(observation_id=str(UUID(int=99)), occurred_at=date(10).isoformat(), available_at=(date(10)+timedelta(hours=1)).isoformat())
    duplicate["context"]["normalized_text"] = "SÍN FONDOS!"
    duplicate["context"]["processor"] = "other-psp"
    document["observations"].append(duplicate)
    for revision, decision in [(1, "draft"), (2, "approved")]:
        document["reviews"].append({"context": duplicate["context"], "revision": revision, "decision": decision,
                                    "category": "FUNDS", "actor_id": str(UUID(int=revision)), "reviewed_at": (date(10)+timedelta(days=revision)).isoformat()})
    export_files.write_bundle(private, "input", bundle(document))
    result = prepare_plan(private, "input", secret=SECRET, protocol=protocol("p1", group_policy="unseen_text"))
    assert result["exclusions"] == {"group_previously_observed": 1}
    assert len(result["partitions"]["test"]) == 1
    assert "FONDOS" not in json.dumps(result) and "Sin fondos" not in json.dumps(result)


def test_package_identity_wrong_key_and_temporal_corruption(private):
    original = bundle()
    export_files.write_bundle(private, "input", original)
    with pytest.raises(ValueError):
        prepare_plan(private, "input", secret=b"x"*32, protocol=protocol())
    with pytest.raises(ValueError):
        prepare_plan(private, "input", secret=SECRET, protocol=protocol("p1"))
    lines = [json.loads(line) for line in dict(original.files)["metadata.jsonl"].splitlines()]
    lines[0]["outcome_end"] = "2025-02-15T00:00:00Z"
    malformed = repackage(original, "metadata.jsonl", b"".join(canonical_json(row) for row in lines))
    export_files.write_bundle(private, "malformed", malformed)
    with pytest.raises(ValueError):
        prepare_plan(private, "malformed", secret=SECRET, protocol=protocol())


def test_signed_plan_reproducible_and_tampering_rejected():
    result = plan()
    signed = prepare_evaluation.sign_plan(result, secret=SECRET)
    assert signed == prepare_evaluation.sign_plan(plan(), secret=SECRET)
    prepare_evaluation.verify_plan(signed, secret=SECRET)
    with pytest.raises(ValueError):
        prepare_evaluation.verify_plan(signed, secret=b"x"*32)
    modified = json.loads(signed)
    modified["training_executed"] = True
    with pytest.raises(ValueError):
        prepare_evaluation.verify_plan(canonical_json(modified), secret=SECRET)


def test_cli_plan_and_verify_does_not_train_or_print_private_rows(private, monkeypatch, capsys):
    root = private.parent
    (root / ".local").mkdir()
    monkeypatch.setattr(prepare_evaluation, "ROOT", root)
    monkeypatch.setattr(prepare_evaluation, "source_fingerprint", lambda root: "a"*64)
    # This fixture isolates CLI provenance; the native smoke uses actual Git and ACL.
    monkeypatch.setattr(prepare_evaluation.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"e"*40 if "rev-parse" in args[0] else b""))
    (root / "scripts/ml").mkdir(parents=True)
    (root / "scripts/ml/prepare_evaluation.py").write_bytes(b"synthetic-cli")
    (root / "requirements.lock").write_bytes(b"synthetic-lock")
    storage = root / ".local/ml-private"
    assert prepare_evaluation.main(["init-protocol", "--task", "p2", "--destination", "protocols/template.json"]) == 0
    with pytest.raises(ValueError):
        parse_protocol((storage / "protocols/template.json").read_bytes())
    export_files.generate_key(storage, "keys/export.key")
    # Use the known synthetic key to sign this fixture package.
    (storage / "keys/export.key").write_bytes(SECRET)
    export_files.write_bundle(storage, "input", bundle())
    export_files.write_private_document(storage, "protocol.json", canonical_json(configuration()))
    assert prepare_evaluation.main(["plan", "--bundle", "input", "--protocol", "protocol.json", "--destination", "plans/run.json"]) == 0
    assert prepare_evaluation.main(["verify-plan", "--document", "plans/run.json"]) == 0
    assert prepare_evaluation.main(["plan", "--bundle", "input", "--protocol", "protocol.json", "--destination", "plans/run.json"]) == 2
    export_files.write_private_document(storage, "draft.json", canonical_json(configuration(criteria_status="draft")))
    assert prepare_evaluation.main(["plan", "--bundle", "input", "--protocol", "draft.json", "--destination", "plans/blocked.json"]) == 3
    output = capsys.readouterr()
    assert "1000" not in output.out and "Traceback" not in output.err and PACKAGE not in output.out


def test_module_imports_no_runtime_or_training_dependencies():
    code = "import sys; from scripts.ml import prepare_evaluation; assert not any(n in sys.modules for n in ('sklearn','pandas','app.db.session','app.core.config')); print('offline')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
    assert result.stdout.strip() == b"offline"
