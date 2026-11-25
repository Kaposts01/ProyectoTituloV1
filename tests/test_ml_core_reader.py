"""Native PostgreSQL Core reads, synthetic records in guarded disposable DB only."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import engine
from app.ml.recommendation import Advice, State, recommend
from app.services.ml_core_reader import (
    ReviewedStateMapping,
    map_core_evidence,
    read_core_evidence,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


@pytest.fixture
def rows():
    ids = {name: uuid4() for name in ("subscription", "charge", "payment", "standalone")}
    args = ids | {"clock": NOW}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO core_subscriptions(id,source,external_id,status,updated_at)
            VALUES (:subscription,'virtualpos1',:external,'raw-active',:clock)"""), args | {"external": str(ids["subscription"])})
        conn.execute(text("""INSERT INTO core_charges(id,source,external_id,subscription_id,source_status,
            latest_rejection_code,latest_rejection_at,updated_at)
            VALUES (:charge,'virtualpos1',:external,:subscription,'raw-rejected','-4',:clock,:clock)"""), args | {"external": str(ids["charge"])})
        for name, charge in (("payment", ids["charge"]), ("standalone", None)):
            conn.execute(text("""INSERT INTO core_payments(id,source,external_id,subscription_id,charge_id,
                source_status,rejection_code,rejection_reported_at,updated_at)
                VALUES (:id,'virtualpos1',:external,:subscription,:linked_charge,'raw-rejected','-4',:clock,:clock)"""),
                         args | {"id": ids[name], "external": str(ids[name]), "linked_charge": charge})
        conn.execute(text("UPDATE core_charges SET latest_rejection_payment_id=:payment WHERE id=:charge"), args)
    yield ids
    with engine.begin() as conn:
        conn.execute(text("UPDATE core_charges SET latest_rejection_payment_id=NULL WHERE id=:charge"), args)
        conn.execute(text("DELETE FROM core_payments WHERE id IN (:payment,:standalone)"), args)
        conn.execute(text("DELETE FROM core_charges WHERE id=:charge"), args)
        conn.execute(text("DELETE FROM core_subscriptions WHERE id=:subscription"), args)


def read(conn, rows, *, kind="charge", key="charge", source="virtualpos1"):
    return read_core_evidence(conn, source=source, resource_type=kind, resource_id=rows[key])


def test_scoped_core_projection_and_payment_without_charge(rows):
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        charge = read(conn, rows)
        assert charge.links_consistent and charge.evidence_id == rows["payment"]
        assert charge.subscription_id == rows["subscription"] and charge.source_status == "raw-rejected"
        assert read(conn, rows, source="virtualpos2") is None
        assert read_core_evidence(conn, source="tch", resource_type="payment", resource_id=uuid4()) is None
        standalone = read(conn, rows, kind="payment", key="standalone")
        assert standalone.charge_id is None and standalone.links_consistent
        assert standalone.resource_type == "payment" and standalone.evidence_id == rows["standalone"]
        assert not hasattr(charge, "rejection_reason")  # Free text/PII excluded at SQL projection.
        mapping = ReviewedStateMapping("virtualpos1", "charge", "a"*64,
                                       (("raw-rejected", State.REJECTED),), (("raw-active", True),))
        snap = map_core_evidence(charge, mapping, as_of=NOW, verified_through=NOW)
        assert not snap.settlement_verified and recommend(snap).advice == Advice.REVIEW
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE core_charges SET source_status='paid' WHERE id=:id"), {"id": rows["charge"]})
        conn.rollback()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT source_status FROM core_charges WHERE id=:id"), {"id": rows["charge"]}).scalar_one() == "raw-rejected"


def test_transaction_guards_prevent_uncontrolled_reads(rows):
    with engine.connect() as conn:
        with pytest.raises(ValueError, match="explicita"):
            read(conn, rows)
        with conn.begin(), pytest.raises(ValueError, match="solo lectura"):
            read(conn, rows)
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        with pytest.raises(ValueError, match="consistente"):
            read(conn, rows)
    with engine.connect() as conn:
        for source, kind, resource_id in (("virtualpos", "charge", uuid4()), ("toku", "subscription", uuid4()), ("toku", "payment", "personal-id")):
            with pytest.raises(ValueError):
                read_core_evidence(conn, source=source, resource_type=kind, resource_id=resource_id)


def test_cross_source_links_never_become_verified(rows):
    with engine.begin() as conn:
        conn.execute(text("UPDATE core_payments SET source='virtualpos2' WHERE id=:id"), {"id": rows["payment"]})
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        assert read(conn, rows).links_consistent is False


def test_null_link_is_false_instead_of_sql_unknown(rows):
    with engine.begin() as conn:
        conn.execute(text("UPDATE core_payments SET subscription_id=NULL WHERE id=:id"), {"id": rows["payment"]})
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        assert read(conn, rows).links_consistent is False
