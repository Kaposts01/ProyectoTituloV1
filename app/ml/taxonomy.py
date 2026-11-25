"""ML-02: deterministic, conservative reason classification, without I/O or action policy.

Families describe reported evidence, not independently verified causes. Text rules and
business mappings require domain validation. No probability, retry date or permission
is inferred; source input text is deliberately absent from the immutable output.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.services.payku_rejection_codes import (
    PAYKU_CATEGORY_LABELS,
    payku_rejection_category,
    payku_subscription_rejection_status,
)
from app.services.toku_rejection_codes import (
    TOKU_REJECTION_CODES,
    lookup_toku_code,
    normalize_processor_message,
    parse_toku_response_code,
)
from app.services.vp_rejection_codes import VP_REJECTION_LABELS

TAXONOMY_VERSION = "reason-taxonomy-v1-draft"
RULES_VERSION = "reason-rules-v1-draft"
_SOURCES = frozenset({"virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"})


class Category(StrEnum):
    FUNDS = "FUNDS"
    LIMIT = "LIMIT"
    TECH = "TECH"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"
    FRAUD = "FRAUD"
    ISSUER = "ISSUER"


class Severity(StrEnum):
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class ClassificationState(StrEnum):
    CLASSIFIED = "classified"
    UNMAPPED = "unmapped"
    MISSING = "missing"
    CONFLICT = "conflict"
    NOT_REJECTION = "not_rejection"
    UNSUPPORTED_SOURCE = "unsupported_source"


class Restriction(StrEnum):
    NO_AUTOMATIC_RETRY = "no_automatic_retry"
    RETRY_LIMIT = "retry_limit"
    MANDATE_INACTIVE = "mandate_inactive"
    ACCOUNT_CLOSED = "account_closed"
    INSTRUMENT_UNUSABLE = "instrument_unusable"
    SECURITY_REVIEW = "security_review"
    INVALID_STATE = "invalid_state"


@dataclass(frozen=True, slots=True)
class Classification:
    source: str | None
    category: Category | None
    subreason: str | None
    severity: Severity
    reported_severity: Severity | None
    state: ClassificationState
    method: str
    matched_rules: tuple[str, ...]
    restrictions: tuple[Restriction, ...]
    review_reasons: tuple[str, ...]
    review_required: bool
    confidence: None = None
    taxonomy_version: str = TAXONOMY_VERSION
    rules_version: str = RULES_VERSION


@dataclass(frozen=True, slots=True)
class _Rule:
    category: Category | None
    subreason: str
    severity: Severity
    restrictions: tuple[Restriction, ...]


def _rule(category: str | None, subreason: str, severity: str = "unknown", *restrictions: Restriction) -> _Rule:
    flags = set(restrictions)
    if category == "FRAUD":
        flags.add(Restriction.SECURITY_REVIEW)
    if category in {"EXPIRED", "BLOCKED"}:
        flags.add(Restriction.INSTRUMENT_UNUSABLE)
    if flags:
        flags.add(Restriction.NO_AUTOMATIC_RETRY)
    return _Rule(Category(category) if category else None, subreason, Severity(severity), tuple(sorted(flags)))


_VP = {
    "-1": _rule("INVALID", "card_number_invalid"),
    "-2": _rule("TECH", "connection_error"),
    "-3": _rule("LIMIT", "amount_limit"),
    "-4": _rule("INVALID", "expiration_date_invalid"),
    "-5": _rule("FRAUD", "authentication_failed"),
    "-6": _rule("ISSUER", "generic_rejection"),
    "-7": _rule("BLOCKED", "instrument_blocked"),
    "-8": _rule("EXPIRED", "card_expired", "permanent"),
    "-9": _rule("INVALID", "instrument_unsupported"),
    "-10": _rule(None, "transaction_error_unspecified"),
    "-11": _rule("LIMIT", "retry_limit", "unknown", Restriction.RETRY_LIMIT),
    "-1001": _rule(None, "merchant_configuration"),
    "-1002": _rule(None, "transaction_not_pending", "unknown", Restriction.INVALID_STATE),
    "-1003": _rule("LIMIT", "amount_limit"),
    "-1004": _rule(None, "browser_context"),
    "-1005": _rule("FRAUD", "automated_activity_signal"),
    "-1006": _rule(None, "payer_context_unavailable"),
    "-1007": _rule(None, "country_restriction"),
    "-1009": _rule("LIMIT", "merchant_daily_amount_limit"),
    "-1010": _rule("LIMIT", "merchant_daily_transaction_limit"),
    "-1011": _rule("BLOCKED", "client_or_device_restricted"),
    "-1013": _rule("INVALID", "foreign_instrument_unsupported"),
    "-1014": _rule("LIMIT", "retry_limit", "unknown", Restriction.RETRY_LIMIT),
    "-1015": _rule("LIMIT", "instrument_daily_transaction_limit", "unknown", Restriction.NO_AUTOMATIC_RETRY),
    "-1016": _rule("INVALID", "instrument_not_enabled"),
    "-1017": _rule("FRAUD", "security_validation_failed"),
    "-1018": _rule(None, "user_cancelled"),
    "-2122": _rule("FRAUD", "acquirer_security_signal"),
}

_TOKU = {
    "0000": _rule(None, "success"),
    "1001": _rule("FUNDS", "insufficient_funds", "temporary"),
    "1002": _rule("BLOCKED", "account_closed", "permanent", Restriction.ACCOUNT_CLOSED),
    "1007": _rule("FRAUD", "verification_failed", "permanent"),
    "1008": _rule("ISSUER", "generic_rejection", "temporary"),
    "1010": _rule("EXPIRED", "card_expired", "permanent"),
    "1011": _rule("BLOCKED", "instrument_stolen", "permanent", Restriction.SECURITY_REVIEW),
    "1017": _rule("INVALID", "instrument_invalid", "permanent"),
    "1019": _rule("BLOCKED", "instrument_blocked", "permanent"),
    "1059": _rule("BLOCKED", "account_temporarily_blocked", "temporary"),
    "1062": _rule("INVALID", "expiration_date_invalid", "temporary"),
    "1073": _rule("BLOCKED", "instrument_temporarily_blocked", "temporary"),
    "2005": _rule("BLOCKED", "mandate_removed", "permanent", Restriction.MANDATE_INACTIVE),
    "2006": _rule("INVALID", "verification_code_invalid", "temporary"),
    "2008": _rule("TECH", "processing_error", "temporary"),
    "2009": _rule("INVALID", "parameter_validation", "temporary"),
    "2028": _rule("ISSUER", "generic_rejection", "temporary"),
    "2035": _rule("INVALID", "instrument_unsupported", "temporary"),
    "2063": _rule("EXPIRED", "card_expired", "permanent"),
    "2070": _rule("LIMIT", "retry_limit", "temporary", Restriction.RETRY_LIMIT),
    "2106": _rule(None, "issuer_unknown", "permanent"),
    "4007": _rule("TECH", "acquirer_error", "temporary"),
    "5408": _rule("TECH", "external_processing_error", "temporary"),
    "9999": _rule(None, "unexpected_error"),
}

_PAYKU = {
    "REJECT": _rule(None, "transaction_rejection_unspecified"),
    "RETRY": _rule(None, "retry_instruction_without_cause", "unknown", Restriction.NO_AUTOMATIC_RETRY),
    "ERROR": _rule(None, "transaction_error_unspecified"),
    "RATE": _rule(None, "rate_error_unspecified"),
    "MONTHLY_LIMIT": _rule("LIMIT", "monthly_limit"),
    "DAILY_LIMIT": _rule("LIMIT", "daily_amount_limit"),
    "MCC": _rule("INVALID", "merchant_category_restricted"),
}

# Exact semantic phrases are draft text rules, not an official TCH bank-code catalogue.
_PHRASES = {
    "fondos insuficientes": _rule("FUNDS", "insufficient_funds"),
    "saldo insuficiente": _rule("FUNDS", "insufficient_funds"),
    "limite de monto excedido": _rule("LIMIT", "amount_limit"),
    "excede el monto maximo permitido": _rule("LIMIT", "amount_limit"),
    "limite de reintentos excedido": _rule("LIMIT", "retry_limit", "unknown", Restriction.RETRY_LIMIT),
    "error de conexion": _rule("TECH", "connection_error"),
    "tarjeta vencida": _rule("EXPIRED", "card_expired", "permanent"),
    "tarjeta expirada": _rule("EXPIRED", "card_expired", "permanent"),
    "cuenta cerrada": _rule("BLOCKED", "account_closed", "permanent", Restriction.ACCOUNT_CLOSED),
    "mandato revocado": _rule("BLOCKED", "mandate_revoked", "permanent", Restriction.MANDATE_INACTIVE),
    "bloqueo temporal": _rule("BLOCKED", "instrument_temporarily_blocked", "temporary"),
    "datos invalidos": _rule("INVALID", "data_invalid"),
    "sospecha de fraude": _rule("FRAUD", "security_signal"),
    "rechazo del banco emisor": _rule("ISSUER", "generic_rejection"),
}


def _text_key(value: str) -> str:
    folded = "".join(char for char in unicodedata.normalize("NFKD", value).casefold() if not unicodedata.combining(char))
    return re.sub(r"[\s.,:;]+", " ", folded).strip()


def _text_rule(source: str, reason: str) -> tuple[_Rule | None, str | None, str | None]:
    normalized = normalize_processor_message(reason)
    key = _text_key(normalized.text) if normalized else ""
    if source == "payku":
        category = payku_rejection_category(reason)
        if category:
            return _PAYKU[category], f"payku:message:{category}", None
        for category, message in PAYKU_CATEGORY_LABELS.items():
            if _text_key(message) == key:
                return _PAYKU[category], f"payku:catalogue_label:{category}", None
        status = payku_subscription_rejection_status(reason)
        if status:
            rule = _rule("LIMIT", "retry_limit", "unknown", Restriction.RETRY_LIMIT) if status == "maximum attempt limit" else _rule(None, "subscription_rejection_unspecified")
            return rule, f"payku:subscription_status:{status.replace(' ', '_')}", None
    catalogue = VP_REJECTION_LABELS if source.startswith("virtualpos") else {code: item.message for code, item in TOKU_REJECTION_CODES.items()} if source == "toku" else {}
    rules = _VP if source.startswith("virtualpos") else _TOKU
    candidates = {rules[code] for code, message in catalogue.items() if code in rules and _text_key(message) == key}
    if len(candidates) > 1:
        return None, None, "ambiguous_text"
    if candidates:
        rule = candidates.pop()
        return rule, f"{source}:catalogue_text:{rule.subreason}", None
    if key in _PHRASES:
        rule = _PHRASES[key]
        return rule, f"{source}:phrase:{rule.subreason}", "draft_text_rule"
    return None, None, None


def _incompatible(a: _Rule, b: _Rule) -> bool:
    if a.subreason == "success" or b.subreason == "success":
        return a.subreason != b.subreason
    if a.category is not None and b.category is not None and a.category != b.category:
        return True
    if a.severity != Severity.UNKNOWN and b.severity != Severity.UNKNOWN and a.severity != b.severity:
        return True
    # Do not hide a retry cap or a different blocked entity behind the same family.
    return a.category == b.category and a.category in {Category.LIMIT, Category.BLOCKED} and a.subreason != b.subreason


def classify_rejection(source: str, code: str | None = None, reason: str | None = None) -> Classification:
    """Classify reported evidence only; no action is authorized by this result.

    Reason is bounded to 200 characters (the existing normalizer's full-text limit),
    so truncation cannot hide conflicting evidence. Inputs are never echoed.
    """
    for value, maximum in ((source, 32), (code, 64), (reason, 200)):
        if value is not None and not isinstance(value, str):
            raise TypeError("La evidencia debe ser texto o nula.")
        if value is not None and len(value) > maximum:
            raise ValueError("La evidencia excede el limite; requiere preparacion revisada.")
    source = (source or "").strip().casefold()
    code, reason = (code or "").strip(), (reason or "").strip()
    supported = source in _SOURCES
    primary, primary_id, prefix_conflict = None, None, False
    parsed = parse_toku_response_code(code) if source == "toku" else None
    reported_severity = {"TE": Severity.TEMPORARY, "PE": Severity.PERMANENT, "UE": Severity.UNKNOWN}.get(parsed.severity) if parsed else None
    if supported and source.startswith("virtualpos") and code in VP_REJECTION_LABELS:
        primary, primary_id = _VP.get(code), f"virtualpos:code:{code}"
    elif source == "toku" and (entry := lookup_toku_code(code)):
        primary, primary_id = _TOKU.get(entry.detail), f"toku:detail:{entry.detail}"
        prefix_conflict = parsed is not None and parsed.severity != entry.severity
    elif source == "payku" and code in PAYKU_CATEGORY_LABELS:
        primary, primary_id = _PAYKU.get(code), f"payku:category:{code}"
    secondary, secondary_id, text_review = _text_rule(source, reason) if supported and reason else (None, None, None)
    if parsed and secondary:
        if parsed.severity == "SU" and secondary.subreason != "success":
            prefix_conflict = True
        elif reported_severity not in {None, Severity.UNKNOWN} and secondary.severity != Severity.UNKNOWN and reported_severity != secondary.severity:
            prefix_conflict = True
    rules = [rule for rule in (primary, secondary) if rule is not None]
    matched = tuple(identifier for rule, identifier in ((primary, primary_id), (secondary, secondary_id)) if rule is not None and identifier)
    flags = {flag for rule in rules for flag in rule.restrictions}
    review = {text_review} if text_review else set()
    if code and primary is None:
        review.add("unmapped_code")
    if reason and secondary is None:
        review.add("uninterpreted_text")
    if source == "tch" and secondary:
        review.add("domain_validation_pending")
    conflict = prefix_conflict or (primary is not None and secondary is not None and _incompatible(primary, secondary))
    chosen = primary or secondary
    if not supported:
        state = ClassificationState.UNSUPPORTED_SOURCE
    elif conflict:
        state = ClassificationState.CONFLICT
        review.add("conflicting_evidence")
    elif chosen and chosen.subreason == "success":
        state = ClassificationState.NOT_REJECTION
    elif chosen and chosen.category is not None:
        state = ClassificationState.CLASSIFIED
    else:
        state = ClassificationState.UNMAPPED if code or reason else ClassificationState.MISSING
    if state != ClassificationState.CLASSIFIED:
        flags.add(Restriction.NO_AUTOMATIC_RETRY)
    needs_review = bool(review or state not in {ClassificationState.CLASSIFIED, ClassificationState.NOT_REJECTION}
                        or (flags and state != ClassificationState.NOT_REJECTION))
    return Classification(
        source=source if supported else None,
        category=chosen.category if chosen and state == ClassificationState.CLASSIFIED else None,
        subreason=chosen.subreason if chosen and not conflict else None,
        severity=chosen.severity if chosen and not conflict else Severity.UNKNOWN,
        reported_severity=reported_severity,
        state=state, method="rule" if matched else "unmapped", matched_rules=matched,
        restrictions=tuple(sorted(flags)), review_reasons=tuple(sorted(review)),
        review_required=needs_review,
    )
