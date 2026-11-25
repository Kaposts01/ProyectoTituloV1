"""Deterministic, signed restricted packages. Pseudonyms are NOT anonymization."""

from __future__ import annotations

import hashlib
import hmac
import json
import platform
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.ml.annotation_contract import CONTEXT_COLUMNS
from app.ml.export_snapshot import PreparedSnapshot
from app.ml.temporal_dataset import P1Dataset

EXPORT_VERSION = "restricted-rejection-export-v1"
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
PAYLOAD_FILES = ("features.jsonl", "targets.jsonl", "metadata.jsonl")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_secret(secret: bytes) -> None:
    if type(secret) is not bytes or len(secret) != 32:
        raise ValueError("Se requiere una clave privada de 32 bytes generada aleatoriamente")


def signature(value: bytes, secret: bytes, *, domain: str) -> str:
    validate_secret(secret)
    return hmac.new(secret, domain.encode("ascii") + b"\x00" + value, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ExportBundle:
    files: tuple[tuple[str, bytes], ...] = field(repr=False)
    manifest: bytes = field(repr=False)


def build_bundle(prepared: PreparedSnapshot, *, secret: bytes, scope: str,
                 exporter_revision: str, exporter_dependencies_sha256: str,
                 exporter_source_sha256: str, exporter_dirty: bool = False) -> ExportBundle:
    """All sensitive rows remain in three separate restricted files, joined by row_key.

    Keys never enter the bundle. Same snapshot/key/scope/exporter provenance -> same bytes.
    A trusted caller supplies actual exporter provenance; CLI derives it from local files.
    """
    validate_secret(secret)
    if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", scope)
            or not re.fullmatch(r"[a-f0-9]{40}", exporter_revision)
            or not re.fullmatch(r"[a-f0-9]{64}", exporter_dependencies_sha256)
            or not re.fullmatch(r"[a-f0-9]{64}", exporter_source_sha256) or type(exporter_dirty) is not bool):
        raise ValueError("Procedencia de exportacion invalida")
    dataset = prepared.dataset
    p1 = isinstance(dataset, P1Dataset)
    task = "p1" if p1 else "p2"
    inputs, targets, metadata = [], [], []
    classes = Counter()

    def pseudonym(kind: str, source: str, value: object) -> str:
        return signature(canonical_json([scope, kind, source, value]), secret, domain="pseudonym-v1")

    for row in dataset.rows:
        if p1:
            observation = row.observation
            context = observation.context
            source = context.source
            row_key = pseudonym("p1-observation", source, str(observation.observation_id))
            features, target = row.model_features(), row.target.value
            group = {name: getattr(context, name) for name in CONTEXT_COLUMNS}
            auxiliary = {
                "source": source, "context_group": pseudonym("p1-context", source, group),
                "occurred_at": _time(observation.occurred_at), "calculated_at": _time(observation.available_at),
                "label_available_at": _time(row.label_available_at), "label_revision": row.label_revision,
                "normalization_version": context.normalization_version, "taxonomy_version": context.taxonomy_version,
            }
        else:
            source = row.source
            row_key = pseudonym("p2-obligation", source, str(row.obligation_id))
            features, target = row.features.model_features(), row.target
            # JSON decimal strings preserve amounts; future preprocessing must cast explicitly.
            features["amount"] = format(row.features.amount.quantize(Decimal("1")), "f")
            auxiliary = {
                "source": source, "obligation_group": pseudonym("obligation", source, str(row.obligation_id)),
                "subscription_group": pseudonym("subscription", source, str(row.subscription_id)) if row.subscription_id else None,
                "first_rejection_ref": pseudonym("event", source, str(row.first_rejection_id)),
                "coverage_ref": pseudonym("coverage", source, str(row.coverage_id)),
                "t0": _time(row.t0), "calculated_at": _time(row.calculated_at),
                "outcome_end": _time(row.outcome_end), "label_available_at": _time(row.label_available_at),
            }
        inputs.append(canonical_json({"row_key": row_key, "features": features}))
        targets.append(canonical_json({"row_key": row_key, "target": target}))
        metadata.append(canonical_json({"row_key": row_key, **auxiliary}))
        classes[str(target)] += 1
    files = tuple(zip(PAYLOAD_FILES, (b"".join(inputs), b"".join(targets), b"".join(metadata)), strict=True))
    if sum(len(content) for _, content in files) > MAX_PACKAGE_BYTES:
        raise ValueError("Paquete demasiado grande; reduzca el snapshot conservando grupos y cortes")
    manifest = {
        "export_version": EXPORT_VERSION, "dataset_version": dataset.version, "task": task,
        "purpose": prepared.purpose, "as_of": _time(dataset.as_of), "scope": scope,
        "key_id": signature(b"key-id", secret, domain="key-fingerprint-v1"),
        "input_snapshot_sha256": prepared.snapshot_sha256, "input_provenance": dict(prepared.provenance),
        "exporter_revision": exporter_revision, "exporter_dependencies_sha256": exporter_dependencies_sha256,
        "exporter_source_sha256": exporter_source_sha256, "exporter_dirty": exporter_dirty,
        "exporter_runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                             "system": platform.system()},
        "rows": len(dataset.rows), "target_counts": dict(sorted(classes.items())),
        "source_counts": [{"source": source, "included": included, "excluded": excluded}
                          for source, included, excluded in prepared.source_counts],
        "coverage_proofs": [{"source": source, "proofs": total, "complete": complete,
                             "reconciled": reconciled, "history_complete": history}
                            for source, total, complete, reconciled, history in prepared.coverage_summary],
        "exclusions": {str(reason): count for reason, count in dataset.exclusions},
        "feature_names": (["source", "resource_type", "processor", "code", "processor_code", "normalized_text"]
                          if p1 else ["source", "amount", "currency", "elapsed_days", "days_from_due"]),
        "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)} for name, content in files},
        "access": "restricted-not-anonymous", "missing_values": "JSON-null-no-imputation",
    }
    if not p1:
        manifest["episode_policy"] = dataset.episode_policy
        manifest["horizon_hours"] = 720
    # Fingerprint and MAC bind manifest, provenance and payload hashes, without circularity.
    manifest["package_id"] = hashlib.sha256(canonical_json(manifest)).hexdigest()
    manifest["signature"] = signature(canonical_json(manifest), secret, domain="manifest-v1")
    return ExportBundle(files, canonical_json(manifest))
