"""Soporte compartido de los tests de solicitudes de baja multicanal: roles/usuarios reales, suscripciones sinteticas
(sin datos personales) y sesion transaccional revertida. Ninguna llamada de red."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.auth import User
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.crm import Subscription
from app.models.payku_channel import PaykuTransaction
from app.models.tch import TchSuscripcion
from app.models.toku_channel import TokuInvoice
from app.models.vp import VpCharge
from app.services import cancellation_requests as cr
from app.services.rbac import (
    CANCELLATION_APPROVE,
    CANCELLATION_REQUEST,
    CANCELLATION_VIEW,
    executive_permission_codes,
    support_permission_codes,
)

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def make_roles(db: Session) -> dict:
    from billing_requests_support import make_role

    from app.services.rbac import PERMISSIONS

    return {
        "admin": make_role(db, "admin", set(PERMISSIONS)),
        "jefatura": make_role(db, "jefatura", {CANCELLATION_REQUEST, CANCELLATION_APPROVE, CANCELLATION_VIEW}),
        "ejecutivo": make_role(db, "ejecutivo", executive_permission_codes()),
        "soporte": make_role(db, "soporte", support_permission_codes()),
        "coordinador": make_role(db, "coordinador", {CANCELLATION_VIEW}),
        # solicita pero NO aprueba (para probar el flujo con aprobacion de otra persona)
        "solicitante": make_role(db, "solicitante-cancel-t", {CANCELLATION_REQUEST, CANCELLATION_VIEW}),
    }


def make_user(db: Session, *roles) -> User:
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=True, roles=list(roles))
    db.add(user)
    db.flush()
    return user


def seed_vp(db: Session, sub: str = "sub-c1", status: str = "ACTIVA", pending: int = 2, platform: str = "virtualpos1"):
    db.add(Subscription(source=platform, external_id=sub, status=status, plan_external_id="plan-1", amount="9900",
                        raw_payload={"id": sub, "status": status}))
    for i in range(pending):
        db.add(VpCharge(platform=platform, external_id=f"{sub}-p{i}", subscription_external_id=sub, status="pendiente",
                        amount="9900", charge_date="2026-12-05", raw_payload={}))
    db.add(VpCharge(platform=platform, external_id=f"{sub}-paid", subscription_external_id=sub, status="pagado",
                    amount="9900", charge_date="2026-10-05", raw_payload={}))
    db.commit()


def seed_toku(db: Session, sub: str = "sub_tk1", unpaid: int = 2, in_progress: int = 0, status: str = "ACTIVE"):
    db.add(Subscription(source="toku", external_id=sub, status=status, raw_payload={"id": sub, "status": status}))
    for i in range(unpaid):
        db.add(TokuInvoice(external_id=f"in_{sub}_{i}", subscription_id=sub, status="unpaid",
                           raw_payload={"general_status": "unpaid", "in_progress": False}))
    for i in range(in_progress):
        db.add(TokuInvoice(external_id=f"in_{sub}_ip{i}", subscription_id=sub, status="unpaid",
                           raw_payload={"general_status": "unpaid", "in_progress": True}))
    db.commit()


def seed_payku(db: Session, sub: str = "sus_pk1", pending: int = 1, status: str = "active"):
    db.add(Subscription(source="payku", external_id=sub, status=status, raw_payload={"id": sub, "status": status}))
    for i in range(pending):
        db.add(PaykuTransaction(external_id=f"trx_{sub}_{i}", subscription_id=sub, status="pending", raw_payload={}))
    db.commit()


def seed_tch(db: Session, ficha: int = 910001, eliminated: bool = False) -> str:
    db.add(TchSuscripcion(numero_ficha=ficha, estado="VIGENTE", fecha_eliminacion="2026-10-30" if eliminated else None))
    db.commit()
    return str(ficha)


def params(channel: str = "virtualpos1", sub: str = "sub-c1", **over) -> cr.CancellationParams:
    values = {"channel": channel, "subscription_external_id": sub, "reason_code": "member_request",
              "reason_comment": "El socio pidio la baja por correo"}
    values.update(over)
    return cr.CancellationParams(**values)


def approved_request(db: Session, user: User, channel: str = "virtualpos1", sub: str = "sub-c1", **over):
    """Crea una solicitud ya aprobada (el actor es aprobador y la politica permite autoaprobar)."""
    return cr.create_request(db, user, params(channel, sub, **over), now=NOW)


def expire_in_past(db: Session, req: SubscriptionCancellationRequest) -> None:
    req.expires_at = NOW - timedelta(days=1)
    db.commit()
