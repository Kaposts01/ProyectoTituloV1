"""Private artifact descriptors, opaque payload verification and ML-07 evidence binding.

Never calls pickle/joblib/skops load. A digest/signature is not proof of safe provenance.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import token
from app.ml.evaluation_signing import seal, unseal
from app.ml.export_files import read_private_file
from app.ml.export_snapshot import exact, parse_json
from app.ml.model_evaluation import VERSION as EVALUATION_VERSION
from app.ml.pipelines import PACKAGES, PIPELINE_VERSION, TASKS, environment, recipe
from app.ml.temporal_dataset import SOURCES

ARTIFACT_VERSION = "rejection-artifact-v1"


@dataclass(frozen=True)
class VerifiedArtifact:
    artifact_id: str
    manifest_relative: str = field(repr=False)
    manifest_sha256: str
    descriptor: dict = field(repr=False)
    evaluation_verified: bool
    compatible: bool


def verify_artifact(root: Path, relative: str, *, secret: bytes) -> VerifiedArtifact:
    encoded = read_private_file(root, relative, max_bytes=128_000)
    return _verify_encoded(root, relative, encoded, secret=secret)


def prepare_artifact(root: Path, relative: str, descriptor: dict, *, secret: bytes) -> bytes:
    """Verify reviewed descriptor/payload/evidence before publishing the signed manifest."""
    encoded = seal(descriptor, secret=secret, domain="ml-artifact-v1", id_field="artifact_id")
    if len(encoded) > 128_000:
        raise ValueError("Manifiesto demasiado grande")
    _verify_encoded(root, relative, encoded, secret=secret)
    return encoded


def _verify_encoded(root: Path, relative: str, encoded: bytes, *, secret: bytes) -> VerifiedArtifact:
    if len(relative) > 255:
        raise ValueError("Referencia de manifiesto demasiado larga")
    record = unseal(encoded, secret=secret, domain="ml-artifact-v1", id_field="artifact_id")
    exact(record, {"artifact_id", "version", "task", "source", "candidate_id", "purpose", "training_status",
                   "provenance_reviewed", "pipeline_version", "feature_schema_sha256", "seed", "recipe_sha256", "environment",
                   "package_id", "plan_id", "training_rows_sha256", "calibration_rows_sha256", "calibrator_sha256", "fit_code_sha256",
                   "fit_environment_sha256", "pipeline_sha256", "decision_policy_sha256", "payload", "evaluation"})
    if (record["version"] != ARTIFACT_VERSION or record["candidate_id"] not in TASKS
            or record["task"] != TASKS[record["candidate_id"]] or record["source"] not in SOURCES
            or record["pipeline_version"] != PIPELINE_VERSION or record["provenance_reviewed"] is not True
            or record["feature_schema_sha256"] != recipe(record["candidate_id"])["schema_sha256"]):
        raise ValueError("Contrato de artefacto incompatible")
    definition = recipe(record["candidate_id"], seed=record["seed"])
    if record["recipe_sha256"] != hashlib.sha256(canonical_json(definition)).hexdigest():
        raise ValueError("Receta no corresponde al pipeline declarado")
    if record["purpose"] not in {"synthetic", "reviewed-real"} or record["training_status"] not in {"fixture", "unfitted", "externally-trained"}:
        raise ValueError("Estado de artefacto invalido")
    if record["purpose"] == "reviewed-real" and record["training_status"] != "externally-trained":
        raise ValueError("Un artefacto real debe tener entrenamiento externo declarado")
    for name in ("package_id", "plan_id", "training_rows_sha256", "fit_code_sha256", "fit_environment_sha256", "pipeline_sha256", "decision_policy_sha256"):
        token(record[name])
    if record["calibration_rows_sha256"] is not None:
        token(record["calibration_rows_sha256"])
    if record["calibrator_sha256"] is not None:
        token(record["calibrator_sha256"])
    if (record["calibrator_sha256"] is None) != (record["calibration_rows_sha256"] is None):
        raise ValueError("Calibracion contradictoria")
    runtime = exact(record["environment"], {"python", "implementation", "system", "machine", "packages"})
    exact(runtime["packages"], set(PACKAGES))
    if any(not isinstance(runtime[name], str) or len(runtime[name]) > 64 for name in ("python", "implementation", "system", "machine")):
        raise ValueError("Entorno invalido")
    if any(value is not None and (not isinstance(value, str) or len(value) > 32) for value in runtime["packages"].values()):
        raise ValueError("Versiones de entorno invalidas")
    if record["fit_environment_sha256"] != hashlib.sha256(canonical_json(runtime)).hexdigest():
        raise ValueError("Entorno de ajuste no corresponde a su huella")
    payload = exact(record["payload"], {"path", "sha256", "bytes", "format"})
    token(payload["sha256"])
    if type(payload["bytes"]) is not int or not 0 < payload["bytes"] <= 64*1024*1024:
        raise ValueError("Tamano de artefacto invalido")
    if payload["format"] not in {"fixture-json", "skops"}:
        raise ValueError("Serializacion no admitida; no usar pickle/joblib")
    data = read_private_file(root, payload["path"], max_bytes=64*1024*1024)
    if len(data) != payload["bytes"] or hashlib.sha256(data).hexdigest() != payload["sha256"]:
        raise ValueError("Artefacto alterado")
    if payload["format"] == "fixture-json":
        if record["purpose"] != "synthetic" or record["training_status"] != "fixture":
            raise ValueError("Fixture no puede presentarse como modelo real")
        fixture = exact(parse_json(data), {"fixture_version", "untrained", "serial"})
        if fixture["fixture_version"] != "ml08-v1" or fixture["untrained"] is not True or type(fixture["serial"]) is not int or not 1 <= fixture["serial"] <= 1000:
            raise ValueError("Fixture invalido")
    else:
        # Bound archive expansion before non-executing type inspection; never load the model.
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if (len(members) > 10_000 or sum(info.file_size for info in members) > 128*1024*1024
                    or any(info.filename.startswith(("/", "\\")) or ".." in info.filename.replace("\\", "/").split("/") for info in members)):
                raise ValueError("Archivo de artefacto no admitido")
        try:
            from skops.io import get_untrusted_types
        except ImportError:
            raise ValueError("Inspeccione skops en el entorno experimental bloqueado") from None
        if get_untrusted_types(data=data):
            raise ValueError("Tipos no confiables; no se autorizan automaticamente")
    evaluation_verified = False
    if record["evaluation"] is not None:
        references = exact(record["evaluation"], {"test_report", "freeze"})
        report = unseal(read_private_file(root, references["test_report"], max_bytes=8*1024*1024), secret=secret,
                        domain="evaluation-report-v1", id_field="report_id")
        frozen = unseal(read_private_file(root, references["freeze"], max_bytes=128_000), secret=secret,
                        domain="model-freeze-v1", id_field="freeze_id")
        candidate = record["candidate_id"]
        if (report["version"] != EVALUATION_VERSION or frozen["version"] != EVALUATION_VERSION
                or report["criteria_sha256"] != frozen["criteria_sha256"]
                or report["phase"] != "test" or report["purpose"] != record["purpose"] or report["freeze_id"] != frozen["freeze_id"]
                or frozen["candidate_id"] != candidate or candidate not in report["candidates"]
                or report["candidates"][candidate]["meets_frozen_checks"] is not True
                or record["source"] not in report["candidates"][candidate]["metrics"]):
            raise ValueError("Evidencia de evaluacion no apta")
        for evidence in (report, frozen):
            if evidence["package_id"] != record["package_id"] or evidence["plan_id"] != record["plan_id"]:
                raise ValueError("Evaluacion de otro dataset/plan")
        identity = report["candidates"][candidate]["artifacts"]
        if identity != frozen["artifacts"][candidate]:
            raise ValueError("Identidad congelada contradictoria")
        for name in ("training_rows_sha256", "calibration_rows_sha256", "calibrator_sha256", "fit_code_sha256", "fit_environment_sha256", "pipeline_sha256", "decision_policy_sha256"):
            if record[name] != identity[name]:
                raise ValueError("Procedencia no corresponde al modelo evaluado")
        if payload["sha256"] != identity["model_sha256"]:
            raise ValueError("Bytes no corresponden al modelo evaluado")
        receipt = unseal(read_private_file(root, f"receipts/{record['package_id']}/test.json", max_bytes=128_000),
                         secret=secret, domain="test-opening-v1", id_field="receipt_id")
        if (receipt["receipt_id"] != report["test_opening_receipt_id"] or receipt["freeze_id"] != frozen["freeze_id"]
                or receipt["package_id"] != record["package_id"] or receipt["plan_id"] != record["plan_id"]
                or receipt["prediction_sha256s"][candidate] != report["candidates"][candidate]["prediction_sha256"]):
            raise ValueError("Registro de apertura no corresponde a la evaluacion")
        evaluation_verified = True
    return VerifiedArtifact(record["artifact_id"], relative, hashlib.sha256(encoded).hexdigest(), record,
                            evaluation_verified, runtime == environment())
