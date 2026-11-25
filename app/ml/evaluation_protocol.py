"""ML-06 label-blind temporal planning. No fitting, prediction or statistical results."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from app.ml.dataset_export import canonical_json
from app.ml.export_snapshot import exact, parse_json
from app.ml.temporal_dataset import SOURCES

PROTOCOL_VERSION = "rejection-evaluation-v1-draft"
SPLITS = ("train", "calibration", "selection", "test")
CANDIDATES = {
    "p1": ("ml02_rules", "char_tfidf_logistic"),
    "p2": ("train_prevalence", "logistic", "hist_gradient_boosting"),
}


def instant(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Reloj de protocolo invalido")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Reloj sin zona")
    return result.astimezone(UTC)


def token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Referencia restringida invalida")
    return value


@dataclass(frozen=True, slots=True)
class Protocol:
    task: str
    experiment_id: str
    boundaries: tuple[datetime, ...]
    group_policy: str
    expected_sources: tuple[str, ...]
    minimum_rows_per_source_split: int
    criteria_status: str
    practical_margin: str | None
    minimum_prediction_coverage: str | None
    criteria_reference_sha256: str | None
    seed: int
    max_trials: int
    max_fit_seconds: int
    max_memory_mb: int
    max_threads: int
    fingerprint: str


def parse_protocol(data: bytes) -> Protocol:
    """Require explicit cuts/criteria; no arbitrary executable estimators or artifact paths."""
    try:
        value = parse_json(data)
        names = {"protocol_version", "task", "experiment_id", "train_start", "train_end", "calibration_end",
                 "selection_end", "test_end", "group_policy", "expected_sources", "minimum_rows_per_source_split",
                 "criteria_status", "practical_margin", "minimum_prediction_coverage", "criteria_reference_sha256",
                 "seed", "max_trials", "max_fit_seconds", "max_memory_mb", "max_threads"}
        exact(value, names)
        if value["protocol_version"] != PROTOCOL_VERSION or value["task"] not in CANDIDATES:
            raise ValueError("Version/tarea no admitida")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value["experiment_id"]):
            raise ValueError("Identificador invalido")
        boundaries = tuple(instant(value[name]) for name in (
            "train_start", "train_end", "calibration_end", "selection_end", "test_end"))
        if any(a >= b for a, b in pairwise(boundaries)):
            raise ValueError("Cortes no crecientes")
        policies = {"temporal", "unseen_context", "unseen_text"} if value["task"] == "p1" else {"temporal", "unseen_subscription"}
        if value["group_policy"] not in policies:
            raise ValueError("Agrupacion incompatible")
        sources = value["expected_sources"]
        if (type(sources) is not list or not sources or any(source not in SOURCES for source in sources)
                or len(set(sources)) != len(sources)):
            raise ValueError("Fuentes explicitas requeridas")
        bounds = {"minimum_rows_per_source_split": (1, 100_000), "seed": (0, 2**32 - 1),
                  "max_trials": (1, 100), "max_fit_seconds": (1, 36_000), "max_memory_mb": (128, 65_536), "max_threads": (1, 32)}
        for name, (low, high) in bounds.items():
            if type(value[name]) is not int or not low <= value[name] <= high:
                raise ValueError("Limite invalido")
        if value["criteria_status"] not in {"draft", "agreed"}:
            raise ValueError("Estado de criterios invalido")
        for name in ("practical_margin", "minimum_prediction_coverage"):
            item = value[name]
            if item is not None and (not isinstance(item, str) or len(item) > 24
                                     or not Decimal(item).is_finite() or not 0 < Decimal(item) <= 1):
                raise ValueError("Criterio invalido")
        if value["criteria_reference_sha256"] is not None:
            token(value["criteria_reference_sha256"])
        return Protocol(
            value["task"], value["experiment_id"], boundaries, value["group_policy"], tuple(sorted(sources)),
            value["minimum_rows_per_source_split"], value["criteria_status"], value["practical_margin"],
            value["minimum_prediction_coverage"], value["criteria_reference_sha256"],
            *(value[name] for name in ("seed", "max_trials", "max_fit_seconds", "max_memory_mb", "max_threads")),
            hashlib.sha256(canonical_json(value)).hexdigest(),
        )
    except (ValueError, TypeError, KeyError, InvalidOperation):
        raise ValueError("Protocolo rechazado: revise cortes, criterios, fuentes y limites") from None


@dataclass(frozen=True, slots=True)
class PlanningRow:
    row_key: str = field(repr=False)
    source: str
    calculated_at: datetime
    label_available_at: datetime
    outcome_end: datetime | None
    group: str | None = field(repr=False)


def build_plan(rows: tuple[PlanningRow, ...], *, protocol: Protocol, as_of: datetime,
               package_id: str) -> dict:
    """Four forward-only stages. Never inspect targets, choose a winner or fit anything.

    Unseen-group mode assigns each group to its first nominal period, including pre-study
    history; future membership never removes earlier training observations.
    """
    token(package_id)
    bounds = protocol.boundaries
    if as_of.tzinfo is None:
        raise ValueError("Corte sin zona")
    as_of = as_of.astimezone(UTC)
    if bounds[-1] > as_of:
        raise ValueError("Fin del test posterior al corte del paquete")
    seen = set()
    for row in rows:
        token(row.row_key)
        if (row.row_key in seen or row.source not in SOURCES or row.calculated_at.tzinfo is None
                or row.label_available_at.tzinfo is None or row.label_available_at > as_of or row.calculated_at > as_of):
            raise ValueError("Metadatos temporales duplicados o invalidos")
        if protocol.task == "p2" and (row.outcome_end is None or row.outcome_end.tzinfo is None
                                     or row.outcome_end > row.label_available_at or row.outcome_end <= row.calculated_at):
            raise ValueError("Ventana P2 invalida")
        if row.group is not None:
            token(row.group)
        seen.add(row.row_key)

    def stage(row: PlanningRow) -> int:
        if row.calculated_at < bounds[0]:
            return -1
        for i in range(4):
            if row.calculated_at < bounds[i + 1]:
                return i
        return 4

    first = {}
    if protocol.group_policy != "temporal":
        for row in rows:
            if row.group and row.source in protocol.expected_sources:
                first[row.group] = min(first.get(row.group, 4), stage(row))
    partitions = {name: [] for name in SPLITS}
    exclusions, counts = Counter(), Counter()
    for row in sorted(rows, key=lambda item: (item.calculated_at, item.row_key)):
        index = stage(row)
        reason = None
        if row.source not in protocol.expected_sources:
            reason = "source_outside_protocol"
        elif index not in range(4):
            reason = "outside_study_period"
        elif protocol.group_policy != "temporal" and row.group is None:
            reason = "missing_group"
        elif protocol.group_policy != "temporal" and first[row.group] != index:
            reason = "group_previously_observed"
        elif index < 3 and row.outcome_end is not None and row.outcome_end >= bounds[index + 1]:
            reason = "purged_overlapping_outcome"
        elif row.label_available_at > (bounds[index + 1] if index < 3 else as_of):
            reason = "label_not_available_at_stage_cutoff"
        if reason:
            exclusions[reason] += 1
        else:
            name = SPLITS[index]
            partitions[name].append(row.row_key)
            counts[name, row.source] += 1
    blockers = []
    if (protocol.criteria_status != "agreed" or protocol.practical_margin is None
            or protocol.minimum_prediction_coverage is None or protocol.criteria_reference_sha256 is None):
        blockers.append("acceptance_criteria_not_agreed")
    if protocol.task == "p2" and bounds[-1] + timedelta(days=30) > as_of:
        blockers.append("test_period_not_fully_mature")
    per_source = []
    for name in SPLITS:
        for source in protocol.expected_sources:
            count = counts[name, source]
            per_source.append({"split": name, "source": source, "rows": count})
            if count < protocol.minimum_rows_per_source_split:
                blockers.append(f"insufficient_rows:{name}:{source}")
    return {
        "protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol.fingerprint,
        "experiment_id": protocol.experiment_id, "task": protocol.task, "package_id": package_id,
        "status": "structural_preflight_passed" if not blockers else "blocked",
        "blockers": blockers, "partitions": partitions, "counts": per_source,
        "exclusions": dict(sorted(exclusions.items())), "group_policy": protocol.group_policy,
        "expected_sources": list(protocol.expected_sources),
        "minimum_rows_per_source_split": protocol.minimum_rows_per_source_split,
        "boundaries_utc": [value.isoformat() for value in bounds], "as_of": as_of.isoformat(),
        "criteria": {"status": protocol.criteria_status, "practical_margin": protocol.practical_margin,
                     "minimum_prediction_coverage": protocol.minimum_prediction_coverage,
                     "reference_sha256": protocol.criteria_reference_sha256},
        "comparison": {"candidate_ids": CANDIDATES[protocol.task],
                       "primary_metric": "macro_f1_end_to_end" if protocol.task == "p1" else "brier",
                       "direction": "maximize" if protocol.task == "p1" else "minimize",
                       "benchmark_status": "not_run", "winner": None},
        "future_runner_limits": {name: getattr(protocol, name) for name in (
            "seed", "max_trials", "max_fit_seconds", "max_memory_mb", "max_threads")},
        "test_labels_inspected": False, "training_executed": False,
        "pending": ["class_support", "statistical_power", "calibration", "uncertainty", "domain_validation", "activation_approval"],
    }
