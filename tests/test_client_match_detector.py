"""Tests para el detector de candidatos de match cross-canal (EPIC-C)."""

import uuid as uuid_mod

import pytest
from sqlalchemy.orm import Session

from app.models.core import ClientMatchCandidate, CoreClient, CoreClientAttribute
from app.services.client_match_detector import (
    _normalize_email,
    _normalize_rut,
    detect_matches,
)

# ── unit: normalización de RUT ───────────────────────────────────────────────
# RUTs válidos con DV correcto:
#   12345678-5  (suma ponderada = 138, 138%11=6, 11-6=5)
#   7654321-6   (suma ponderada = 126, 126%11=5, 11-5=6)
#   8765432-K   (suma ponderada = 155, 155%11=1, 11-1=10 → K)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12.345.678-5", "12345678-5"),
        ("12345678-5", "12345678-5"),
        ("  12.345.678-5  ", "12345678-5"),
        ("7.654.321-6", "7654321-6"),
        ("8.765.432-K", "8765432-K"),
        ("8.765.432-k", "8765432-K"),  # lowercase k → K
    ],
)
def test_normalize_rut_valid(raw: str, expected: str) -> None:
    assert _normalize_rut(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "12.345.678-9",   # DV incorrecto (debería ser 5)
        "7.654.321-K",    # DV incorrecto (debería ser 6)
        "1234",           # muy corto
        "abc-K",          # no numérico
        "",
    ],
)
def test_normalize_rut_invalid(raw: str) -> None:
    assert _normalize_rut(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("USER@Example.COM", "user@example.com"),
        ("  test@test.cl  ", "test@test.cl"),
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert _normalize_email(raw) == expected


# ── integration: con PostgreSQL real ─────────────────────────────────────────


@pytest.fixture
def pg_session():
    """Require the test database and roll back fixtures, including service commits."""
    from app.db.session import engine

    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            try:
                yield db
            finally:
                db.rollback()
                transaction.rollback()


def _unique_source(prefix: str) -> str:
    """Genera un nombre de fuente único por test para evitar conflictos de UNIQUE."""
    return f"{prefix}_{uuid_mod.uuid4().hex[:8]}"


def _make_client(db: Session) -> CoreClient:
    c = CoreClient()
    db.add(c)
    db.flush()
    return c


def _add_attr(db: Session, client: CoreClient, source: str, attr_type: str, value: str) -> None:
    db.add(CoreClientAttribute(
        client_id=client.id,
        source=source,
        attribute_type=attr_type,
        attribute_value=value,
    ))
    db.flush()


def test_rut_match_creates_level_b_candidate(pg_session: Session) -> None:
    src_a = _unique_source("vpos")
    src_b = _unique_source("toku")
    c1 = _make_client(pg_session)
    c2 = _make_client(pg_session)
    _add_attr(pg_session, c1, src_a, "rut", "12.345.678-5")
    _add_attr(pg_session, c2, src_b, "rut", "12.345.678-5")

    counts = detect_matches(pg_session)

    assert counts["inserted"] >= 1
    candidate = (
        pg_session.query(ClientMatchCandidate)
        .filter(
            ClientMatchCandidate.client_id_a.in_([c1.id, c2.id]),
            ClientMatchCandidate.client_id_b.in_([c1.id, c2.id]),
        )
        .first()
    )
    assert candidate is not None
    assert candidate.match_level == "B"
    assert candidate.match_signals.get("rut") is True


def test_email_match_creates_level_c_candidate(pg_session: Session) -> None:
    src_a = _unique_source("vpos")
    src_b = _unique_source("payku")
    c1 = _make_client(pg_session)
    c2 = _make_client(pg_session)
    _add_attr(pg_session, c1, src_a, "email", "test@example.com")
    _add_attr(pg_session, c2, src_b, "email", "TEST@EXAMPLE.COM")  # mismo normalizado

    counts = detect_matches(pg_session)

    assert counts["inserted"] >= 1
    candidate = (
        pg_session.query(ClientMatchCandidate)
        .filter(
            ClientMatchCandidate.client_id_a.in_([c1.id, c2.id]),
            ClientMatchCandidate.client_id_b.in_([c1.id, c2.id]),
        )
        .first()
    )
    assert candidate is not None
    assert candidate.match_level == "C"
    assert candidate.match_signals.get("email") is True


def test_different_rut_no_match(pg_session: Session) -> None:
    """Dos clientes de fuentes distintas con RUT diferente no generan candidato."""
    src_a = _unique_source("vpos")
    src_b = _unique_source("toku")
    c1 = _make_client(pg_session)
    c2 = _make_client(pg_session)
    _add_attr(pg_session, c1, src_a, "rut", "7.654.321-6")
    _add_attr(pg_session, c2, src_b, "rut", "8.765.432-K")

    detect_matches(pg_session)

    # Verificar que este par específico NO tiene candidato
    candidate = (
        pg_session.query(ClientMatchCandidate)
        .filter(
            ClientMatchCandidate.client_id_a.in_([c1.id, c2.id]),
            ClientMatchCandidate.client_id_b.in_([c1.id, c2.id]),
        )
        .first()
    )
    assert candidate is None  # RUTs distintos → sin candidato para este par


def test_detect_matches_idempotent(pg_session: Session) -> None:
    src_a = _unique_source("vpos")
    src_b = _unique_source("toku")
    c1 = _make_client(pg_session)
    c2 = _make_client(pg_session)
    _add_attr(pg_session, c1, src_a, "rut", "8.765.432-K")
    _add_attr(pg_session, c2, src_b, "rut", "8.765.432-K")

    counts1 = detect_matches(pg_session)
    counts2 = detect_matches(pg_session)

    assert counts1["inserted"] >= 1
    # Segunda ejecución: ningún candidato nuevo para este par
    assert counts2["inserted"] == 0
    assert counts2["skipped_duplicate"] >= 1
