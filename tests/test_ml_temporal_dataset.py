"""ML-04 temporal contracts, using deterministic synthetic evidence only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.ml.annotation_contract import Decision, prepare_context
from app.ml.taxonomy import Category
from app.ml.temporal_dataset import (
    Coverage,
    EventKind,
    EvidenceEvent,
    Exclusion,
    P1Observation,
    P1Review,
    build_p1,
    build_p2,
    eligible_for_fit,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
END = T0 + timedelta(days=30)
FREEZE = END + timedelta(days=5)
A, B = UUID(int=1), UUID(int=2)


def event(**changes):
    values = dict(event_id=UUID(int=10), source="virtualpos1", obligation_id=UUID(int=100),
                  kind=EventKind.REJECTION, occurred_at=T0, available_at=T0 + timedelta(hours=1),
                  amount=Decimal("1000"), currency="CLP", link_verified=True,
                  subscription_id=UUID(int=200), due_at=T0 - timedelta(days=2), due_available_at=T0)
    return EvidenceEvent(**(values | changes))


def payment(**changes):
    return event(**(dict(event_id=UUID(int=11), kind=EventKind.FULL_PAYMENT,
                        occurred_at=T0 + timedelta(days=20), available_at=T0 + timedelta(days=21)) | changes))


def coverage(**changes):
    values = dict(evidence_id=UUID(int=300), source="virtualpos1", obligation_id=UUID(int=100),
                  observed_from=T0, observed_through=END, available_at=END + timedelta(hours=1),
                  complete=True, reconciled=True, history_complete=True)
    return Coverage(**(values | changes))


def result(events=None, proof=None, as_of=FREEZE):
    return build_p2(events if events is not None else [event()], [proof or coverage()], as_of=as_of)


def excluded(expected, **kwargs):
    dataset = result(**kwargs)
    assert dataset.rows == ()
    assert dict(dataset.exclusions) == {expected: 1}


def context(**changes):
    return prepare_context(**(dict(source="toku", resource_type="payment", processor="psp",
                                   reason="Sin fondos", privacy_reviewed=True) | changes))


def observation(**changes):
    return P1Observation(**(dict(observation_id=UUID(int=400), context=context(),
                                occurred_at=T0, available_at=T0 + timedelta(hours=1)) | changes))


def reviews():
    return [P1Review(context(), 1, Decision.DRAFT, Category.FUNDS, T0 + timedelta(days=1), A),
            P1Review(context(), 2, Decision.APPROVED, Category.FUNDS, T0 + timedelta(days=2), B)]


def test_positive_negative_maturity_and_feature_whitelist():
    positive = result([event(), payment()]).rows[0]
    negative = result().rows[0]
    assert (positive.target, negative.target) == (1, 0)
    assert positive.label_available_at == coverage().available_at
    assert positive.features == negative.features
    assert positive.features.model_features() == {
        "source": "virtualpos1", "amount": Decimal("1000"), "currency": "CLP",
        "elapsed_days": 1 / 24, "days_from_due": 2 + 1 / 24,
    }
    assert not eligible_for_fit(positive, fit_at=END)
    assert eligible_for_fit(positive, fit_at=FREEZE)
    for events in ([event()], [event(), payment()]):
        excluded(Exclusion.IMMATURE, events=events, as_of=END - timedelta(seconds=1))


@pytest.mark.parametrize("when,target", [(END, 1), (END + timedelta(seconds=1), 0)])
def test_exact_inclusive_30_day_boundary(when, target):
    assert result([event(), payment(occurred_at=when, available_at=when)]).rows[0].target == target


def test_repeated_attempts_and_duplicate_ingestion_do_not_multiply_episodes():
    retry = event(event_id=UUID(int=12), occurred_at=T0 + timedelta(days=3), available_at=T0 + timedelta(days=3))
    events = [payment(), retry, event(), event()]
    dataset = result(events)
    assert len(dataset.rows) == 1 and dataset.rows[0].target == 1
    assert result(list(reversed(events))) == dataset
    with pytest.raises(ValueError, match="contradictorio"):
        result([event(), replace(event(), amount=Decimal("2000"))])


def test_payments_cannot_cross_obligation_account_or_subscription_by_similarity():
    for changes in ({"obligation_id": UUID(int=101)}, {"source": "virtualpos2"}):
        dataset = result([event(), payment(**changes)])
        assert len(dataset.rows) == 1 and dataset.rows[0].target == 0
        assert dict(dataset.exclusions) == {Exclusion.NO_REJECTION: 1}
    excluded(Exclusion.AMBIGUOUS, events=[event(), payment(subscription_id=UUID(int=201))])


@pytest.mark.parametrize("change,reason", [
    ({"occurred_at": None}, Exclusion.MISSING_CLOCK),
    ({"available_at": None}, Exclusion.MISSING_CLOCK),
    ({"link_verified": False}, Exclusion.LINK),
    ({"amount": None}, Exclusion.AMOUNT),
    ({"currency": None}, Exclusion.AMOUNT),
    ({"currency": "USD"}, Exclusion.AMOUNT),
    ({"amount": Decimal("1000.50")}, Exclusion.AMOUNT),
    ({"available_at": END}, Exclusion.TOO_LATE),
])
def test_unusable_rejection_never_becomes_negative(change, reason):
    excluded(reason, events=[event(**change)])


@pytest.mark.parametrize("change,reason", [
    ({"history_complete": False}, Exclusion.ORIGIN),
    ({"complete": False}, Exclusion.COVERAGE),
    ({"reconciled": False}, Exclusion.COVERAGE),
    ({"observed_from": T0 + timedelta(seconds=1)}, Exclusion.COVERAGE),
    ({"observed_through": END - timedelta(seconds=1)}, Exclusion.COVERAGE),
    ({"available_at": FREEZE + timedelta(seconds=1)}, Exclusion.COVERAGE),
])
def test_coverage_is_required_for_both_outcomes(change, reason):
    for events in ([event()], [event(), payment()]):
        excluded(reason, events=events, proof=coverage(**change))
    assert build_p2([event()], [], as_of=FREEZE).exclusions == ((Exclusion.ORIGIN, 1),)


@pytest.mark.parametrize("kind", [EventKind.PARTIAL, EventKind.REVERSAL, EventKind.AMBIGUOUS])
def test_unapproved_partial_and_net_payment_policies_abstain(kind):
    excluded(Exclusion.AMBIGUOUS, events=[event(), payment(kind=kind)])


def test_late_or_already_resolved_payment_is_not_a_negative():
    excluded(Exclusion.LATE, events=[event(), payment(available_at=FREEZE + timedelta(days=1))])
    excluded(Exclusion.PRECALCULATION, events=[event(), payment(occurred_at=T0, available_at=T0 + timedelta(minutes=1))])
    excluded(Exclusion.AMBIGUOUS, events=[event(), payment(amount=Decimal("999"))])
    excluded(Exclusion.AMBIGUOUS, events=[event(), payment(currency="USD")])
    excluded(Exclusion.AMBIGUOUS, events=[event(), payment(), payment(event_id=UUID(int=12))])


def test_first_rejection_is_never_arbitrarily_picked_or_backdated():
    excluded(Exclusion.AMBIGUOUS, events=[event(), event(event_id=UUID(int=12))])
    excluded(Exclusion.AMBIGUOUS, events=[event(available_at=T0 + timedelta(days=3)),
             event(event_id=UUID(int=12), occurred_at=T0 + timedelta(days=1), available_at=T0 + timedelta(days=1))])
    excluded(Exclusion.AMBIGUOUS, events=[event(), event(event_id=UUID(int=12),
             occurred_at=T0 + timedelta(days=1), available_at=T0 + timedelta(days=1), amount=Decimal("2000"))])


def test_future_facts_do_not_enter_features_and_unknown_is_not_zero():
    initial = result().rows[0]
    unknown_due = result([event(due_available_at=T0 + timedelta(days=2))]).rows[0]
    missing_due = result([event(due_at=None)]).rows[0]
    assert unknown_due.features.days_from_due is None and missing_due.features.days_from_due is None
    later = event(event_id=UUID(int=12), occurred_at=FREEZE + timedelta(days=1), available_at=FREEZE + timedelta(days=1))
    assert result([event(), later]).rows[0].features == initial.features
    assert result([event(), payment()]).rows[0].features == initial.features
    delayed = result([event(available_at=T0 + timedelta(days=5))]).rows[0]
    assert delayed.features.elapsed_days == 5 and delayed.outcome_end == END


def test_timezone_offsets_preserve_instants_and_elapsed_horizon():
    chile_offset = timezone(timedelta(hours=-3))
    source = event(occurred_at=T0.astimezone(chile_offset), available_at=event().available_at.astimezone(chile_offset))
    row = result([source]).rows[0]
    assert row.t0.tzinfo == UTC and row.outcome_end == END
    assert row.outcome_end - row.t0 == timedelta(hours=720)


@pytest.mark.parametrize("changes", [
    {"occurred_at": T0.replace(tzinfo=None)}, {"occurred_at": "2026-01"},
    {"amount": 1000.0}, {"amount": Decimal("NaN")}, {"amount": Decimal("-1")},
    {"source": "virtualpos"}, {"obligation_id": "external-person-id"}, {"currency": "unknown"},
    {"available_at": T0 - timedelta(seconds=1)},
])
def test_invalid_contracts_fail_without_echoing_values(changes):
    with pytest.raises(ValueError) as error:
        event(**changes)
    assert "external-person-id" not in str(error.value)


def test_conflicting_coverage_is_not_last_row_wins():
    with pytest.raises(ValueError, match="contradictorias"):
        build_p2([event()], [coverage(), coverage(complete=False)], as_of=FREEZE)
    assert result() == build_p2([event()], [coverage(), coverage()], as_of=FREEZE)


def test_p1_latest_review_and_label_clock_control_eligibility():
    obs, history = observation(), reviews()
    dataset = build_p1([obs, obs], history, as_of=FREEZE, review_history_complete=True)
    assert len(dataset.rows) == 1
    row = dataset.rows[0]
    assert row.target == Category.FUNDS and row.label_revision == 2
    assert row.model_features() == {"source": "toku", "resource_type": "payment", "processor": "psp",
                                    "code": "", "processor_code": "", "normalized_text": "Sin fondos"}
    assert not eligible_for_fit(row, fit_at=T0 + timedelta(days=1))
    assert eligible_for_fit(row, fit_at=T0 + timedelta(days=3))
    withdrawn = P1Review(context(), 3, Decision.WITHDRAWN, None, T0 + timedelta(days=3), A)
    assert not build_p1([obs], [*history, withdrawn], as_of=FREEZE, review_history_complete=True).rows
    assert build_p1([obs], [*history, withdrawn], as_of=T0 + timedelta(days=2), review_history_complete=True).rows


def test_p1_correction_abstention_missing_labels_and_future_observations():
    for decision in (Decision.DRAFT, Decision.ABSTAINED, Decision.REJECTED):
        history = [*reviews(), P1Review(context(), 3, decision, None, T0 + timedelta(days=3), A)]
        dataset = build_p1([observation()], history, as_of=FREEZE, review_history_complete=True)
        assert dataset.exclusions == (("latest_label_not_approved", 1),)
    dataset = build_p1([observation(context=context(processor="bank-12"))], reviews(), as_of=FREEZE, review_history_complete=True)
    assert dataset.exclusions == (("no_label_at_cutoff", 1),)
    dataset = build_p1([observation(available_at=FREEZE + timedelta(days=1))], reviews(), as_of=FREEZE, review_history_complete=True)
    assert dataset.exclusions == (("observation_after_cutoff", 1),)


def test_p1_history_must_be_complete_independent_and_consistent():
    with pytest.raises(ValueError, match="invalida"):
        replace(reviews()[1], context=context(processor="unresolved"))
    with pytest.raises(ValueError, match="completo"):
        build_p1([observation()], reviews(), as_of=FREEZE)
    bad_histories = [reviews()[1:], [replace(reviews()[0], decision=Decision.APPROVED)],
                     [reviews()[0], replace(reviews()[1], actor_id=A)],
                     [reviews()[0], replace(reviews()[1], category=Category.TECH)],
                     [reviews()[0], replace(reviews()[1], reviewed_at=T0)]]
    for history in bad_histories:
        with pytest.raises(ValueError):
            build_p1([observation()], history, as_of=FREEZE, review_history_complete=True)
    with pytest.raises(ValueError, match="contradictorias"):
        build_p1([observation(), observation(occurred_at=T0 - timedelta(hours=1))], reviews(), as_of=FREEZE, review_history_complete=True)


def test_no_personal_ids_or_final_outcomes_in_model_inputs():
    row = result([event(), payment()]).rows[0]
    features = row.features.model_features()
    assert not {"target", "obligation_id", "subscription_id", "event_id", "coverage_id", "label_available_at"} & features.keys()
    assert str(event().obligation_id) not in repr(row)
    assert build_p2([], [], as_of=FREEZE).rows == ()
    with pytest.raises(ValueError):
        event(amount=Decimal("1E+30"))
