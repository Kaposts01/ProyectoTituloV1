"""Synthetic examples only: privacy gates, contextual keys and bounded CSV contracts."""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.ml.annotation_contract import (
    AnnotationContext,
    Decision,
    Rationale,
    ReviewRequest,
    prepare_context,
    read_requests_csv,
    write_requests_csv,
)
from app.ml.taxonomy import Category, Severity


def context(**overrides):
    values = dict(source="toku", resource_type="payment", processor="psp",
                  reason="[51] Fondos insuficientes", privacy_reviewed=True)
    return prepare_context(**(values | overrides))


def command(**overrides):
    values = dict(context=context(), request_id=uuid4(), expected_revision=0,
                  decision=Decision.DRAFT, category=Category.FUNDS,
                  severity=Severity.TEMPORARY, rationale=Rationale.ANNOTATION)
    return ReviewRequest(**(values | overrides))


def test_context_retains_processor_code_and_hides_text_in_repr():
    result = context()
    assert result.processor_code == "51"
    assert result.normalized_text == "Fondos insuficientes"
    assert "Fondos" not in repr(result)
    assert context(reason="[54] Fondos insuficientes") != result
    for changes in ({"source": "virtualpos1"}, {"processor": "bank-12"}, {"resource_type": "charge"}, {"code": "-11"}):
        assert context(**changes) != result
    assert context(source="virtualpos1") != context(source="virtualpos2")


@pytest.mark.parametrize("changes", [
    {"privacy_reviewed": False}, {"source": "virtualpos"}, {"processor": ""},
    {"reason": ""}, {"reason": "x" * 201}, {"reason": "=HYPERLINK(test)"},
    {"reason": "Correo prueba@example.invalid"}, {"reason": "RUT 11111111-1"},
    {"reason": "PAN 4111111111111111"}, {"reason": "CVV 123"},
    {"reason": "token: secreto"}, {"reason": "http://example.invalid"},
    {"reason": "\uff0bcomando"}, {"code": "4111111111111111"},
    {"reason": "Texto\u202eoculto"}, {"code": "\uff11\uff12"},
])
def test_sensitive_ambiguous_or_unreviewed_inputs_are_rejected_without_echo(changes):
    with pytest.raises(ValueError) as error:
        context(**changes)
    assert "example.invalid" not in str(error.value)
    assert "4111111111111111" not in str(error.value)


def test_versions_are_explicit_and_unknown_version_is_not_silently_reused():
    with pytest.raises(ValueError, match="Version"):
        replace(context(), normalization_version="future-v2")
    assert context(reason="[51] Fondos insuficientes 01-10-2025 07:33").normalized_text == "Fondos insuficientes"
    assert context(reason="", code="-11").normalized_text == ""
    for value in ("Fondos  insuficientes", "[ABC] Sin fondos"):
        with pytest.raises(ValueError, match="normalizada"):
            replace(context(), normalized_text=value)


def test_csv_roundtrip_and_identity_is_not_supplied_by_file():
    requests = [command(), command(context=context(source="virtualpos1", code="-11"))]
    content = write_requests_csv(requests)
    assert read_requests_csv(content) == requests
    assert "actor_id" not in content
    assert "privacy_reviewed" in content


@pytest.mark.parametrize("transform", [
    lambda value: value.replace("source,", "actor_id,", 1),
    lambda value: value.replace("true,", "false,"),
    lambda value: value.replace("Fondos insuficientes", "=malicioso"),
    lambda value: value.replace("draft,FUNDS", "approved,"),
    lambda value: value + "fila,incompleta\n",
    lambda value: value.replace("expected_revision,", "source,", 1),
])
def test_entire_csv_validated_before_any_mutation(transform):
    with pytest.raises(ValueError):
        read_requests_csv(transform(write_requests_csv([command()])))


def test_csv_bounds_and_invalid_review_contract():
    with pytest.raises(ValueError):
        read_requests_csv("x" * 1_000_001)
    with pytest.raises(ValueError):
        write_requests_csv([command()] * 1001)
    with pytest.raises(ValueError):
        command(expected_revision=-1)
    with pytest.raises(ValueError):
        command(decision=Decision.ABSTAINED, rationale=Rationale.INSUFFICIENT)
    with pytest.raises(ValueError):
        command(decision=Decision.APPROVED, category=None, rationale=Rationale.REVIEW)
    with pytest.raises(ValueError, match="Cabecera"):
        read_requests_csv('"cabecera sin cierre')


def test_direct_context_requires_review_even_if_normalized():
    with pytest.raises(ValueError):
        AnnotationContext(source="tch", resource_type="charge", processor="bank-12", normalized_text="Sin fondos")
