"""Synthetic descriptors/bytes only; never fit or load model artifacts."""

import copy
import hashlib
import math
import subprocess
import sys

import pytest

from app.ml import export_files, pipelines
from app.ml.artifacts import prepare_artifact, verify_artifact
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_signing import seal, unseal
from app.ml.pipelines import build_pipeline, feature_matrix, recipe
from scripts.ml.prepare_artifacts import template

SECRET = b"synthetic-test-only-key-32-bytes"


def fixture_artifact(root, *, serial=1, source="virtualpos1", candidate="logistic"):
    descriptor = template(candidate, source)
    data = canonical_json({"fixture_version": "ml08-v1", "untrained": True, "serial": serial})
    export_files.write_private_document(root, f"payload-{serial}.json", data)
    descriptor.update(provenance_reviewed=True, training_status="fixture", package_id="a"*64, plan_id="b"*64,
                      training_rows_sha256="c"*64, fit_code_sha256="d"*64, pipeline_sha256="e"*64, decision_policy_sha256="f"*64,
                      payload={"path": f"payload-{serial}.json", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "format": "fixture-json"})
    relative = f"artifact-{serial}.json"
    encoded = prepare_artifact(root, relative, descriptor, secret=SECRET)
    export_files.write_private_document(root, relative, encoded)
    return verify_artifact(root, relative, secret=SECRET)


@pytest.fixture
def private(tmp_path, monkeypatch):
    # Native permissions have separate tests and CLI smoke.
    monkeypatch.setattr(export_files, "_permissions", lambda *a, **k: None)
    return tmp_path / "private"


def test_recipes_and_whitelist_do_not_learn_or_accept_ids():
    row = {"source": "virtualpos1", "amount": "1000", "currency": "CLP", "elapsed_days": 1, "days_from_due": None}
    matrix = feature_matrix("p2", [row])
    assert matrix[0][:4] == ["virtualpos1", 1000.0, "CLP", 1.0] and math.isnan(matrix[0][4])
    assert recipe("char_tfidf_logistic")["task"] == "p1" and recipe("logistic")["task"] == "p2"
    assert not recipe("hist_gradient_boosting")["hidden_validation"]
    with pytest.raises(ValueError):
        feature_matrix("p2", [row | {"rut": "synthetic-person"}])
    for bad in (row | {"currency": "USD"}, row | {"amount": 1000.0}, row | {"elapsed_days": True}, row | {"elapsed_days": 30}):
        with pytest.raises(ValueError):
            feature_matrix("p2", [bad])


def test_fixture_manifest_is_signed_compatible_and_not_real(private):
    artifact = fixture_artifact(private)
    assert artifact.compatible and not artifact.evaluation_verified
    assert artifact.descriptor["training_status"] == "fixture"
    encoded = (private / "artifact-1.json").read_bytes()
    assert SECRET not in encoded
    with pytest.raises(ValueError):
        verify_artifact(private, "artifact-1.json", secret=b"x"*32)
    (private / "payload-1.json").write_bytes(b"altered")
    with pytest.raises(ValueError, match="alterado"):
        verify_artifact(private, "artifact-1.json", secret=SECRET)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(provenance_reviewed=False), lambda d: d.update(source="virtualpos"),
    lambda d: d.update(task="p1"), lambda d: d.update(recipe_sha256="0"*64),
    lambda d: d["payload"].update(format="pickle"), lambda d: d["payload"].update(path="../outside"),
    lambda d: d.update(purpose="reviewed-real", training_status="externally-trained"),
    lambda d: d.update(calibrator_sha256="0"*64), lambda d: d.update(fit_environment_sha256="0"*64),
])
def test_unsafe_or_mismatched_descriptors_fail_before_publication(private, mutation):
    original = fixture_artifact(private)
    descriptor = copy.deepcopy(original.descriptor)
    descriptor.pop("artifact_id")
    mutation(descriptor)
    with pytest.raises(ValueError):
        prepare_artifact(private, "rejected.json", descriptor, secret=SECRET)
    assert not (private / "rejected.json").exists()


def test_environment_mismatch_is_not_silently_compatible(private):
    original = fixture_artifact(private)
    descriptor = copy.deepcopy(original.descriptor)
    descriptor.pop("artifact_id")
    descriptor["environment"]["python"] = "0.0.0"
    descriptor["fit_environment_sha256"] = hashlib.sha256(canonical_json(descriptor["environment"])).hexdigest()
    encoded = prepare_artifact(private, "other.json", descriptor, secret=SECRET)
    export_files.write_private_document(private, "other.json", encoded)
    assert not verify_artifact(private, "other.json", secret=SECRET).compatible


def test_evidence_requires_matching_report_freeze_payload_and_receipt(private):
    artifact = fixture_artifact(private)
    descriptor = copy.deepcopy(artifact.descriptor)
    descriptor.pop("artifact_id")
    candidate = descriptor["candidate_id"]
    identity = {name: descriptor[name] for name in ("training_rows_sha256", "calibration_rows_sha256", "calibrator_sha256", "fit_code_sha256", "fit_environment_sha256", "pipeline_sha256", "decision_policy_sha256")}
    identity["model_sha256"] = descriptor["payload"]["sha256"]
    frozen = {"version": "frozen-evaluation-v1", "package_id": descriptor["package_id"], "plan_id": descriptor["plan_id"],
              "candidate_id": candidate, "artifacts": {candidate: identity}, "criteria_sha256": "0"*64}
    encoded = seal(frozen, secret=SECRET, domain="model-freeze-v1", id_field="freeze_id")
    export_files.write_private_document(private, "freeze.json", encoded)
    freeze_id = unseal(encoded, secret=SECRET, domain="model-freeze-v1", id_field="freeze_id")["freeze_id"]
    receipt = {"package_id": descriptor["package_id"], "plan_id": descriptor["plan_id"], "freeze_id": freeze_id,
               "prediction_sha256s": {candidate: "9"*64}}
    encoded = seal(receipt, secret=SECRET, domain="test-opening-v1", id_field="receipt_id")
    export_files.write_private_document(private, f"receipts/{descriptor['package_id']}/test.json", encoded)
    receipt_id = unseal(encoded, secret=SECRET, domain="test-opening-v1", id_field="receipt_id")["receipt_id"]
    report = {"version": "frozen-evaluation-v1", "package_id": descriptor["package_id"], "plan_id": descriptor["plan_id"],
              "purpose": "synthetic", "phase": "test", "freeze_id": freeze_id, "test_opening_receipt_id": receipt_id,
              "criteria_sha256": "0"*64, "candidates": {candidate: {"artifacts": identity, "meets_frozen_checks": True,
                                                                  "metrics": {descriptor["source"]: {}}, "prediction_sha256": "9"*64}}}
    export_files.write_private_document(private, "test.json", seal(report, secret=SECRET, domain="evaluation-report-v1", id_field="report_id"))
    descriptor["evaluation"] = {"test_report": "test.json", "freeze": "freeze.json"}
    encoded = prepare_artifact(private, "reviewed.json", descriptor, secret=SECRET)
    export_files.write_private_document(private, "reviewed.json", encoded)
    assert verify_artifact(private, "reviewed.json", secret=SECRET).evaluation_verified
    descriptor["decision_policy_sha256"] = "8"*64
    with pytest.raises(ValueError):
        prepare_artifact(private, "wrong.json", descriptor, secret=SECRET)


def test_crm_imports_and_build_guard_do_not_load_ml_runtime(monkeypatch):
    monkeypatch.setattr(pipelines, "environment", lambda: {"packages": {}})
    with pytest.raises(ValueError):
        build_pipeline("logistic")
    code = "import sys; from app.ml import pipelines, artifacts; assert not any(n in sys.modules for n in ('sklearn','skops','app.db.session','app.core.config')); print('offline')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
    assert result.stdout.strip() == b"offline"
