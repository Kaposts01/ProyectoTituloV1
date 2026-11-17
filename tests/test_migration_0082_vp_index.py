"""BUG-VP-03a: tras `alembic upgrade head` (conftest) no existe `uq_vp_sub_active_plan_client` y caben dos activas."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.vp import VpSubscription

RUT = "11111111-1"


def test_index_is_gone_after_head() -> None:
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE indexname = 'uq_vp_sub_active_plan_client'")
        ).all()
    assert found == []


def test_two_active_same_plan_and_client_can_coexist() -> None:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        for ext in ("zz82-a", "zz82-b"):
            session.add(
                VpSubscription(
                    external_id=ext, platform="virtualpos1", plan_external_id="zz82-plan",
                    client_social_id=RUT, status="ACTIVA",
                )
            )
        session.flush()
        rows = session.scalars(select(VpSubscription.external_id).where(VpSubscription.external_id.like("zz82-%"))).all()
        assert sorted(rows) == ["zz82-a", "zz82-b"]
    finally:
        session.close()
        transaction.rollback()
        connection.close()
