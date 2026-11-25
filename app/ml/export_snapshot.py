"""Strict offline adapter for reviewed ML-04 snapshots; never infers missing history."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.ml.annotation_contract import CONTEXT_COLUMNS, AnnotationContext, Decision
from app.ml.taxonomy import Category
from app.ml.temporal_dataset import (
    SOURCES,
    Coverage,
    EventKind,
    EvidenceEvent,
    P1Dataset,
    P1Observation,
    P1Review,
    P2Dataset,
    build_p1,
    build_p2,
)

MAX_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 100_000
INPUT_VERSION = "rejection-snapshot-v1"


def exact(value: dict, names: set[str]) -> dict:
    if type(value) is not dict or set(value) != names:
        raise ValueError("Campos del snapshot no admitidos o incompletos")
    return value


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clave JSON repetida")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("Numero no finito no admitido")


def parse_json(data: bytes) -> dict:
    if type(data) is not bytes or len(data) > MAX_BYTES:
        raise ValueError("Archivo invalido o demasiado grande")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("JSON invalido") from None


def _date(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Reloj invalido")
    return datetime.fromisoformat(value)


def _uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("UUID interno invalido")
    return UUID(value)


def _records(value: list) -> list:
    if type(value) is not list or len(value) > MAX_RECORDS or any(type(row) is not dict for row in value):
        raise ValueError("Coleccion de registros invalida")
    return value


def _context(value: dict) -> AnnotationContext:
    return AnnotationContext(**exact(value, {*CONTEXT_COLUMNS, "privacy_reviewed"}))


@dataclass(frozen=True, slots=True)
class PreparedSnapshot:
    dataset: P1Dataset | P2Dataset = field(repr=False)
    purpose: str
    provenance: tuple[tuple[str, str], ...]
    snapshot_sha256: str
    source_counts: tuple[tuple[str, int, int], ...]
    coverage_summary: tuple[tuple[str, int, int, int, int], ...]


def prepare_snapshot(data: bytes, *, allow_reviewed_real: bool = False) -> PreparedSnapshot:
    """No output until all rows validate; unexpected columns (including PII) fail closed.

    Provenance hashes are declarations to reconcile with private originals, not evidence
    of authenticity or privacy. No SQL/credentials are accepted as provenance text.
    """
    try:
        return _prepare(data, allow_reviewed_real=allow_reviewed_real)
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, OverflowError):
        raise ValueError("Snapshot rechazado: revise esquema, procedencia, privacidad y contratos temporales") from None


def _prepare(data: bytes, *, allow_reviewed_real: bool) -> PreparedSnapshot:
    document = parse_json(data)
    common = {"schema_version", "task", "purpose", "as_of", "privacy_reviewed", "policy_reviewed", "provenance"}
    task = document.get("task")
    fields = {"observations", "reviews", "review_history_complete"} if task == "p1" else {"events", "coverages"}
    exact(document, common | fields)
    if (document["schema_version"] != INPUT_VERSION or task not in {"p1", "p2"}
            or document["privacy_reviewed"] is not True or document["policy_reviewed"] is not True):
        raise ValueError("Revision explicita requerida")
    purpose = document["purpose"]
    if purpose not in {"synthetic", "reviewed-real"} or (purpose == "reviewed-real" and allow_reviewed_real is not True):
        raise ValueError("Uso real no habilitado")
    provenance = exact(document["provenance"], {"adapter_version", "query_sha256", "source_snapshot_sha256",
                                              "code_revision", "dependencies_sha256", "study_mode"})
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provenance["adapter_version"]):
        raise ValueError("Adaptador invalido")
    for name in ("query_sha256", "source_snapshot_sha256", "dependencies_sha256", "code_revision"):
        if not isinstance(provenance[name], str) or not re.fullmatch(r"[a-f0-9]{40}" if name == "code_revision" else r"[a-f0-9]{64}", provenance[name]):
            raise ValueError("Fingerprint invalido")
    if provenance["study_mode"] not in {"retrospective-limited", "point-in-time"}:
        raise ValueError("Modo de estudio invalido")
    cutoff = _date(document["as_of"])
    counts, coverage_counts = [], []
    if task == "p1":
        observations, reviews = [], []
        for row in _records(document["observations"]):
            exact(row, {"observation_id", "context", "occurred_at", "available_at"})
            observations.append(P1Observation(_uuid(row["observation_id"]), _context(row["context"]),
                                              _date(row["occurred_at"]), _date(row["available_at"])))
        for row in _records(document["reviews"]):
            exact(row, {"context", "revision", "decision", "category", "reviewed_at", "actor_id"})
            reviews.append(P1Review(_context(row["context"]), row["revision"], Decision(row["decision"]),
                                    Category(row["category"]) if row["category"] is not None else None,
                                    _date(row["reviewed_at"]), _uuid(row["actor_id"])))
        dataset = build_p1(observations, reviews, as_of=cutoff, review_history_complete=document["review_history_complete"])
        for source in sorted(SOURCES):
            subset = [row for row in observations if row.context.source == source]
            if subset:
                part = build_p1(subset, reviews, as_of=cutoff, review_history_complete=True)
                counts.append((source, len(part.rows), sum(count for _, count in part.exclusions)))
    else:
        events, coverages = [], []
        event_fields = {"event_id", "source", "obligation_id", "kind", "occurred_at", "available_at", "amount",
                        "currency", "link_verified", "subscription_id", "due_at", "due_available_at"}
        for row in _records(document["events"]):
            exact(row, event_fields)
            if row["amount"] is not None and (type(row["amount"]) is not str or len(row["amount"]) > 32):
                raise ValueError("Monto debe ser texto decimal acotado")
            values = dict(row)
            for name in ("event_id", "obligation_id", "subscription_id"):
                values[name] = _uuid(row[name])
            for name in ("occurred_at", "available_at", "due_at", "due_available_at"):
                values[name] = _date(row[name])
            values["kind"] = EventKind(row["kind"])
            values["amount"] = Decimal(row["amount"]) if row["amount"] is not None else None
            events.append(EvidenceEvent(**values))
        for row in _records(document["coverages"]):
            exact(row, {"evidence_id", "source", "obligation_id", "observed_from", "observed_through", "available_at",
                        "complete", "reconciled", "history_complete"})
            values = dict(row)
            for name in ("evidence_id", "obligation_id"):
                values[name] = _uuid(row[name])
            for name in ("observed_from", "observed_through", "available_at"):
                values[name] = _date(row[name])
            coverages.append(Coverage(**values))
        dataset = build_p2(events, coverages, as_of=cutoff)
        for source in sorted(SOURCES):
            subset = [row for row in events if row.source == source]
            proofs = list({proof for proof in coverages if proof.source == source})
            if subset:
                part = build_p2(subset, proofs, as_of=cutoff)
                counts.append((source, len(part.rows), sum(count for _, count in part.exclusions)))
            if proofs:
                coverage_counts.append((source, len(proofs), sum(p.complete for p in proofs),
                                        sum(p.reconciled for p in proofs), sum(p.history_complete for p in proofs)))
    return PreparedSnapshot(dataset, purpose, tuple(sorted(provenance.items())), hashlib.sha256(data).hexdigest(),
                            tuple(counts), tuple(coverage_counts))
