"""ML-04: pure, fail-closed dataset contracts. No DB, files, fitting or inference.

Adapters must supply immutable, verified evidence; current Core state is insufficient.
The first-rejection/one-obligation policy is a versioned experimental proposal only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from app.ml.annotation_contract import AnnotationContext, Decision
from app.ml.taxonomy import Category

DATASET_VERSION = "rejection-dataset-v1-draft"
EPISODE_POLICY = "first-rejection-one-obligation-v1-draft"
HORIZON = timedelta(days=30)
SOURCES = frozenset({"virtualpos1", "virtualpos2", "toku", "payku", "tch"})


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Se requiere un instante con zona y precision verificable")
    return value.astimezone(UTC)


def _key(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValueError("Se requiere una clave interna opaca")


def _scope(source: str, obligation_id: UUID) -> None:
    if source not in SOURCES:
        raise ValueError("Fuente/cuenta no admitida")
    _key(obligation_id)


@dataclass(frozen=True, slots=True)
class P1Observation:
    observation_id: UUID = field(repr=False)
    context: AnnotationContext
    occurred_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        _key(self.observation_id)
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at))
        object.__setattr__(self, "available_at", _instant(self.available_at))
        if not isinstance(self.context, AnnotationContext) or _instant(self.available_at) < _instant(self.occurred_at):
            raise ValueError("Observacion P1 invalida")


@dataclass(frozen=True, slots=True)
class P1Review:
    context: AnnotationContext
    revision: int
    decision: Decision
    category: Category | None
    reviewed_at: datetime
    actor_id: UUID = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewed_at", _instant(self.reviewed_at))
        _key(self.actor_id)
        if (not isinstance(self.context, AnnotationContext) or type(self.revision) is not int
                or self.revision < 1 or not isinstance(self.decision, Decision)
                or (self.category is not None and not isinstance(self.category, Category))
                or (self.decision == Decision.APPROVED and (
                    self.category is None or self.context.processor == "unresolved"
                ))
                or (self.decision not in {Decision.DRAFT, Decision.APPROVED} and self.category is not None)):
            raise ValueError("Revision P1 invalida")


@dataclass(frozen=True, slots=True)
class P1Row:
    observation: P1Observation
    target: Category
    label_revision: int
    label_available_at: datetime

    def model_features(self) -> dict[str, str]:
        context = self.observation.context
        return {name: getattr(context, name) for name in (
            "source", "resource_type", "processor", "code", "processor_code", "normalized_text",
        )}


@dataclass(frozen=True, slots=True)
class P1Dataset:
    rows: tuple[P1Row, ...]
    exclusions: tuple[tuple[str, int], ...]
    as_of: datetime
    version: str = DATASET_VERSION


def build_p1(observations: list[P1Observation], reviews: list[P1Review], *,
             as_of: datetime, review_history_complete: bool = False) -> P1Dataset:
    """Latest human approval AS OF the freeze, not the last-ever approved revision.

    Labels may be reviewed after the observation; training folds must separately require
    label_available_at <= fit time. Entire review history must come from ML-03, not rules.
    """
    freeze = _instant(as_of)
    if review_history_complete is not True:
        raise ValueError("Se requiere historial ML-03 completo y verificado")
    histories = defaultdict(dict)
    for review in reviews:
        previous = histories[review.context].get(review.revision)
        if previous is not None and previous != review:
            raise ValueError("Revisiones contradictorias")
        histories[review.context][review.revision] = review
    latest = {}
    for context, history in histories.items():
        ordered = sorted(history.values(), key=lambda review: review.revision)
        if [review.revision for review in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("Historial de revisiones incompleto")
        if ordered[0].decision != Decision.DRAFT:
            raise ValueError("Historial no comienza en propuesta ML-03")
        if any(a.reviewed_at > b.reviewed_at for a, b in pairwise(ordered)):
            raise ValueError("Relojes de revision inconsistentes")
        for review in ordered:
            if _instant(review.reviewed_at) <= freeze:
                latest[context] = review
        for previous, review in pairwise(ordered):
            if review.decision == Decision.APPROVED and (
                previous.decision != Decision.DRAFT or previous.category != review.category
                or previous.actor_id == review.actor_id
            ):
                raise ValueError("Aprobacion independiente ML-03 no verificable")
    unique = {}
    for observation in observations:
        if observation.observation_id in unique and unique[observation.observation_id] != observation:
            raise ValueError("Observaciones contradictorias")
        unique[observation.observation_id] = observation
    rows, excluded = [], Counter()
    for observation in unique.values():
        label = latest.get(observation.context)
        if observation.available_at > freeze:
            excluded["observation_after_cutoff"] += 1
        elif label is None:
            excluded["no_label_at_cutoff"] += 1
        elif label.decision != Decision.APPROVED:
            excluded["latest_label_not_approved"] += 1
        else:
            rows.append(P1Row(observation, label.category, label.revision, _instant(label.reviewed_at)))
    return P1Dataset(tuple(sorted(rows, key=lambda row: (row.observation.available_at, row.observation.observation_id))),
                     tuple(sorted(excluded.items())), freeze)


class EventKind(StrEnum):
    REJECTION = "rejection"
    FULL_PAYMENT = "confirmed_full_payment"
    PARTIAL = "partial_payment"
    REVERSAL = "reversal"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: UUID = field(repr=False)
    source: str
    obligation_id: UUID = field(repr=False)
    kind: EventKind
    occurred_at: datetime | None
    available_at: datetime | None
    amount: Decimal | None = None
    currency: str | None = None
    link_verified: bool = False
    subscription_id: UUID | None = field(default=None, repr=False)
    due_at: datetime | None = None
    due_available_at: datetime | None = None

    def __post_init__(self) -> None:
        _key(self.event_id)
        _scope(self.source, self.obligation_id)
        if self.subscription_id is not None:
            _key(self.subscription_id)
        if not isinstance(self.kind, EventKind) or type(self.link_verified) is not bool:
            raise ValueError("Evidencia invalida")
        for name in ("occurred_at", "available_at", "due_at", "due_available_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _instant(value))
        if self.occurred_at and self.available_at and self.available_at < self.occurred_at:
            raise ValueError("Disponibilidad anterior al evento")
        if self.amount is not None and (not isinstance(self.amount, Decimal) or not self.amount.is_finite()
                                        or not 0 < self.amount <= Decimal("9999999999999999.99")):
            raise ValueError("Monto invalido; se requiere Decimal positivo y finito")
        if self.currency is not None and self.currency not in {"CLP", "USD", "EUR", "UF"}:
            raise ValueError("Moneda no soportada por el contrato")


@dataclass(frozen=True, slots=True)
class Coverage:
    evidence_id: UUID = field(repr=False)
    source: str
    obligation_id: UUID = field(repr=False)
    observed_from: datetime
    observed_through: datetime
    available_at: datetime
    complete: bool = False
    reconciled: bool = False
    history_complete: bool = False

    def __post_init__(self) -> None:
        _key(self.evidence_id)
        _scope(self.source, self.obligation_id)
        for name in ("observed_from", "observed_through", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name)))
        if not (_instant(self.observed_from) <= _instant(self.observed_through) <= _instant(self.available_at)):
            raise ValueError("Intervalo de cobertura invalido")
        if any(type(flag) is not bool for flag in (self.complete, self.reconciled, self.history_complete)):
            raise ValueError("Cobertura invalida")


@dataclass(frozen=True, slots=True)
class P2Features:
    source: str
    amount: Decimal
    currency: str
    elapsed_days: float
    days_from_due: float | None

    def model_features(self) -> dict[str, str | Decimal | float | None]:
        return {name: getattr(self, name) for name in (
            "source", "amount", "currency", "elapsed_days", "days_from_due",
        )}


@dataclass(frozen=True, slots=True)
class P2Row:
    features: P2Features
    target: int
    source: str
    obligation_id: UUID = field(repr=False)
    first_rejection_id: UUID = field(repr=False)
    subscription_id: UUID | None = field(repr=False)
    coverage_id: UUID = field(repr=False)
    t0: datetime
    calculated_at: datetime
    outcome_end: datetime
    label_available_at: datetime


class Exclusion(StrEnum):
    NO_REJECTION = "no_rejection_at_cutoff"
    MISSING_CLOCK = "missing_event_or_availability_clock"
    LINK = "unverified_obligation_link"
    IMMATURE = "immature_window"
    COVERAGE = "incomplete_or_unreconciled_coverage"
    ORIGIN = "unverified_first_rejection"
    AMOUNT = "missing_amount_or_unsupported_currency"
    AMBIGUOUS = "ambiguous_partial_reversed_or_conflicting"
    PRECALCULATION = "payment_before_calculation"
    LATE = "evidence_not_available_at_cutoff"
    TOO_LATE = "calculation_after_horizon"


@dataclass(frozen=True, slots=True)
class P2Dataset:
    rows: tuple[P2Row, ...]
    exclusions: tuple[tuple[Exclusion, int], ...]
    as_of: datetime
    version: str = DATASET_VERSION
    episode_policy: str = EPISODE_POLICY


def _episode(events: list[EvidenceEvent], coverage: Coverage | None,
             freeze: datetime) -> P2Row | Exclusion:
    if any(event.occurred_at is None or event.available_at is None for event in events):
        return Exclusion.MISSING_CLOCK
    rejections = sorted((event for event in events if event.kind == EventKind.REJECTION and event.available_at <= freeze),
                        key=lambda event: (event.occurred_at, event.event_id))
    if not rejections:
        return Exclusion.NO_REJECTION
    first = rejections[0]
    t0, calculation = _instant(first.occurred_at), _instant(first.available_at)
    deadline = t0 + HORIZON  # UTC elapsed time, never calendar arithmetic across DST.
    if any(not event.link_verified for event in events):
        return Exclusion.LINK
    if freeze < deadline:
        return Exclusion.IMMATURE
    if calculation >= deadline:
        return Exclusion.TOO_LATE
    if not coverage or not coverage.history_complete:
        return Exclusion.ORIGIN
    if (not coverage.complete or not coverage.reconciled or coverage.observed_from > t0
            or coverage.observed_through < deadline or coverage.available_at > freeze):
        return Exclusion.COVERAGE
    if first.amount is None or first.currency != "CLP" or first.amount != first.amount.to_integral_value():
        return Exclusion.AMOUNT
    if (sum(event.occurred_at == t0 for event in rejections) > 1
            or any(event.available_at < calculation for event in rejections[1:])
            or len({event.subscription_id for event in events if event.subscription_id is not None}) > 1
            or any((event.amount, event.currency) != (first.amount, first.currency)
                   for event in rejections if event.occurred_at <= deadline)):
        return Exclusion.AMBIGUOUS
    if any(event.kind in {EventKind.PARTIAL, EventKind.REVERSAL, EventKind.AMBIGUOUS}
           and event.available_at <= freeze for event in events):
        return Exclusion.AMBIGUOUS
    window = [event for event in events if event.occurred_at <= deadline]
    if any(event.available_at > freeze for event in window):
        return Exclusion.LATE
    payments = [event for event in window if event.kind == EventKind.FULL_PAYMENT]
    if any(event.occurred_at <= calculation for event in payments):
        return Exclusion.PRECALCULATION
    if any(event.amount != first.amount or event.currency != first.currency for event in payments) or len(payments) > 1:
        return Exclusion.AMBIGUOUS
    days_from_due = None
    if first.due_at is not None and first.due_available_at is not None and first.due_available_at <= calculation:
        days_from_due = (calculation - _instant(first.due_at)).total_seconds() / 86400
    return P2Row(
        features=P2Features(first.source, first.amount, first.currency,
                            (calculation - t0).total_seconds() / 86400, days_from_due),
        target=int(bool(payments)), source=first.source, obligation_id=first.obligation_id,
        first_rejection_id=first.event_id, subscription_id=first.subscription_id, coverage_id=coverage.evidence_id,
        t0=t0, calculated_at=calculation, outcome_end=deadline,
        label_available_at=max(_instant(coverage.available_at), deadline,
                               *(event.available_at for event in window)),
    )


def build_p2(events: list[EvidenceEvent], coverages: list[Coverage], *, as_of: datetime) -> P2Dataset:
    """One episode per (source/account, obligation), positive and negative equally mature.

    Identical event IDs deduplicate; conflicting versions fail, never last-row-wins.
    Exclusions count obligations, not attempts, and contain no personal identifiers.
    """
    freeze = _instant(as_of)
    unique, proofs = {}, {}
    for event in events:
        if event.event_id in unique and unique[event.event_id] != event:
            raise ValueError("Evidencia duplicada con contenido contradictorio")
        unique[event.event_id] = event
    for coverage in coverages:
        key = (coverage.source, coverage.obligation_id)
        if key in proofs and proofs[key] != coverage:
            raise ValueError("Coberturas contradictorias; seleccione un snapshot verificable")
        proofs[key] = coverage
    groups = defaultdict(list)
    for event in unique.values():
        groups[(event.source, event.obligation_id)].append(event)
    rows, excluded = [], Counter()
    for key, group in groups.items():
        result = _episode(group, proofs.get(key), freeze)
        if isinstance(result, Exclusion):
            excluded[result] += 1
        else:
            rows.append(result)
    return P2Dataset(tuple(sorted(rows, key=lambda row: (row.calculated_at, row.source, row.obligation_id))),
                     tuple(sorted(excluded.items())), freeze)


def eligible_for_fit(row: P1Row | P2Row, *, fit_at: datetime) -> bool:
    """Availability gate only; temporal folds/purging/group isolation still belong to ML-06."""
    cutoff = _instant(fit_at)
    calculation = row.observation.available_at if isinstance(row, P1Row) else row.calculated_at
    return calculation < cutoff and row.label_available_at <= cutoff
