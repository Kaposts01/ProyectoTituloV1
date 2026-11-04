"""Informe de drift (documentacion vs proveedor). Sin red ni BD; todo saneado antes de escribirse."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.read_only_provider_sync import safe_error_message, sanitize_record

_SENSITIVE_KEYS = re.compile(r"(rut|social_id|api_key|secret|signature|authorization|pan|card|token|password)", re.I)
_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b")


@dataclass
class ClaimRecord:
    claim: str
    document: str
    expected: Any
    observed: Any
    matches: bool
    date: str
    http_status: int | None = None
    error_code: str | None = None
    note: str = ""


def scrub(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Quita llaves, firmas, PAN y RUT de cualquier estructura."""
    value = sanitize_record(value)
    if isinstance(value, dict):
        return {k: ("[redacted]" if _SENSITIVE_KEYS.search(str(k)) else scrub(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        text = safe_error_message(Exception(value), secrets) if value else value
        return _JWT.sub("[redacted]", _RUT.sub("[redacted]", text))
    return value


class ClaimRecorder:
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.records: list[ClaimRecord] = []
        self._secrets = tuple(s for s in secrets if s)

    def check(
        self,
        claim_id: str,
        document: str,
        expected: Any,
        observed: Any,
        note: str = "",
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        matches: bool | None = None,
    ) -> ClaimRecord:
        """Registra esperado (doc) vs observado. Nunca falla la prueba por desacuerdo.

        `matches` explicito solo cuando la comparacion no es igualdad simple.
        """
        record = ClaimRecord(
            claim=claim_id,
            document=document,
            expected=scrub(expected, self._secrets),
            observed=scrub(observed, self._secrets),
            matches=(expected == observed) if matches is None else matches,
            date=datetime.now(UTC).isoformat(timespec="seconds"),
            http_status=http_status,
            error_code=error_code,
            note=scrub(note, self._secrets),
        )
        self.records.append(record)
        return record

    def to_markdown(self) -> str:
        lines = ["# Drift VirtualPOS (doc vs sandbox)", "", f"Afirmaciones: {len(self.records)} / discrepancias: "
                 f"{sum(not r.matches for r in self.records)}", "",
                 "| claim | documento | esperado | observado | coincide | fecha | HTTP | error | nota |",
                 "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in self.records:
            cells = [r.claim, r.document, _cell(r.expected), _cell(r.observed), "si" if r.matches else "NO", r.date,
                     str(r.http_status or ""), r.error_code or "", _cell(r.note)]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines) + "\n"

    def write(self, out_dir: Path, now: datetime | None = None) -> tuple[Path, Path]:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"drift-{stamp}.json"
        md_path = out_dir / f"drift-{stamp}.md"
        json_path.write_text(
            json.dumps([asdict(r) for r in self.records], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path


def _cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text.replace("|", r"\|").replace("\n", " ")[:300]
