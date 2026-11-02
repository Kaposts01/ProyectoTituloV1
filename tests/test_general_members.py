"""UX-10 (transitorio): Socios agrupados por RUT, paginados en SQL, con filtros de canal y estado. Datos sinteticos."""

import random

from app.api.v1.routes import staging
from app.models.crm import Client, Subscription
from app.models.tch import TchClient, TchSubscription
from tests.test_staging_api import db_session  # noqa: F401  (fixture con rollback)


def _rut() -> tuple[str, str]:
    body = str(random.randint(10_000_000, 29_999_999))
    return f"{body[:2]}.{body[2:5]}.{body[5:]}-K", f"{body}K"


def _seed(session):
    rut_a, key_a = _rut()  # VirtualPOS + TCH, activo en TCH
    rut_b, key_b = _rut()  # solo Toku, sin suscripcion activa
    session.add_all([
        Client(source="virtualpos1", external_id=f"m-{key_a}", social_id=rut_a, first_name="Zoila", last_name="Unificada",
               email="zoila@example.test", raw_payload={}),
        Subscription(source="virtualpos1", external_id=f"ms-{key_a}", client_external_id=f"m-{key_a}", status="cancelada", raw_payload={}),
        TchClient(rut=key_a, name="Zoila", last_name="Unificada"),
        TchSubscription(file_number=random.randint(50_000_000, 59_999_999), client_rut=key_a, status="VIGENTE"),
        Client(source="toku", external_id=f"m-{key_b}", social_id=rut_b, first_name="Zoe", last_name="Solotoku", raw_payload={}),
        Subscription(source="toku", external_id=f"ms-{key_b}", client_external_id=f"m-{key_b}", status="canceled", raw_payload={}),
    ])
    session.flush()
    return (rut_a, key_a), (rut_b, key_b)


def test_members_group_by_rut_across_channels_and_filter_in_sql(db_session) -> None:  # noqa: F811
    (rut_a, key_a), (rut_b, _key_b) = _seed(db_session)
    items, total = staging._general_clients_page(db_session, key_a, "rut", 0, 50)
    assert total == 1
    assert items[0] == {"rut": rut_a, "name": "Zoila Unificada", "origins": ["TCH", "VirtualPOS"], "active_origins": ["TCH"]}
    zo, zo_total = staging._general_clients_page(db_session, "zo", "name", 0, 50)
    assert {item["rut"] for item in zo} >= {rut_a, rut_b} and zo_total >= 2
    only_toku, _ = staging._general_clients_page(db_session, "zo", "name", 0, 50, channel="toku")
    assert rut_b in {item["rut"] for item in only_toku} and rut_a not in {item["rut"] for item in only_toku}
    active, _ = staging._general_clients_page(db_session, "zo", "name", 0, 50, status="active")
    inactive, _ = staging._general_clients_page(db_session, "zo", "name", 0, 50, status="inactive")
    assert rut_a in {i["rut"] for i in active} and rut_a not in {i["rut"] for i in inactive}
    assert rut_b in {i["rut"] for i in inactive}
    by_email, _ = staging._general_clients_page(db_session, "zoila@example", "email", 0, 50)
    assert [i["rut"] for i in by_email] == [rut_a]
    first, _ = staging._general_clients_page(db_session, "zo", "name", 0, 1)
    second, _ = staging._general_clients_page(db_session, "zo", "name", 1, 1)
    assert len(first) == 1 and len(second) == 1 and first[0]["rut"] != second[0]["rut"]


def test_member_detail_filters_by_rut_key(db_session) -> None:  # noqa: F811
    (rut_a, key_a), _ = _seed(db_session)
    assert staging._member_exists(db_session, rut_a) and not staging._member_exists(db_session, "1-9")
    detail = staging._general_client_detail(db_session, rut_a)
    assert {c["portal"] for c in detail["clients"]} == {"VirtualPOS", "TCH"}
    assert {(s["portal"], s["status"]) for s in detail["subscriptions"]} == {("VirtualPOS", "cancelada"), ("TCH", "VIGENTE")}
    assert staging._general_client_detail(db_session, key_a)["clients"] == detail["clients"]
