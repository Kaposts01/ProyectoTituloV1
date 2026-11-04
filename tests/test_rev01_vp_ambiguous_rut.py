"""REV-01: un RUT compartido por dos clientes de VirtualPOS no vincula una suscripcion ni un pago al primero.

Tomado de origin/sprint-5/estabilizacion-dashboard (1005a26, tests/test_core_data_integrity.py), sin las pruebas que
dependen de su migracion 20261029_0037 (no se integro). Datos sinteticos; todo se revierte al final.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreClient, CoreSubscription
from app.models.vp import VpClient, VpSubscription
from app.services import core_vp_etl


@pytest.fixture
def db():
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            try:
                yield session
            finally:
                session.rollback()
                transaction.rollback()


@pytest.mark.parametrize("direct", [None, "known", "unknown"])
@pytest.mark.parametrize("shared", [True, False])
def test_vp_ambiguous_rut_never_selects_first_client(db, direct, shared):
    token = uuid.uuid4().hex
    clients = [CoreClient(), CoreClient(), CoreClient()]
    db.add_all(clients)
    db.flush()
    mapping = {}
    for i, client in enumerate(clients):
        platform = "virtualpos1" if i < 2 else "virtualpos2"
        external_id = f"{token}-{i}"
        db.add(VpClient(platform=platform, external_id=external_id, social_id=token if shared or i != 1 else token + "-other"))
        mapping[(platform, external_id)] = client.id
    sub_id = token + "-sub"
    db.add(VpSubscription(platform="virtualpos1", external_id=sub_id, client_social_id=token,
                          client_external_id=(token + "-0" if direct == "known" else "missing" if direct == "unknown" else None)))
    db.add(VpSubscription(platform="virtualpos2", external_id=sub_id, client_social_id=token))
    db.flush()
    core_vp_etl._materialize_subscriptions(db, core_vp_etl._build_social_id_index(db), mapping)
    subscriptions = {s.source: s for s in db.scalars(select(CoreSubscription).where(CoreSubscription.external_id == sub_id))}
    # Con ID explicito conocido se usa ese cliente; con ID explicito desconocido, ninguno (nunca cae al RUT);
    # sin ID, el RUT solo vincula si identifica a un unico cliente de la plataforma.
    assert subscriptions["virtualpos1"].client_id == (clients[0].id if direct == "known" or (direct is None and not shared) else None)
    assert subscriptions["virtualpos2"].client_id == clients[2].id


def test_vp_payment_index_excludes_shared_client_rut(db):
    token = uuid.uuid4().hex
    db.add_all([VpClient(platform="virtualpos1", external_id=f"{token}-{i}", social_id=token) for i in range(2)])
    db.add(VpSubscription(platform="virtualpos1", external_id=token, client_social_id=token))
    db.add(CoreSubscription(source="virtualpos1", external_id=token))
    db.flush()
    assert not core_vp_etl._build_rut_to_sub_index(db).get(("virtualpos1", token))


def test_vp_payment_index_keeps_a_rut_of_a_single_client(db):
    token = uuid.uuid4().hex
    db.add(VpClient(platform="virtualpos1", external_id=f"{token}-0", social_id=token))
    db.add(VpSubscription(platform="virtualpos1", external_id=token, client_social_id=token))
    core = CoreSubscription(source="virtualpos1", external_id=token)
    db.add(core)
    db.flush()
    assert core_vp_etl._build_rut_to_sub_index(db).get(("virtualpos1", token)) == [core.id]
