"""Only hand-authored synthetic predictions; no estimator is trained or loaded."""

import copy
import json
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_ml_evaluation import SECRET, configuration, snapshot

from app.ml import export_files
from app.ml.dataset_export import build_bundle, canonical_json
from app.ml.evaluation_metrics import paired_interval, summarize
from app.ml.evaluation_package import prepare_plan
from app.ml.evaluation_protocol import parse_protocol
from app.ml.export_snapshot import prepare_snapshot
from app.ml.model_evaluation import (
    ARTIFACT_FIELDS,
    VERSION,
    evaluate,
    load_input,
    parse_predictions,
    rowset_sha,
    selective_records,
)
from scripts.ml import evaluate_models
from scripts.ml.prepare_evaluation import sign_plan


def study(task="p2"):
    document = snapshot(task)
    if task == "p2":
        original, proofs = copy.deepcopy(document["events"]), copy.deepcopy(document["coverages"])
        document.update(events=[], coverages=[])
        for stage, (event, proof) in enumerate(zip(original, proofs, strict=True)):
            for index in range(16):
                number = stage*100+index
                rejection = event | {"event_id": str(UUID(int=1000+number)), "obligation_id": str(UUID(int=2000+number)),
                                     "subscription_id": str(UUID(int=3000+stage*100+index//2))}
                document["events"].append(rejection)
                document["coverages"].append(proof | {"evidence_id": str(UUID(int=4000+number)), "obligation_id": rejection["obligation_id"]})
                if index % 2:
                    from datetime import datetime

                    clock = datetime.fromisoformat(event["occurred_at"])
                    document["events"].append(rejection | {"event_id": str(UUID(int=5000+number)), "kind": "confirmed_full_payment",
                                                           "occurred_at": (clock+timedelta(days=20)).isoformat(),
                                                           "available_at": (clock+timedelta(days=21)).isoformat()})
    else:
        original = copy.deepcopy(document["observations"])
        document.update(observations=[], reviews=[])
        for stage, event in enumerate(original):
            for index in range(16):
                number = stage*100+index
                context = event["context"] | {"processor": f"psp-{stage}-{index}",
                                               "normalized_text": "Sin fondos" if index % 2 else "Tarjeta vencida"}
                document["observations"].append(event | {"observation_id": str(UUID(int=1000+number)), "context": context})
                for revision, decision in ((1, "draft"), (2, "approved")):
                    document["reviews"].append({"context": context, "revision": revision, "decision": decision,
                                                "category": "FUNDS" if index % 2 else "EXPIRED", "reviewed_at": event["available_at"],
                                                "actor_id": str(UUID(int=revision))})
    return document


def criteria(task="p2"):
    return {"version": VERSION, "agreement_sha256": "b"*64, "classes": [0, 1] if task == "p2" else ["FUNDS", "EXPIRED"],
            "minimum_class_rows": 2, "minimum_independent_units": 2, "bootstrap_repetitions": 200,
            "calibration_bins": 10, "uncertainty_unit": "subscription" if task == "p2" else "context",
            "comparison_rule": "non_inferiority"}


@pytest.fixture
def private(tmp_path, monkeypatch):
    monkeypatch.setattr(export_files, "_permissions", lambda *args, **kwargs: None)
    return tmp_path / "private"


def setup_study(root, task="p2"):
    prepared = prepare_snapshot(canonical_json(study(task)))
    package = build_bundle(prepared, secret=SECRET, scope="ml07-synthetic", exporter_revision="e"*40,
                           exporter_dependencies_sha256="f"*64, exporter_source_sha256="a"*64)
    export_files.write_bundle(root, "input", package)
    protocol_data = canonical_json(configuration(task))
    raw_plan = prepare_plan(root, "input", secret=SECRET, protocol=parse_protocol(protocol_data))
    plan_data, criteria_data = sign_plan(raw_plan, secret=SECRET), canonical_json(criteria(task))
    context = load_input(root, "input", secret=SECRET, plan_data=plan_data, protocol_data=protocol_data, criteria_data=criteria_data)
    return context, package, protocol_data, plan_data, criteria_data


def prediction(context, package, candidate, phase="selection"):
    # Values are intentionally perfect/constant hand-authored fixtures, not fitted models.
    targets = {row["row_key"]: row["target"] for row in map(json.loads, dict(package.files)["targets.jsonl"].splitlines())}
    artifacts = {name: "a"*64 for name in ARTIFACT_FIELDS}
    artifacts.update(calibrator_sha256=None, calibration_rows_sha256=None,
                     training_rows_sha256=None if candidate == "ml02_rules" else rowset_sha(context.plan["partitions"]["train"]))
    rows = []
    for key in context.plan["partitions"][phase]:
        value = targets[key]
        if candidate == "train_prevalence":
            value = 0.5
        elif candidate == "ml02_rules":
            value = None  # Generic textual rules require domain review in this fixture.
        elif context.plan["task"] == "p2":
            value = 0.8 if value else 0.2
        rows.append({"row_key": key, "prediction": value})
    return {"version": VERSION, "task": context.plan["task"], "package_id": context.plan["package_id"],
            "plan_id": context.plan["plan_id"], "phase": phase, "candidate_id": candidate, "artifacts": artifacts, "rows": rows}


def candidates(context, package, phase="selection"):
    return [parse_predictions(canonical_json(prediction(context, package, candidate, phase)), context, phase=phase)
            for candidate in context.plan["comparison"]["candidate_ids"]]


def test_known_binary_metrics_ties_abstention_and_single_class():
    result = summarize("p2", [0, 1], [0.2, 0.8], classes=(0, 1), bins=10)
    assert result["brier"] == pytest.approx(0.04) and result["auroc"] == 1 and result["average_precision"] == 1
    assert result["ece"] == pytest.approx(0.2)
    ties = summarize("p2", [0, 1], [0.5, 0.5], classes=(0, 1), bins=10)
    assert ties["auroc"] == 0.5 and ties["average_precision"] == 0.5
    ranked = summarize("p2", [0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8], classes=(0, 1), bins=10)
    assert ranked["auroc"] == 0.75 and ranked["average_precision"] == pytest.approx(5/6)
    assert ranked["brier"] == pytest.approx(0.158125)
    partial = summarize("p2", [0, 1], [None, 0.8], classes=(0, 1), bins=10)
    assert partial["coverage"] == 0.5 and partial["auroc"] is None
    assert summarize("p2", [0, 1], [None, None], classes=(0, 1), bins=10)["brier"] is None


def test_macro_f1_counts_abstention_as_false_negative_not_missing_row():
    result = summarize("p1", ["FUNDS", "EXPIRED"], ["FUNDS", None], classes=("FUNDS", "EXPIRED"), bins=10)
    assert result["primary"] == 0.5 and result["coverage"] == 0.5
    assert result["per_class"]["EXPIRED"]["recall"] == 0 and result["per_class"]["EXPIRED"]["precision"] is None
    assert summarize("p1", ["FUNDS"], ["FUNDS"], classes=("FUNDS", "EXPIRED"), bins=10)["primary"] is None


def test_paired_cluster_intervals_reproducible_missing_units_and_support():
    args = ("p2", [0, 1]*8, [0.5]*16, [0.2, 0.8]*8, [str(i//2) for i in range(16)])
    settings = dict(classes=(0, 1), repetitions=200, seed=17, minimum_units=2)
    first = paired_interval(*args, **settings)
    assert first == paired_interval(*args, **settings)
    assert first["lower"] == pytest.approx(0.21) and first["upper"] == pytest.approx(0.21)
    assert paired_interval(*args[:-1], [None]*16, **settings)["lower"] is None
    assert paired_interval(*args, **(settings | {"minimum_units": 99}))["reason"] == "insufficient_units_or_resampling_budget"


@pytest.mark.parametrize("task", ["p1", "p2"])
def test_selection_reports_same_cohort_metrics_by_source_no_test_or_winner(private, task):
    context, package, *_ = setup_study(private, task)
    report = evaluate(context, candidates(context, package), phase="selection")
    assert report["winner"] is None and report["activation_authorized"] is False and report["training_executed"] is False
    assert "test" not in report["label_partitions_opened"]
    candidate = context.plan["comparison"]["candidate_ids"][1]
    assert report["candidates"][candidate]["eligible_for_manual_freeze"]
    assert len(report["candidates"][candidate]["metrics"]) == 2


def test_selective_reader_does_not_decode_unopened_test_values():
    train, test = "a"*64, "b"*64
    data = canonical_json({"row_key": train, "target": 1}) + b'{"row_key":"' + test.encode() + b'","target":DO_NOT_DECODE}\n'
    assert selective_records(data, selected={train}, all_keys={train, test}, kind="targets") == {train: 1}
    with pytest.raises(ValueError):
        selective_records(data, selected={test}, all_keys={train, test}, kind="targets")


@pytest.mark.parametrize("mutation", [
    lambda p: p["rows"].pop(), lambda p: p["rows"].append(p["rows"][0]),
    lambda p: p["rows"][0].update(prediction=True), lambda p: p["rows"][0].update(prediction=1.1),
    lambda p: p.update(plan_id="f"*64), lambda p: p.update(phase="test"),
    lambda p: p["artifacts"].update(training_rows_sha256="f"*64),
    lambda p: p.update(model_path="untrusted.pkl"),
])
def test_predictions_reject_wrong_rows_values_provenance_and_executable_paths(private, mutation):
    context, package, *_ = setup_study(private)
    value = prediction(context, package, "logistic")
    mutation(value)
    with pytest.raises(ValueError):
        parse_predictions(canonical_json(value), context, phase="selection")


def test_test_requires_preclaimed_authenticated_opening_and_reference_is_audited(private):
    context, package, *_ = setup_study(private)
    with pytest.raises(ValueError, match="apertura"):
        evaluate(context, candidates(context, package, "test"), phase="test")
    values = candidates(context, package)
    baseline = values[0]
    baseline["predictions"] = dict.fromkeys(baseline["predictions"], 0.9)
    with pytest.raises(ValueError, match="prevalencia"):
        evaluate(context, values, phase="selection")


def test_small_support_is_inconclusive_even_with_perfect_synthetic_predictions(private):
    context, package, protocol, plan, settings = setup_study(private)
    changed = json.loads(settings) | {"minimum_class_rows": 99}
    context = load_input(private, "input", secret=SECRET, plan_data=plan, protocol_data=protocol, criteria_data=canonical_json(changed))
    result = evaluate(context, candidates(context, package), phase="selection")
    assert not any(record["eligible_for_manual_freeze"] for record in result["candidates"].values())


@pytest.mark.parametrize("fail_after_open", [False, True])
def test_cli_freeze_and_single_opening_keeps_receipt_after_repeated_attempt(private, monkeypatch, capsys, fail_after_open):
    root = private.parent
    (root / ".local").mkdir()
    store = root / ".local/ml-private"
    context, package, protocol, plan, settings = setup_study(store)
    export_files.generate_key(store, "keys/export.key")
    (store / "keys/export.key").write_bytes(SECRET)
    for name, data in (("protocol.json", protocol), ("plan.json", plan), ("criteria.json", settings), ("approval.txt", b"synthetic-only approval")):
        export_files.write_private_document(store, name, data)
    for phase in ("selection", "test"):
        for candidate in context.plan["comparison"]["candidate_ids"]:
            export_files.write_private_document(store, f"predictions/{phase}-{candidate}.json", canonical_json(prediction(context, package, candidate, phase)))
    monkeypatch.setattr(evaluate_models, "ROOT", root)
    monkeypatch.setattr(evaluate_models, "source_fingerprint", lambda root: "a"*64)
    (root / "scripts/ml").mkdir(parents=True)
    (root / "scripts/ml/evaluate_models.py").write_bytes(b"synthetic runner")
    (root / "requirements.lock").write_bytes(b"synthetic-lock")
    monkeypatch.setattr(evaluate_models.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=b"e"*40 if "rev-parse" in args[0] else b""))
    common = ["--bundle", "input", "--plan", "plan.json", "--protocol", "protocol.json", "--criteria", "criteria.json"]
    selection = ["selection", *common, "--destination", "reports/selection.json"]
    for candidate in context.plan["comparison"]["candidate_ids"]:
        selection += ["--prediction", f"predictions/selection-{candidate}.json"]
    assert evaluate_models.main(selection) == 0
    assert evaluate_models.main(["freeze", *common, "--destination", "freezes/model.json", "--selection-report", "reports/selection.json", "--candidate", "logistic", "--approval-reference", "approval.txt"]) == 0
    final = ["test", *common, "--destination", "reports/test.json", "--freeze", "freezes/model.json",
             "--prediction", "predictions/test-train_prevalence.json", "--prediction", "predictions/test-logistic.json"]
    assert evaluate_models.main(final) == 2  # No explicit opening flag.
    assert not (store / "receipts").exists()
    path = store / "predictions/test-logistic.json"
    original = path.read_bytes()
    altered = json.loads(original)
    altered["artifacts"]["pipeline_sha256"] = "f"*64
    path.write_bytes(canonical_json(altered))
    assert evaluate_models.main([*final, "--open-test"]) == 2
    assert not (store / "receipts").exists()
    path.write_bytes(original)
    if fail_after_open:
        def fail(*args, **kwargs):
            raise ValueError("synthetic failure after receipt")
        monkeypatch.setattr(evaluate_models, "evaluate", fail)
    assert evaluate_models.main([*final, "--open-test"]) == (2 if fail_after_open else 0)
    if not fail_after_open:
        report = json.loads((store / "reports/test.json").read_bytes())
        assert "meets_frozen_checks" in report["candidates"]["logistic"]
        assert "eligible_for_manual_freeze" not in report["candidates"]["logistic"]
        assert report["freeze_id"] and report["test_opening_receipt_id"]
    def never_read_again(*args, **kwargs):
        raise AssertionError("test scoring must not be called after opening")
    monkeypatch.setattr(evaluate_models, "evaluate", never_read_again)
    replay = list(final)
    replay[replay.index("reports/test.json")] = "reports/repeated-test.json"
    assert evaluate_models.main([*replay, "--open-test"]) == 2
    receipt = store / f"receipts/{context.plan['package_id']}/test.json"
    assert receipt.exists()
    output = capsys.readouterr()
    assert "1000" not in output.out and "Traceback" not in output.err


def test_no_imported_training_or_database_runtime():
    code = "import sys; from scripts.ml import evaluate_models; assert not any(n in sys.modules for n in ('sklearn','pandas','joblib','app.db.session','app.core.config')); print('offline')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
    assert result.stdout.strip() == b"offline"
