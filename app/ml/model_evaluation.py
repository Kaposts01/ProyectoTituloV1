"""ML-07: evaluate externally frozen predictions. Never loads or fits a model."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.ml.annotation_contract import AnnotationContext
from app.ml.dataset_export import MAX_PACKAGE_BYTES, canonical_json
from app.ml.evaluation_metrics import paired_interval, summarize
from app.ml.evaluation_package import prepare_plan
from app.ml.evaluation_protocol import PROTOCOL_VERSION, parse_protocol, token
from app.ml.evaluation_signing import unseal
from app.ml.export_files import read_private_file, verify_bundle
from app.ml.export_snapshot import MAX_RECORDS, exact, parse_json
from app.ml.taxonomy import Category, ClassificationState, classify_rejection

VERSION = "frozen-evaluation-v1"
ARTIFACT_FIELDS = {"model_sha256", "pipeline_sha256", "calibrator_sha256", "decision_policy_sha256",
                   "training_rows_sha256", "calibration_rows_sha256", "fit_code_sha256", "fit_environment_sha256"}


def rowset_sha(keys) -> str:
    return hashlib.sha256(canonical_json(sorted(keys))).hexdigest()


def parse_criteria(data: bytes, plan: dict) -> dict:
    value = exact(parse_json(data), {"version", "agreement_sha256", "classes", "minimum_class_rows",
                                   "minimum_independent_units", "bootstrap_repetitions", "calibration_bins",
                                   "uncertainty_unit", "comparison_rule"})
    if value["version"] != VERSION or value["agreement_sha256"] != plan["criteria"]["reference_sha256"]:
        raise ValueError("Criterios no vinculados al acuerdo del plan")
    classes = value["classes"]
    if (type(classes) is not list or len(classes) < 2 or len(set(classes)) != len(classes)
            or (plan["task"] == "p1" and any(c not in {category.value for category in Category} for c in classes))
            or (plan["task"] == "p2" and (any(type(c) is not int for c in classes) or sorted(classes) != [0, 1]))):
        raise ValueError("Clases predeclaradas invalidas")
    for name, low, high in (("minimum_class_rows", 1, 100_000), ("minimum_independent_units", 2, 100_000),
                            ("bootstrap_repetitions", 200, 2000), ("calibration_bins", 2, 20)):
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError("Limite estadistico invalido")
    units = {"context", "time_week"} if plan["task"] == "p1" else {"subscription", "time_week"}
    if value["uncertainty_unit"] not in units or value["comparison_rule"] not in {"non_inferiority", "practical_superiority"}:
        raise ValueError("Politica estadistica incompatible")
    return value


@dataclass(frozen=True)
class EvaluationInput:
    root: Path = field(repr=False)
    bundle: str = field(repr=False)
    secret: bytes = field(repr=False)
    plan: dict = field(repr=False)
    manifest: dict = field(repr=False)
    criteria: dict
    criteria_sha256: str
    metadata: dict = field(repr=False)

    def payload(self, name: str) -> bytes:
        data = read_private_file(self.root, f"{self.bundle}/{name}", max_bytes=MAX_PACKAGE_BYTES)
        if hashlib.sha256(data).hexdigest() != self.manifest["files"][name]["sha256"]:
            raise ValueError("Paquete alterado durante evaluacion")
        return data


def load_input(root: Path, bundle: str, *, secret: bytes, plan_data: bytes,
               protocol_data: bytes, criteria_data: bytes) -> EvaluationInput:
    plan = unseal(plan_data, secret=secret, domain="evaluation-plan-v1", id_field="plan_id")
    if plan.get("protocol_version") != PROTOCOL_VERSION or plan.get("status") != "structural_preflight_passed":
        raise ValueError("Plan no apto")
    protocol = parse_protocol(protocol_data)
    current = prepare_plan(root, bundle, secret=secret, protocol=protocol)
    if canonical_json({key: plan.get(key) for key in current}) != canonical_json(current):
        raise ValueError("Plan, protocolo y paquete no corresponden")
    verified = verify_bundle(root, bundle, secret=secret, include_manifest=True)
    if verified["package_id"] != plan["package_id"]:
        raise ValueError("Paquete cambio durante comprobacion del plan")
    criteria = parse_criteria(criteria_data, plan)
    context = EvaluationInput(root, bundle, secret, plan, verified["manifest"], criteria,
                              hashlib.sha256(criteria_data).hexdigest(), {})
    rows = [parse_json(line) for line in context.payload("metadata.jsonl").splitlines()]
    metadata = {row["row_key"]: row for row in rows}
    if len(metadata) != len(rows) or len(rows) != context.manifest["rows"]:
        raise ValueError("Metadatos duplicados o incompletos")
    return EvaluationInput(root, bundle, secret, plan, context.manifest, criteria, context.criteria_sha256, metadata)


def parse_predictions(data: bytes, context: EvaluationInput, *, phase: str) -> dict:
    value = exact(parse_json(data), {"version", "task", "package_id", "plan_id", "phase", "candidate_id", "artifacts", "rows"})
    if (value["version"] != VERSION or value["task"] != context.plan["task"] or value["phase"] != phase
            or value["package_id"] != context.plan["package_id"] or value["plan_id"] != context.plan["plan_id"]
            or value["candidate_id"] not in context.plan["comparison"]["candidate_ids"]):
        raise ValueError("Predicciones incompatibles")
    artifacts = exact(value["artifacts"], ARTIFACT_FIELDS)
    for name, digest in artifacts.items():
        if digest is not None:
            token(digest)
        elif name not in {"calibrator_sha256", "calibration_rows_sha256", "training_rows_sha256"}:
            raise ValueError("Procedencia de modelo incompleta")
    rules = value["candidate_id"] == "ml02_rules"
    if value["candidate_id"] in {"ml02_rules", "train_prevalence"} and artifacts["calibrator_sha256"] is not None:
        raise ValueError("La referencia no usa calibrador")
    train_hash = rowset_sha(context.plan["partitions"]["train"])
    if artifacts["training_rows_sha256"] != (None if rules else train_hash):
        raise ValueError("El modelo no declara las filas de entrenamiento previstas")
    if artifacts["calibrator_sha256"] is None:
        if artifacts["calibration_rows_sha256"] is not None:
            raise ValueError("Calibracion contradictoria")
    elif rules or artifacts["calibration_rows_sha256"] != rowset_sha(context.plan["partitions"]["calibration"]):
        raise ValueError("Calibracion fuera de su particion")
    records = value["rows"]
    if type(records) is not list or len(records) > MAX_RECORDS:
        raise ValueError("Predicciones demasiado grandes")
    predictions = {}
    for row in records:
        exact(row, {"row_key", "prediction"})
        key, prediction = token(row["row_key"]), row["prediction"]
        if key in predictions:
            raise ValueError("Prediccion duplicada")
        if prediction is not None:
            if context.plan["task"] == "p1":
                if prediction not in context.criteria["classes"]:
                    raise ValueError("Clase no predeclarada")
            elif type(prediction) not in {int, float} or not math.isfinite(prediction) or not 0 <= prediction <= 1:
                raise ValueError("Probabilidad invalida")
        predictions[key] = prediction
    if set(predictions) != set(context.plan["partitions"][phase]):
        raise ValueError("Faltan filas; una abstencion debe ser null explicito")
    return {"candidate_id": value["candidate_id"], "artifacts": artifacts, "predictions": predictions,
            "input_sha256": hashlib.sha256(data).hexdigest()}


def selective_records(data: bytes, *, selected: set[str], all_keys: set[str], kind: str) -> dict:
    """Inspect canonical row headers only outside selected partitions; never parse their targets."""
    result, seen = {}, set()
    pattern = rb'^\{"row_key":"([a-f0-9]{64})","target":' if kind == "targets" else rb',"row_key":"([a-f0-9]{64})"\}$'
    for line in data.splitlines():
        match = re.search(pattern, line)
        if not match:
            raise ValueError("Formato de fila no compatible con lectura selectiva")
        key = match.group(1).decode("ascii")
        if key in seen:
            raise ValueError("Fila duplicada")
        seen.add(key)
        if key in selected:
            row = exact(parse_json(line), {"row_key", "target" if kind == "targets" else "features"})
            result[key] = row["target" if kind == "targets" else "features"]
    if seen != all_keys or set(result) != selected:
        raise ValueError("Filas de archivos no alineadas")
    return result


def evaluate(context: EvaluationInput, candidates: list[dict], *, phase: str, test_receipt: bytes | None = None) -> dict:
    """Caller must claim the test opening before invoking this for test labels."""
    if phase not in {"selection", "test"}:
        raise ValueError("Solo seleccion o test")
    if phase == "test":
        if test_receipt is None:
            raise ValueError("Test requiere registro previo de apertura")
        receipt = unseal(test_receipt, secret=context.secret, domain="test-opening-v1", id_field="receipt_id")
        if (receipt["package_id"] != context.plan["package_id"] or receipt["plan_id"] != context.plan["plan_id"]
                or receipt["prediction_sha256s"] != {c["candidate_id"]: c["input_sha256"] for c in candidates}):
            raise ValueError("Apertura no corresponde a estas predicciones")
    keys = context.plan["partitions"][phase]
    expected = set(context.plan["comparison"]["candidate_ids"])
    supplied = {c["candidate_id"] for c in candidates}
    if len(supplied) != len(candidates) or (phase == "selection" and supplied != expected):
        raise ValueError("Comparadores incompletos o duplicados")
    baseline_id = context.plan["comparison"]["candidate_ids"][0]
    if baseline_id not in supplied:
        raise ValueError("Falta referencia")
    selected = set(keys) | (set(context.plan["partitions"]["train"]) if context.plan["task"] == "p2" else set())
    targets = selective_records(context.payload("targets.jsonl"), selected=selected, all_keys=set(context.metadata), kind="targets")
    classes = tuple(context.criteria["classes"])
    if any(value not in classes or (context.plan["task"] == "p2" and type(value) is not int) for value in targets.values()):
        raise ValueError("Etiqueta fuera de clases predeclaradas")
    by_id = {c["candidate_id"]: c for c in candidates}
    baseline = by_id[baseline_id]["predictions"]
    if context.plan["task"] == "p2":
        train = context.plan["partitions"]["train"]
        prevalence = sum(targets[key] for key in train)/len(train)
        if any(value is None or abs(value-prevalence) > 1e-12 for value in baseline.values()):
            raise ValueError("Referencia de prevalencia no corresponde solo a entrenamiento")
    else:
        features = selective_records(context.payload("features.jsonl"), selected=set(keys), all_keys=set(context.metadata), kind="features")
        for key in keys:
            row, meta = features[key], context.metadata[key]
            evidence = AnnotationContext(**row, normalization_version=meta["normalization_version"],
                                         taxonomy_version=meta["taxonomy_version"], privacy_reviewed=True)
            reference = classify_rejection(evidence.source, evidence.code or None, evidence.normalized_text or None)
            expected_label = reference.category.value if (reference.state == ClassificationState.CLASSIFIED
                                                          and not reference.review_required and reference.category) else None
            if baseline[key] != expected_label:
                raise ValueError("Referencia no corresponde a reglas ML-02 vigentes")
    unit = context.criteria["uncertainty_unit"]

    def group(key):
        meta = context.metadata[key]
        if unit == "time_week":
            clock = datetime.fromisoformat(meta["calculated_at"].replace("Z", "+00:00"))
            return f"{clock.isocalendar().year}-{clock.isocalendar().week}"
        return meta["context_group" if unit == "context" else "subscription_group"]

    reports = {}
    for candidate in candidates:
        candidate_id, predicted = candidate["candidate_id"], candidate["predictions"]
        slices = {"all": keys, **{source: [key for key in keys if context.metadata[key]["source"] == source]
                                  for source in context.plan["expected_sources"]}}
        summaries, intervals, adequate = {}, {}, True
        for name, cohort in slices.items():
            labels, values = [targets[key] for key in cohort], [predicted[key] for key in cohort]
            summaries[name] = summarize(context.plan["task"], labels, values, classes=classes, bins=context.criteria["calibration_bins"])
            support = Counter(labels)
            ok = all(support[c] >= context.criteria["minimum_class_rows"] for c in classes)
            ok &= summaries[name]["coverage"] >= float(context.plan["criteria"]["minimum_prediction_coverage"])
            units = [group(key) for key in cohort]
            ok &= all(value is not None for value in units) and len(set(units)) >= context.criteria["minimum_independent_units"]
            if context.plan["task"] == "p2":
                common_support = Counter(y for y, value in zip(labels, values, strict=True) if value is not None)
                ok &= all(common_support[c] >= context.criteria["minimum_class_rows"] for c in classes)
            if candidate_id != baseline_id:
                interval = paired_interval(context.plan["task"], labels, [baseline[key] for key in cohort], values,
                                           [group(key) for key in cohort], classes=classes,
                                           repetitions=context.criteria["bootstrap_repetitions"], seed=context.plan["future_runner_limits"]["seed"],
                                           minimum_units=context.criteria["minimum_independent_units"])
                intervals[name] = interval
                margin = float(context.plan["criteria"]["practical_margin"])
                ok &= interval["lower"] is not None and (interval["lower"] >= -margin if context.criteria["comparison_rule"] == "non_inferiority" else interval["lower"] > margin)
            adequate &= ok
        assessment = "eligible_for_manual_freeze" if phase == "selection" else "meets_frozen_checks"
        reports[candidate_id] = {"metrics": summaries, "paired_intervals": intervals,
                                 assessment: bool(adequate), "artifacts": candidate["artifacts"],
                                 "prediction_sha256": candidate["input_sha256"]}
    return {"version": VERSION, "phase": phase, "task": context.plan["task"], "package_id": context.plan["package_id"],
            "plan_id": context.plan["plan_id"], "protocol_sha256": context.plan["protocol_sha256"],
            "criteria_sha256": context.criteria_sha256, "purpose": context.manifest["purpose"],
            "evaluation_criteria": context.criteria, "minimum_prediction_coverage": context.plan["criteria"]["minimum_prediction_coverage"],
            "practical_margin": context.plan["criteria"]["practical_margin"],
            "cohort_sha256": rowset_sha(keys), "candidates": reports, "winner": None,
            "training_executed": False, "activation_authorized": False,
            "test_opening_receipt_id": receipt["receipt_id"] if phase == "test" else None,
            "freeze_id": receipt["freeze_id"] if phase == "test" else None,
            "label_partitions_opened": ["train", phase] if context.plan["task"] == "p2" else [phase]}
