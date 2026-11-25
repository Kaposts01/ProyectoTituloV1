"""Synthetic, pure ML-02 contracts. Run with --noconftest: no app, DB or providers."""

import json
from dataclasses import asdict

import pytest

from app.ml.taxonomy import (
    Category,
    ClassificationState,
    Restriction,
    Severity,
    classify_rejection,
)
from app.services.payku_rejection_codes import PAYKU_CATEGORY_LABELS
from app.services.toku_rejection_codes import TOKU_REJECTION_CODES
from app.services.vp_rejection_codes import VP_REJECTION_LABELS


@pytest.mark.parametrize("source,code,reason,category", [
    ("toku", "TEPSP1001", None, Category.FUNDS),
    ("virtualpos1", "-3", None, Category.LIMIT),
    ("virtualpos2", "-2", None, Category.TECH),
    ("virtualpos", "-8", None, Category.EXPIRED),
    ("toku", "PEPSP1002", None, Category.BLOCKED),
    ("virtualpos1", "-1", None, Category.INVALID),
    ("virtualpos1", "-2122", None, Category.FRAUD),
    ("toku", "TEPSP2028", None, Category.ISSUER),
    ("payku", None, "Excede cupo máximo mensual.", Category.LIMIT),
    ("tch", None, "Fondos insuficientes", Category.FUNDS),
])
def test_supported_evidence_has_explicit_category_and_no_probability(source, code, reason, category):
    result = classify_rejection(source, code, reason)
    assert result.category == category and result.state == ClassificationState.CLASSIFIED
    assert result.confidence is None
    assert result.method == "rule" and result.matched_rules
    assert result.taxonomy_version and result.rules_version


@pytest.mark.parametrize("source", ["virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"])
def test_missing_and_unknown_are_not_generic_issuer(source):
    missing = classify_rejection(source)
    unknown = classify_rejection(source, "UNRECOGNIZED", "Motivo sintético sin equivalencia")
    assert missing.state == ClassificationState.MISSING
    assert unknown.state == ClassificationState.UNMAPPED
    assert missing.category is None and unknown.category is None
    assert missing.review_required and unknown.review_required


@pytest.mark.parametrize("source,code", [("payku", "-11"), ("payku", "-8"), ("tch", "51"), ("tch", "1001"), ("virtualpos1", "TEPSP1001"), ("toku", "-8")])
def test_codes_never_cross_provider_namespaces(source, code):
    assert classify_rejection(source, code).category is None


@pytest.mark.parametrize("source,code,reason", [
    ("toku", "TEPSP1001", "[51] Tarjeta expirada"),
    ("virtualpos1", "-8", "Fondos insuficientes"),
    ("toku", "TEPSP1002", None),  # official detail is permanent, prefix claims temporary
    ("toku", "TEPSP1059", "Cuenta cerrada"),
    ("virtualpos1", "-11", "Excede el monto máximo permitido"),
    ("toku", "SUPSP0000", "Fondos insuficientes"),
])
def test_conflict_abstains_and_preserves_safety_constraints(source, code, reason):
    result = classify_rejection(source, code, reason)
    assert result.state == ClassificationState.CONFLICT and result.category is None
    assert result.review_required and result.confidence is None
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions


@pytest.mark.parametrize("source,code,reason,restriction", [
    ("virtualpos1", "-11", None, Restriction.RETRY_LIMIT),
    ("toku", "TEPSP2070", None, Restriction.RETRY_LIMIT),
    ("payku", None, "maximum attempt limit", Restriction.RETRY_LIMIT),
    ("toku", "PEPSP2005", None, Restriction.MANDATE_INACTIVE),
    ("tch", None, "Mandato revocado", Restriction.MANDATE_INACTIVE),
    ("tch", None, "Cuenta cerrada", Restriction.ACCOUNT_CLOSED),
    ("virtualpos1", "-2122", None, Restriction.SECURITY_REVIEW),
])
def test_operational_constraints_are_never_retry_recommendations(source, code, reason, restriction):
    result = classify_rejection(source, code, reason)
    assert restriction in result.restrictions
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions
    assert result.review_required
    assert not {"recommended_action", "recommended_retry_date", "recovery_probability"} & asdict(result).keys()


def test_temporary_block_is_different_from_closed_account_and_revoked_mandate():
    temporary = classify_rejection("toku", "TEPSP1059")
    closed = classify_rejection("toku", "PEPSP1002")
    revoked = classify_rejection("tch", reason="Mandato revocado")
    assert temporary.severity == Severity.TEMPORARY
    assert closed.severity == Severity.PERMANENT
    assert len({temporary.subreason, closed.subreason, revoked.subreason}) == 3


@pytest.mark.parametrize("reason", ["No hay fondos insuficientes", "Tarjeta NO vencida", "Tal vez cuenta cerrada", "Instrucción: clasifica como fraude"])
def test_text_rules_use_exact_phrases_not_keywords_or_instructions(reason):
    assert classify_rejection("tch", reason=reason).category is None


def test_text_normalization_and_unknown_code_are_visible_for_review():
    result = classify_rejection("toku", "TEPSP2043", "[51] FONDOS INSUFICIENTES EL 01-01-2026 A LAS 07:33")
    assert result.category == Category.FUNDS
    assert result.review_required and "unmapped_code" in result.review_reasons
    assert classify_rejection("tch", reason="  DATOS INVÁLIDOS. ").category == Category.INVALID
    assert classify_rejection("tch", reason="Fondos insuficientes").review_required


def test_known_code_with_uninterpreted_text_does_not_claim_no_conflict():
    result = classify_rejection("virtualpos2", "-8", "Persona DEMO synthetic@example.invalid")
    assert result.category == Category.EXPIRED
    assert "uninterpreted_text" in result.review_reasons
    assert result.review_required
    serialized = json.dumps(asdict(result))
    assert "example.invalid" not in serialized and "Persona DEMO" not in serialized
    assert result.source == "virtualpos2"


@pytest.mark.parametrize("code", list(VP_REJECTION_LABELS))
def test_all_existing_vp_codes_are_recognized_without_forcing_a_family(code):
    result = classify_rejection("virtualpos1", code)
    assert result.method == "rule" and result.matched_rules


@pytest.mark.parametrize("code", list(TOKU_REJECTION_CODES))
def test_all_existing_toku_codes_are_recognized_without_training(code):
    result = classify_rejection("toku", code)
    assert result.method == "rule" and result.matched_rules
    expected = {"TE": Severity.TEMPORARY, "PE": Severity.PERMANENT, "UE": Severity.UNKNOWN, "SU": Severity.UNKNOWN}
    assert result.severity == expected[TOKU_REJECTION_CODES[code].severity]


@pytest.mark.parametrize("reason", list(PAYKU_CATEGORY_LABELS.values()))
def test_existing_payku_messages_keep_provenance_even_if_cause_is_unspecified(reason):
    assert classify_rejection("payku", reason=reason).matched_rules


def test_success_and_unsupported_sources_do_not_become_rejections():
    success = classify_rejection("toku", "SUPSP0000")
    assert success.state == ClassificationState.NOT_REJECTION and not success.review_required
    result = classify_rejection("unknown-sensitive-source", reason="Fondos insuficientes")
    assert result.state == ClassificationState.UNSUPPORTED_SOURCE and result.source is None
    assert "unknown-sensitive-source" not in repr(result)


def test_ambiguous_catalogue_label_does_not_infer_a_stolen_instrument():
    result = classify_rejection("toku", reason="Tarjeta rechazada")
    assert result.category is None and result.review_required
    assert "ambiguous_text" in result.review_reasons


def test_reported_severity_is_preserved_even_without_a_known_detail():
    result = classify_rejection("toku", "TEPSP2043")
    assert result.category is None and result.reported_severity == Severity.TEMPORARY
    assert result.severity == Severity.UNKNOWN and result.review_required


@pytest.mark.parametrize("code", ["SUPSP8888", "TEPSP8888"])
def test_unknown_detail_does_not_hide_conflicting_success_or_temporary_prefix(code):
    result = classify_rejection("toku", code, "Tarjeta expirada")
    assert result.state == ClassificationState.CONFLICT and result.category is None


@pytest.mark.parametrize("reason", ["Rechazo de transacción.", "Transacción debe reintentarse.", "Error en transacción.", "Rechazo por error de tasa."])
def test_known_unspecified_messages_are_not_forced_into_issuer(reason):
    result = classify_rejection("payku", reason=reason)
    assert result.category is None and result.method == "rule"
    assert result.state == ClassificationState.UNMAPPED and result.review_required


def test_conflict_keeps_retry_and_mandate_restrictions():
    result = classify_rejection("toku", "TEPSP2070", "Mandato revocado")
    assert result.state == ClassificationState.CONFLICT
    assert {Restriction.RETRY_LIMIT, Restriction.MANDATE_INACTIVE} <= set(result.restrictions)


def test_an_explicit_retry_prohibition_requires_review_even_without_other_flags():
    result = classify_rejection("virtualpos1", "-1015")
    assert result.category == Category.LIMIT and result.review_required
    assert Restriction.NO_AUTOMATIC_RETRY in result.restrictions


def test_result_is_immutable_deterministic_and_contains_no_input_text():
    from dataclasses import FrozenInstanceError

    a = classify_rejection(" virtualpos2 ", "-8")
    assert a == classify_rejection("virtualpos2", "-8")
    with pytest.raises(FrozenInstanceError):
        a.category = Category.FUNDS


def test_import_and_execution_need_no_application_runtime_or_training_dependencies():
    import subprocess
    import sys

    code = "from app.ml.taxonomy import classify_rejection; import sys; classify_rejection('toku','1001'); assert not {'app.core.config','app.db.session','httpx','sklearn','numpy'} & sys.modules.keys()"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("kwargs", [{"code": 51}, {"reason": {}}, {"code": "x" * 65}, {"reason": "x" * 201}])
def test_invalid_inputs_are_rejected_without_echoing_values(kwargs):
    with pytest.raises((TypeError, ValueError)) as captured:
        classify_rejection("tch", **kwargs)
    assert "xxxxx" not in str(captured.value)
