"""ML-03 contracts: reviewed generic text only; never infer a human label from rules."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.ml.taxonomy import TAXONOMY_VERSION, Category, Severity
from app.services.toku_rejection_codes import normalize_processor_message

NORMALIZATION_VERSION = "reason-context-v1"


class Decision(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    ABSTAINED = "abstained"
    WITHDRAWN = "withdrawn"


class Rationale(StrEnum):
    ANNOTATION = "annotation"
    CORRECTION = "correction"
    REVIEW = "independent_review"
    INSUFFICIENT = "insufficient_evidence"
    CONFLICT = "conflicting_evidence"
    WITHDRAWAL = "withdrawal"


def _token(value: str, pattern: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("Identificador de contexto invalido")
    return value


@dataclass(frozen=True, slots=True)
class AnnotationContext:
    source: str
    resource_type: str
    processor: str
    code: str = ""
    processor_code: str = ""
    normalized_text: str = field(default="", repr=False)
    normalization_version: str = NORMALIZATION_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    privacy_reviewed: bool = False

    def __post_init__(self) -> None:
        if self.source not in {"virtualpos1", "virtualpos2", "toku", "payku", "tch"}:
            raise ValueError("Se requiere un proveedor y cuenta concretos")
        if self.resource_type not in {"charge", "payment", "transaction", "subscription_state"}:
            raise ValueError("Recurso no admitido")
        _token(self.processor, r"[a-z][a-z0-9_-]{0,39}")
        _token(self.code, r"(?:-?[0-9]{1,6}|[A-Z][A-Z0-9_-]{0,31})?")
        _token(self.processor_code, r"[A-Z0-9]{0,3}")
        if self.normalization_version != NORMALIZATION_VERSION or self.taxonomy_version != TAXONOMY_VERSION:
            raise ValueError("Version no soportada; se requiere migracion explicita del contexto")
        if self.privacy_reviewed is not True:
            raise ValueError("Se requiere revision humana previa de privacidad")
        value = self.normalized_text
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError("Glosa revisada invalida")
        if value != unicodedata.normalize("NFKC", value).strip():
            raise ValueError("Glosa no normalizada")
        normalized = normalize_processor_message(value)
        if normalized and (normalized.text != value or normalized.processor_code is not None):
            raise ValueError("Glosa no normalizada; separe los codigos del texto")
        # Conservative gate, not anonymization: names and other PII still need human review.
        if (re.search(r"[\d@=<>\x00-\x1f\x7f]|https?://|www\.|(?:api.?key|token|password|secret)\s*[:=]", value, re.I)
                or value.startswith(("+", "-"))
                or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)):
            raise ValueError("Glosa requiere saneamiento y nueva revision de privacidad")
        if not value and not self.code and not self.processor_code:
            raise ValueError("Se requiere evidencia de rechazo")


def prepare_context(*, source: str, resource_type: str, processor: str,
                    reason: str, code: str = "", privacy_reviewed: bool = False) -> AnnotationContext:
    """Caller must first remove personal data; date removal does not anonymize text."""
    if not isinstance(reason, str) or len(reason) > 200:
        raise ValueError("Glosa revisada invalida")
    normalized = normalize_processor_message(unicodedata.normalize("NFKC", reason).strip())
    return AnnotationContext(
        source=source, resource_type=resource_type, processor=processor, code=code,
        processor_code=(normalized.processor_code or "") if normalized else "",
        normalized_text=normalized.text if normalized else "",
        privacy_reviewed=privacy_reviewed,
    )


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    context: AnnotationContext
    request_id: UUID
    expected_revision: int
    decision: Decision
    category: Category | None
    severity: Severity
    rationale: Rationale

    def __post_init__(self) -> None:
        if not isinstance(self.context, AnnotationContext) or not isinstance(self.request_id, UUID):
            raise ValueError("Solicitud invalida")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("Revision esperada invalida")
        if not isinstance(self.decision, Decision) or not isinstance(self.severity, Severity) or not isinstance(self.rationale, Rationale):
            raise ValueError("Decision invalida")
        if self.category is not None and not isinstance(self.category, Category):
            raise ValueError("Categoria invalida")
        allowed = {
            Decision.DRAFT: {Rationale.ANNOTATION, Rationale.CORRECTION},
            Decision.APPROVED: {Rationale.REVIEW},
            Decision.REJECTED: {Rationale.CONFLICT},
            Decision.ABSTAINED: {Rationale.INSUFFICIENT, Rationale.CONFLICT},
            Decision.WITHDRAWN: {Rationale.WITHDRAWAL},
        }
        if self.rationale not in allowed[self.decision]:
            raise ValueError("Motivo incompatible con la decision")
        if self.decision == Decision.APPROVED and self.category is None:
            raise ValueError("La aprobacion requiere categoria")
        if self.decision not in {Decision.DRAFT, Decision.APPROVED} and (
            self.category is not None or self.severity != Severity.UNKNOWN
        ):
            raise ValueError("Una abstencion, rechazo o retiro no establece una etiqueta")


CONTEXT_COLUMNS = (
    "source", "resource_type", "processor", "code", "processor_code",
    "normalized_text", "normalization_version", "taxonomy_version",
)
CSV_COLUMNS = (*CONTEXT_COLUMNS, "privacy_reviewed", "request_id", "expected_revision",
               "decision", "category", "severity", "rationale")


def write_requests_csv(requests: list[ReviewRequest]) -> str:
    """Export commands, never reviewer identity or historical-authorship claims."""
    if len(requests) > 1000:
        raise ValueError("Lote demasiado grande")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for request in requests:
        row = {key: getattr(request.context, key) for key in CONTEXT_COLUMNS}
        row.update(privacy_reviewed="true", request_id=str(request.request_id),
                   expected_revision=request.expected_revision, decision=request.decision.value,
                   category=request.category.value if request.category else "",
                   severity=request.severity.value, rationale=request.rationale.value)
        writer.writerow(row)
    return output.getvalue()


def read_requests_csv(content: str) -> list[ReviewRequest]:
    """Validate the whole bounded file before callers perform any mutation."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("Archivo demasiado grande o invalido")
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    try:
        valid_header = reader.fieldnames == list(CSV_COLUMNS)
    except csv.Error:
        raise ValueError("Cabecera CSV invalida") from None
    if not valid_header:
        raise ValueError("Cabecera CSV invalida")
    requests = []
    try:
        for row in reader:
            if len(requests) >= 1000 or None in row or None in row.values() or row["privacy_reviewed"] != "true":
                raise ValueError("Fila invalida")
            context = AnnotationContext(**{key: row[key] for key in CONTEXT_COLUMNS}, privacy_reviewed=True)
            requests.append(ReviewRequest(
                context=context, request_id=UUID(row["request_id"]),
                expected_revision=int(row["expected_revision"]), decision=Decision(row["decision"]),
                category=Category(row["category"]) if row["category"] else None,
                severity=Severity(row["severity"]), rationale=Rationale(row["rationale"]),
            ))
    except (ValueError, TypeError, csv.Error):
        raise ValueError(f"CSV invalido cerca de fila {reader.line_num}; revise el archivo sin registrar sus valores") from None
    return requests
