"""ML-09 shadow policy: deterministic advice, never permission or provider operations.

Only reviewed, point-in-time Core snapshots enter this boundary. Model outputs are
accepted exclusively as explicit synthetic simulations; real inference is not enabled.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.ml.annotation_contract import AnnotationContext
from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import token
from app.ml.taxonomy import (
    RULES_VERSION,
    TAXONOMY_VERSION,
    Category,
    ClassificationState,
    Restriction,
    classify_rejection,
)

ENGINE_VERSION = "rejection-engine-v1-draft"
POLICY_VERSION = "rejection-advice-v1-draft"
SOURCES = frozenset({"virtualpos1", "virtualpos2", "toku", "payku", "tch"})


class State(StrEnum):
    REJECTED = "rejected"
    PAID = "paid"
    CANCELLED = "cancelled"
    PENDING = "pending"
    UNKNOWN = "unknown"


class Advice(StrEnum):
    NONE = "no_action"
    REFRESH = "refresh_data"
    REVIEW = "review_evidence"
    SECURITY = "review_security_signal"
    MANDATE = "review_mandate_or_instrument"
    TECHNICAL = "review_service_incident"
    MANUAL = "review_collection_options"


def _clock(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Se requiere reloj con zona")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CoreSnapshot:
    """No raw text/PII. Coverage clocks require an audited adapter, not updated_at."""

    source: str
    resource_type: str
    resource_id: UUID
    evidence_id: UUID
    evidence_at: datetime
    as_of: datetime
    verified_through: datetime | None
    state: State
    state_mapping_sha256: str
    data_sha256: str
    context: AnnotationContext | None = field(default=None, repr=False)
    mandate_active: bool | None = None
    retry_limit_reached: bool | None = None
    subscription_active: bool | None = None
    links_verified: bool = False
    settlement_verified: bool = False

    def __post_init__(self):
        if self.source not in SOURCES or self.resource_type not in {"charge", "payment", "transaction"}:
            raise ValueError("Ambito centralizado invalido")
        if not isinstance(self.resource_id, UUID) or not isinstance(self.evidence_id, UUID) or not isinstance(self.state, State):
            raise ValueError("Recurso o estado invalido")
        token(self.state_mapping_sha256)
        token(self.data_sha256)
        if _clock(self.evidence_at) > _clock(self.as_of):
            raise ValueError("Evidencia futura")
        if self.verified_through is not None and _clock(self.verified_through) > _clock(self.as_of):
            raise ValueError("Cobertura futura")
        if self.context is not None and (not isinstance(self.context, AnnotationContext)
                or self.context.source != self.source or self.context.resource_type != self.resource_type):
            raise ValueError("Contexto de otro recurso o canal")
        for value in (self.mandate_active, self.retry_limit_reached, self.subscription_active):
            if value is not None and type(value) is not bool:
                raise ValueError("Restriccion invalida")
        if type(self.links_verified) is not bool or type(self.settlement_verified) is not bool:
            raise ValueError("Verificacion de enlaces invalida")


@dataclass(frozen=True, slots=True)
class Simulation:
    """Manually supplied synthetic output; never presented as a validated model."""

    task: str
    source: str
    artifact_id: str
    input_sha256: str
    category: Category | None = None
    score: float | None = None

    def __post_init__(self):
        token(self.artifact_id)
        token(self.input_sha256)
        if self.source not in SOURCES or self.task not in {"p1", "p2"}:
            raise ValueError("Simulacion invalida")
        if self.task == "p1" and (not isinstance(self.category, Category) or self.score is not None):
            raise ValueError("P1 simulado requiere familia; no probabilidad P2")
        if self.task == "p2" and (self.category is not None or type(self.score) not in {float, int}
                or not math.isfinite(self.score) or not 0 <= self.score <= 1):
            raise ValueError("P2 simulado invalido")


@dataclass(frozen=True, slots=True)
class Recommendation:
    logical_id: str
    input_sha256: str
    source: str
    resource_type: str
    as_of: str
    category: Category | None
    method: str
    classification_state: str
    rules_state: str
    subreason: str | None
    severity: str
    advice: Advice
    reasons: tuple[str, ...]
    restrictions: tuple[str, ...]
    matched_rules: tuple[str, ...]
    p1_artifact_id: str | None
    p2_artifact_id: str | None
    simulated_p2: float | None
    simulation: bool
    policy_sha256: str
    engine_version: str = ENGINE_VERSION
    policy_version: str = POLICY_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    rules_version: str = RULES_VERSION
    confidence: None = None
    recovery_probability: None = None
    execution_allowed: bool = False


def snapshot_hash(snapshot: CoreSnapshot) -> str:
    value = asdict(snapshot)
    for key in ("evidence_at", "as_of", "verified_through"):
        value[key] = _clock(value[key]).isoformat() if value[key] is not None else None
    for key in ("resource_id", "evidence_id"):
        value[key] = str(value[key])
    return hashlib.sha256(canonical_json(value)).hexdigest()


def recommend(snapshot: CoreSnapshot, *, max_age_seconds: int = 3600,
              simulations: tuple[Simulation, ...] = (), simulation: bool = False) -> Recommendation:
    """Pure, repeatable shadow calculation. Caller must re-read Core before any WR flow.

    The freshness budget is explicit engineering policy, not a claim of provider SLA.
    Logical idempotence does not persist results or authorize reuse after state changes.
    """
    if not isinstance(snapshot, CoreSnapshot) or type(max_age_seconds) is not int or not 0 < max_age_seconds <= 86400:
        raise ValueError("Politica de vigencia invalida")
    if type(simulation) is not bool or not isinstance(simulations, tuple) or len(simulations) > 2:
        raise ValueError("Modo de simulacion invalido")
    input_sha = snapshot_hash(snapshot)
    models = {}
    for output in simulations:
        if (not simulation or not isinstance(output, Simulation) or output.source != snapshot.source
                or output.input_sha256 != input_sha or output.task in models):
            raise ValueError("Salida simulada no corresponde al calculo")
        models[output.task] = output
    context = snapshot.context
    # Processor codes have no standalone mapping in ML-02. Do not guess their
    # meaning or silently treat them as an equivalent provider rejection code.
    reason = context.normalized_text if context else None
    rules = classify_rejection(snapshot.source, context.code if context else None, reason)
    flags = {str(flag) for flag in rules.restrictions}
    flags.add(str(Restriction.NO_AUTOMATIC_RETRY))  # Shadow policy always requires human control.
    if snapshot.mandate_active is False:
        flags.add(str(Restriction.MANDATE_INACTIVE))
    if snapshot.retry_limit_reached is True:
        flags.add(str(Restriction.RETRY_LIMIT))
    category, method, state = rules.category, rules.method, str(rules.state)
    reasons = set(rules.review_reasons)
    reasons.update({"p1_simulated" if "p1" in models else "p1_unavailable",
                    "p2_simulated" if "p2" in models else "p2_unavailable"})
    if context and context.processor_code:
        reasons.add("processor_code_requires_review")
    p1 = models.get("p1")
    if p1 and rules.state in {ClassificationState.UNMAPPED, ClassificationState.MISSING}:
        category, method, state = p1.category, "simulated_p1", "simulated"
        reasons.add("synthetic_output_not_validated")
    elif p1 and category != p1.category:
        reasons.add("model_rule_disagreement")
    fresh = (snapshot.verified_through is not None
             and _clock(snapshot.as_of) - _clock(snapshot.verified_through) <= timedelta(seconds=max_age_seconds)
             and _clock(snapshot.verified_through) >= _clock(snapshot.evidence_at))
    if snapshot.state in {State.PAID, State.CANCELLED} or snapshot.subscription_active is False:
        advice = Advice.NONE
        reasons.add("already_paid_cancelled_or_subscription_inactive")
    elif not fresh:
        advice = Advice.REFRESH
        reasons.add("coverage_missing_or_stale")
    elif snapshot.state != State.REJECTED or not snapshot.links_verified or not snapshot.settlement_verified:
        advice = Advice.REVIEW
        reasons.add("state_links_or_settlement_unverified")
    elif Restriction.SECURITY_REVIEW in flags or category == Category.FRAUD:
        advice = Advice.SECURITY
    elif ({str(Restriction.MANDATE_INACTIVE), str(Restriction.INSTRUMENT_UNUSABLE), str(Restriction.ACCOUNT_CLOSED)} & flags
          or category in {Category.EXPIRED, Category.BLOCKED}):
        advice = Advice.MANDATE
    elif (rules.state != ClassificationState.CLASSIFIED or rules.review_required or simulation
          or (context and context.processor_code)
          or snapshot.mandate_active is not True or snapshot.retry_limit_reached is not False
          or snapshot.subscription_active is not True):
        advice = Advice.REVIEW
        reasons.add("human_review_required")
    elif category == Category.TECH:
        advice = Advice.TECHNICAL
    else:
        advice = Advice.MANUAL
    policy = {"version": POLICY_VERSION, "max_age_seconds": max_age_seconds, "mode": "shadow",
              "model_mode": "synthetic-only", "engine": ENGINE_VERSION,
              "taxonomy": TAXONOMY_VERSION, "rules": RULES_VERSION}
    policy_sha = hashlib.sha256(canonical_json(policy)).hexdigest()
    bundle = {"input": input_sha, "policy": policy_sha, "simulation": simulation,
              "outputs": [asdict(models[key]) for key in sorted(models)]}
    p2 = models.get("p2")
    return Recommendation(
        logical_id=hashlib.sha256(canonical_json(bundle)).hexdigest(), input_sha256=input_sha,
        source=snapshot.source, resource_type=snapshot.resource_type, as_of=_clock(snapshot.as_of).isoformat(),
        category=category, method=method, classification_state=state, advice=advice,
        rules_state=str(rules.state), subreason=rules.subreason, severity=str(rules.severity),
        reasons=tuple(sorted(reasons)), restrictions=tuple(sorted(flags)), matched_rules=rules.matched_rules,
        p1_artifact_id=p1.artifact_id if p1 else None, p2_artifact_id=p2.artifact_id if p2 else None,
        simulated_p2=p2.score if p2 else None, simulation=simulation, policy_sha256=policy_sha,
    )
