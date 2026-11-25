"""Authenticated ML-05 input -> label-blind ML-06 plan. Never parses targets.jsonl."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from app.ml.annotation_contract import NORMALIZATION_VERSION, AnnotationContext
from app.ml.dataset_export import MAX_PACKAGE_BYTES, canonical_json, signature
from app.ml.evaluation_protocol import PlanningRow, Protocol, build_plan, instant, token
from app.ml.export_files import read_private_file, verify_bundle
from app.ml.export_snapshot import MAX_RECORDS, exact, parse_json
from app.ml.taxonomy import TAXONOMY_VERSION
from app.ml.temporal_dataset import DATASET_VERSION, EPISODE_POLICY, HORIZON, SOURCES


def _lines(data: bytes) -> list[dict]:
    lines = data.splitlines()
    if len(lines) > MAX_RECORDS or any(not line for line in lines):
        raise ValueError("Filas de paquete invalidas")
    return [parse_json(line) for line in lines]


def prepare_plan(root: Path, relative: str, *, secret: bytes, protocol: Protocol) -> dict:
    """Integrity reads all file hashes; semantics use metadata and optional P1 grouping text.

    Test labels never enter memory as parsed objects, class counts are not reported.
    This is a workflow boundary for a trusted operator, not an OS holdout vault.
    """
    verified = verify_bundle(root, relative, secret=secret, include_manifest=True)
    manifest = verified["manifest"]
    if (manifest["task"] != protocol.task or manifest["dataset_version"] != DATASET_VERSION
            or manifest["access"] != "restricted-not-anonymous"):
        raise ValueError("Paquete incompatible con protocolo")
    if protocol.task == "p2" and (manifest.get("episode_policy") != EPISODE_POLICY or manifest.get("horizon_hours") != 720):
        raise ValueError("Politica P2 incompatible")
    if manifest["purpose"] == "reviewed-real" and manifest["exporter_dirty"]:
        raise ValueError("Paquete real sin codigo confirmado")

    def payload(name: str) -> list[dict]:
        data = read_private_file(root, f"{relative}/{name}", max_bytes=MAX_PACKAGE_BYTES)
        if hashlib.sha256(data).hexdigest() != manifest["files"][name]["sha256"]:
            raise ValueError("Paquete cambio durante lectura")
        return _lines(data)

    metadata = payload("metadata.jsonl")
    if type(manifest["rows"]) is not int or len(metadata) != manifest["rows"]:
        raise ValueError("Conteo de metadatos invalido")
    textual_groups = {}
    if protocol.group_policy == "unseen_text":
        features = payload("features.jsonl")
        if len(features) != len(metadata):
            raise ValueError("Features y metadatos desalineados")
        by_key = {row["row_key"]: row for row in metadata}
        for row in features:
            exact(row, {"row_key", "features"})
            key = token(row["row_key"])
            if key in textual_groups or key not in by_key:
                raise ValueError("Fila de features repetida o sin metadatos")
            meta = by_key[key]
            exact(row["features"], {"source", "resource_type", "processor", "code", "processor_code", "normalized_text"})
            context = AnnotationContext(**row["features"], privacy_reviewed=True,
                                        normalization_version=meta["normalization_version"], taxonomy_version=meta["taxonomy_version"])
            if context.source != meta["source"]:
                raise ValueError("Fuentes desalineadas")
            # Blinded global wording group: normalize case/accents/spacing/punctuation only.
            text = unicodedata.normalize("NFKD", context.normalized_text.casefold())
            text = "".join(char for char in text if not unicodedata.combining(char))
            text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()
            textual_groups[key] = signature(canonical_json(["wording-v1", text]), secret,
                                             domain="evaluation-wording-group-v1") if text else None
    rows, obligations = [], set()
    cutoff = instant(manifest["as_of"])
    for row in metadata:
        base = {"row_key", "source", "calculated_at", "label_available_at"}
        extra = ({"context_group", "occurred_at", "label_revision", "normalization_version", "taxonomy_version"}
                 if protocol.task == "p1" else {"obligation_group", "subscription_group", "first_rejection_ref", "coverage_ref", "t0", "outcome_end"})
        exact(row, base | extra)
        if row["source"] not in SOURCES:
            raise ValueError("Fuente no admitida")
        key, calculated, label = token(row["row_key"]), instant(row["calculated_at"]), instant(row["label_available_at"])
        end, group = None, None
        if protocol.task == "p1":
            # Revalidate versions/clock semantics even without reading P1 input text.
            if (row["normalization_version"] != NORMALIZATION_VERSION or row["taxonomy_version"] != TAXONOMY_VERSION
                    or type(row["label_revision"]) is not int or row["label_revision"] < 2 or instant(row["occurred_at"]) > calculated):
                raise ValueError("Contrato P1 incompatible")
            context_group = token(row["context_group"])
            if protocol.group_policy == "unseen_context":
                group = context_group
            elif protocol.group_policy == "unseen_text":
                group = textual_groups[key]
        else:
            obligation = token(row["obligation_group"])
            if obligation in obligations:
                raise ValueError("Obligacion duplicada en el paquete")
            obligations.add(obligation)
            for name in ("first_rejection_ref", "coverage_ref"):
                token(row[name])
            if row["subscription_group"] is not None:
                token(row["subscription_group"])
            if protocol.group_policy == "unseen_subscription":
                group = row["subscription_group"]
            t0, end = instant(row["t0"]), instant(row["outcome_end"])
            if not t0 <= calculated < end or end - t0 != HORIZON:
                raise ValueError("Ventana P2 no verificable")
        rows.append(PlanningRow(key, row["source"], calculated, label, end, group))
    plan = build_plan(tuple(rows), protocol=protocol, as_of=cutoff, package_id=verified["package_id"])
    plan["input_purpose"] = manifest["purpose"]
    plan["input_study_mode"] = manifest["input_provenance"]["study_mode"]
    plan["input_identity"] = {name: manifest[name] for name in (
        "scope", "key_id", "dataset_version", "input_snapshot_sha256", "exporter_source_sha256")}
    return plan
