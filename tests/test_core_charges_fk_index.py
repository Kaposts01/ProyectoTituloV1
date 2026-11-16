"""d223: la FK core_charges.latest_rejection_payment_id -> core_payments tiene indice (migracion 0081).

Sin el, cada DELETE en core_payments recorria core_charges entera (la poda TCH del 16/11 no terminaba).
"""

from sqlalchemy import text

from app.db.session import engine
from app.models.core import CoreCharge


def test_model_declares_the_index() -> None:
    column = CoreCharge.__table__.c.latest_rejection_payment_id
    assert column.index is True


def test_migrated_database_has_the_index() -> None:
    # conftest aplica `alembic upgrade head` sobre la base de test al iniciar la sesion.
    with engine.connect() as conn:
        indexdef = conn.scalar(
            text("select indexdef from pg_indexes where tablename = 'core_charges' and indexname = :n"),
            {"n": "ix_core_charges_latest_rejection_payment_id"},
        )
    assert indexdef is not None and "(latest_rejection_payment_id)" in indexdef
