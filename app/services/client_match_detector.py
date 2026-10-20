"""Detector de candidatos de match cross-canal (EPIC-C).

Escanea core_client_attributes buscando pares de CoreClient de fuentes distintas
que comparten el mismo valor normalizado de RUT o email. Inserta candidatos en
client_match_candidates para revisión manual; NO realiza merges (ADR-001).

Niveles de evidencia (ADR-001 §Matching policy):
  B → mismo RUT válido con checksum correcto, fuentes distintas.
  C → mismo email normalizado, fuentes distintas (sin RUT que lo confirme).

Idempotencia: UNIQUE (client_id_a, client_id_b) con ON CONFLICT DO NOTHING.
client_id_a < client_id_b siempre (invariante del par ordenado).
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.core import ClientMatchCandidate

logger = logging.getLogger(__name__)

# ── normalización ────────────────────────────────────────────────────────────


def _normalize_rut(raw: str) -> str | None:
    """Devuelve el RUT en formato XXXXXXXXX-D (sin puntos) o None si es inválido."""
    clean = re.sub(r"[\s.]", "", raw.strip().upper())
    if not re.match(r"^\d{6,8}-[\dK]$", clean):
        return None
    body, dv = clean.rsplit("-", 1)
    # Validar dígito verificador
    digits = list(map(int, reversed(body)))
    factors = [2, 3, 4, 5, 6, 7]
    total = sum(d * factors[i % 6] for i, d in enumerate(digits))
    remainder = 11 - (total % 11)
    expected = "K" if remainder == 10 else ("0" if remainder == 11 else str(remainder))
    if dv != expected:
        return None
    return f"{body}-{dv}"


def _normalize_email(raw: str) -> str:
    return raw.strip().lower()


# ── lógica de detección ──────────────────────────────────────────────────────


@dataclass
class MatchCandidate:
    client_id_a: uuid.UUID
    client_id_b: uuid.UUID
    match_level: str
    match_signals: dict


def _find_rut_matches(db: Session) -> list[MatchCandidate]:
    """Pares con mismo RUT válido de fuentes distintas → Level B."""
    rows = db.execute(
        text("""
            SELECT
                LEAST(a1.client_id, a2.client_id)    AS cid_a,
                GREATEST(a1.client_id, a2.client_id) AS cid_b,
                a1.attribute_value                   AS rut_value,
                a1.source                            AS source_a,
                a2.source                            AS source_b
            FROM core_client_attributes a1
            JOIN core_client_attributes a2
                ON  a1.attribute_type  = a2.attribute_type
                AND a1.attribute_value = a2.attribute_value
                AND a1.client_id      != a2.client_id
                AND a1.source         != a2.source
            WHERE a1.attribute_type = 'rut'
              AND a1.client_id IS NOT NULL
              AND a2.client_id IS NOT NULL
        """)
    ).fetchall()

    candidates = []
    seen: set[tuple] = set()
    for row in rows:
        cid_a, cid_b = uuid.UUID(str(row.cid_a)), uuid.UUID(str(row.cid_b))
        # Validar que el RUT almacenado sea efectivamente válido
        if _normalize_rut(row.rut_value) is None:
            continue
        key = (cid_a, cid_b)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            MatchCandidate(
                client_id_a=cid_a,
                client_id_b=cid_b,
                match_level="B",
                match_signals={"rut": True, "email": False},
            )
        )
    return candidates


def _find_email_matches(db: Session) -> list[MatchCandidate]:
    """Pares con mismo email normalizado de fuentes distintas → Level C."""
    rows = db.execute(
        text("""
            SELECT
                LEAST(a1.client_id, a2.client_id)       AS cid_a,
                GREATEST(a1.client_id, a2.client_id)    AS cid_b,
                lower(trim(a1.attribute_value))         AS email_norm
            FROM core_client_attributes a1
            JOIN core_client_attributes a2
                ON  a1.attribute_type                    = a2.attribute_type
                AND lower(trim(a1.attribute_value))     = lower(trim(a2.attribute_value))
                AND a1.client_id                        != a2.client_id
                AND a1.source                           != a2.source
            WHERE a1.attribute_type = 'email'
              AND a1.client_id IS NOT NULL
              AND a2.client_id IS NOT NULL
        """)
    ).fetchall()

    candidates = []
    seen: set[tuple] = set()
    for row in rows:
        cid_a, cid_b = uuid.UUID(str(row.cid_a)), uuid.UUID(str(row.cid_b))
        key = (cid_a, cid_b)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            MatchCandidate(
                client_id_a=cid_a,
                client_id_b=cid_b,
                match_level="C",
                match_signals={"rut": False, "email": True},
            )
        )
    return candidates


def _merge_signals(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
    """Si un par aparece en RUT y email, consolida en un solo Level B con ambas señales."""
    by_pair: dict[tuple, MatchCandidate] = {}
    for c in candidates:
        key = (c.client_id_a, c.client_id_b)
        if key not in by_pair:
            by_pair[key] = c
        else:
            existing = by_pair[key]
            merged_signals = {k: existing.match_signals.get(k) or c.match_signals.get(k) for k in set(existing.match_signals) | set(c.match_signals)}
            best_level = "B" if "B" in (existing.match_level, c.match_level) else "C"
            by_pair[key] = MatchCandidate(
                client_id_a=existing.client_id_a,
                client_id_b=existing.client_id_b,
                match_level=best_level,
                match_signals=merged_signals,
            )
    return list(by_pair.values())


# ── punto de entrada ─────────────────────────────────────────────────────────


def detect_matches(db: Session) -> dict[str, int]:
    """Detecta candidatos de match y los persiste para revisión manual.

    Retorna conteo por nivel: {"B": N, "C": N, "inserted": N, "skipped_duplicate": N}.
    """
    rut_candidates = _find_rut_matches(db)
    email_candidates = _find_email_matches(db)
    all_candidates = _merge_signals(rut_candidates + email_candidates)

    counts: dict[str, int] = {"B": 0, "C": 0, "inserted": 0, "skipped_duplicate": 0}
    for c in all_candidates:
        counts[c.match_level] = counts.get(c.match_level, 0) + 1
        existing = (
            db.query(ClientMatchCandidate)
            .filter_by(client_id_a=c.client_id_a, client_id_b=c.client_id_b)
            .first()
        )
        if existing:
            # Actualizar señales si hay más información ahora
            updated_signals = {**existing.match_signals, **c.match_signals}
            best_level = "B" if "B" in (existing.match_level, c.match_level) else existing.match_level
            if updated_signals != existing.match_signals or best_level != existing.match_level:
                existing.match_signals = updated_signals
                existing.match_level = best_level
                db.flush()
            counts["skipped_duplicate"] += 1
        else:
            db.add(
                ClientMatchCandidate(
                    client_id_a=c.client_id_a,
                    client_id_b=c.client_id_b,
                    match_level=c.match_level,
                    match_signals=c.match_signals,
                    status="pending",
                )
            )
            counts["inserted"] += 1

    db.commit()
    logger.info(
        "detect_matches completed: inserted=%d skipped=%d level_B=%d level_C=%d",
        counts["inserted"],
        counts["skipped_duplicate"],
        counts.get("B", 0),
        counts.get("C", 0),
    )
    return counts
