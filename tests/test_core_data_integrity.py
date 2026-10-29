import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import (
    CoreClient,
    CoreClientAttribute,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.payku_channel import PaykuClient
from app.models.tch import TchCliente
from app.models.toku_channel import TokuCustomer
from app.models.vp import VpClient, VpSubscription
from app.services import core_payku_etl, core_tch_etl, core_toku_etl, core_vp_etl


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


@pytest.mark.parametrize("source", ["virtualpos1", "toku", "payku", "tch"])
def test_shared_email_retains_both_clients_and_is_idempotent(db, source):
    email = f"shared-{uuid.uuid4().hex}@example.test"
    clients = [CoreClient(), CoreClient()]
    db.add_all(clients)
    db.flush()
    mapping = {}
    for client in clients:
        external_id = uuid.uuid4().hex[:18]
        mapping[(source, external_id)] = client.id
        db.add(ExternalIdentity(source=source, resource_type="client", external_id=external_id, client_id=client.id))
        if source == "virtualpos1":
            customer = VpClient(platform=source, external_id=external_id, email=email)
        elif source == "toku":
            customer = TokuCustomer(external_id=external_id, email=email)
        elif source == "payku":
            customer = PaykuClient(external_id=external_id, email=email)
        else:
            customer = TchCliente(rut=external_id, email=email)
        db.add(customer)
    db.flush()
    if source == "virtualpos1":
        def materialize():
            return core_vp_etl._materialize_client_attributes(db, mapping)
    else:
        module = {"toku": core_toku_etl, "payku": core_payku_etl, "tch": core_tch_etl}[source]
        def materialize():
            return module._materialize_client_attributes(db)
    materialize()
    query = select(CoreClientAttribute).where(CoreClientAttribute.source == source, CoreClientAttribute.attribute_value == email)
    rows = db.scalars(query).all()
    assert {row.client_id for row in rows} == {client.id for client in clients}
    assert materialize() == 0
    assert len(db.scalars(query).all()) == 2


def test_unlinked_attributes_remain_idempotent(db):
    value = f"orphan-{uuid.uuid4().hex}@example.test"
    for _ in range(2):
        db.execute(insert(CoreClientAttribute).values(source="toku", client_id=None, attribute_type="email", attribute_value=value).on_conflict_do_nothing(constraint="uq_core_client_attribute"))
    assert db.scalar(select(func.count()).select_from(CoreClientAttribute).where(CoreClientAttribute.attribute_value == value)) == 1


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
    assert subscriptions["virtualpos1"].client_id == (clients[0].id if direct == "known" or (direct is None and not shared) else None)
    assert subscriptions["virtualpos2"].client_id == clients[2].id


def test_vp_payment_index_excludes_shared_client_rut(db):
    token = uuid.uuid4().hex
    db.add_all([VpClient(platform="virtualpos1", external_id=f"{token}-{i}", social_id=token) for i in range(2)])
    db.add(VpSubscription(platform="virtualpos1", external_id=token, client_social_id=token))
    db.add(CoreSubscription(source="virtualpos1", external_id=token))
    db.flush()
    assert not core_vp_etl._build_rut_to_sub_index(db).get(("virtualpos1", token))



def test_attribute_migration_preserves_rows_and_blocks_lossy_downgrade(db, monkeypatch):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    migration = ScriptDirectory.from_config(config).get_revision("20261029_0037").module
    # A temporary table shadows the real table; all DDL rolls back with this fixture.
    db.execute(text("""
        CREATE TEMPORARY TABLE core_client_attributes (
            id uuid PRIMARY KEY, client_id uuid, source text NOT NULL,
            attribute_type text NOT NULL, attribute_value text NOT NULL,
            CONSTRAINT uq_core_client_attribute UNIQUE (source, attribute_type, attribute_value)
        )
    """))
    original_id = uuid.uuid4()
    db.execute(text("INSERT INTO core_client_attributes VALUES (:id, :client, 'toku', 'email', 'shared@example.test')"),
               {"id": original_id, "client": uuid.uuid4()})
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(db.connection())))
    migration.upgrade()
    assert db.scalar(text("SELECT id FROM core_client_attributes")) == original_id
    migration.downgrade()
    migration.upgrade()
    db.execute(text("INSERT INTO core_client_attributes VALUES (:id, :client, 'toku', 'email', 'shared@example.test')"),
               {"id": uuid.uuid4(), "client": uuid.uuid4()})
    with pytest.raises(RuntimeError, match="Downgrade blocked"):
        migration.downgrade()
    assert db.scalar(text("SELECT count(*) FROM core_client_attributes")) == 2
