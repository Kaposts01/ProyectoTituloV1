from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.models.crm import Subscription
from app.services.write_payku import (
    ClientNotFoundError as PaykuClientNotFoundError,
    ReconciliationRequiredError as PaykuReconciliationRequiredError,
    SubscriptionNotFoundError as PaykuSubscriptionNotFoundError,
    WriteDisabledError as PaykuWriteDisabledError,
    delete_client as payku_delete_client,
    delete_subscription as payku_delete_subscription,
    update_client as payku_update_client,
)
from app.services.write_toku import (
    CustomerNotFoundError as TokuCustomerNotFoundError,
    ReconciliationRequiredError as TokuReconciliationRequiredError,
    SubscriptionNotFoundError as TokuSubscriptionNotFoundError,
    WriteDisabledError as TokuWriteDisabledError,
    change_subscription_status,
    delete_customer,
    update_customer,
)
from app.services.write_virtualpos import (
    ChargeNotFoundError,
    ClientNotFoundError,
    DuplicateClientError,
    InvalidClientDataError,
    LocalStateUnavailableError,
    ReconciliationRequiredError,
    SubscriptionNotFoundError,
    WriteDisabledError,
    cancel_charge,
    cancel_subscription,
    create_charge,
    create_client,
    create_plan,
    create_subscription,
    retry_charge,
    update_client,
)

router = APIRouter()


class VirtualPOSClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ACTIVO", "BLOQUEADO"] | None = None
    type: Literal["PERSONA", "EMPRESA"] | None = None
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone_number: str | None = Field(default=None, max_length=50)
    social_id_type: Literal["1", "2"] | None = None
    social_id: str | None = Field(default=None, max_length=50)
    birth_date: str | None = Field(default=None, max_length=50)
    gender_id: Literal["", "Masculino", "Femenino"] | None = None
    private_note: str | None = Field(default=None, max_length=2000)


class VirtualPOSClientCreate(VirtualPOSClientUpdate):
    first_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    social_id_type: Literal["1", "2"]
    social_id: str = Field(min_length=1, max_length=50)
    platform: Literal["virtualpos1", "virtualpos2"] = "virtualpos1"


class VirtualPOSPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["virtualpos1", "virtualpos2"] = "virtualpos1"
    name: str = Field(min_length=1, max_length=255)
    amount: int = Field(ge=0)
    currency: Literal["CLP", "UF"] = "CLP"
    frequency_type: Literal["monthly", "weekly", "daily", "annual", "bimonthly", "quarterly", "biannual"]
    description: str | None = Field(default=None, max_length=2000)
    trial_days: int | None = Field(default=None, ge=0)
    num_charges: int | None = Field(default=None, ge=0)
    return_url: str | None = Field(default=None, max_length=500)
    suscription_url: str | None = Field(default=None, max_length=500)
    automatic_renewal: bool | None = None
    show_in_terminal: bool | None = None
    activation_amount: int | None = Field(default=None, ge=0)
    fixed_amount_day_charge: int | None = Field(default=None, ge=1, le=28)
    type: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


@router.put(
    "/virtualpos/clients/{client_id}",
    dependencies=[Depends(require_permissions("virtualpos.clients.update")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def update_virtualpos_client(
    client_id: str,
    body: VirtualPOSClientUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Update an approved VirtualPOS client field set through the internal API."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required")
    try:
        client = await update_client(db, client_id, changes)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except ClientNotFoundError:
        raise HTTPException(status_code=404, detail="VirtualPOS client not found") from None
    except InvalidClientDataError:
        raise HTTPException(status_code=422, detail="Invalid RUT") from None
    except LocalStateUnavailableError:
        raise HTTPException(status_code=503, detail="VirtualPOS local data is unavailable") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rejected the update") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="VirtualPOS update requires local reconciliation") from None

    payload = dict(client.raw_payload or {})
    if client.private_note:
        payload["private_note"] = client.private_note
    return {
        "external_id": client.external_id,
        "source": client.source,
        "status": client.status,
        "payload": payload,
    }


@router.post(
    "/virtualpos/clients",
    dependencies=[Depends(require_permissions("virtualpos.clients.update")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def create_virtualpos_client(
    body: VirtualPOSClientCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create an approved VirtualPOS client through the internal API."""
    try:
        client = await create_client(db, body.model_dump(exclude_none=True, mode="json"))
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except DuplicateClientError:
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese documento de identidad en VirtualPOS") from None
    except InvalidClientDataError:
        raise HTTPException(status_code=422, detail="Invalid RUT") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rejected the client") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="VirtualPOS client requires local reconciliation") from None

    payload = dict(client.raw_payload or {})
    if client.private_note:
        payload["private_note"] = client.private_note
    return {"id": str(client.id), "external_id": client.external_id, "source": client.source, "payload": payload}


@router.post(
    "/virtualpos/plans",
    dependencies=[Depends(require_permissions("virtualpos.plans.update")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def create_virtualpos_plan(
    body: VirtualPOSPlanCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create a VirtualPOS plan through the internal API."""
    try:
        plan = await create_plan(db, body.model_dump(exclude_none=True, mode="json"))
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rejected the plan") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="VirtualPOS plan requires local reconciliation") from None

    return {"id": str(plan.id), "external_id": plan.external_id, "source": plan.source, "payload": plan.raw_payload or {}}


class VirtualPOSSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["virtualpos1", "virtualpos2"] = "virtualpos1"
    plan_id: str = Field(min_length=1, max_length=255)
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str = Field(min_length=1, max_length=255)
    social_id: str = Field(min_length=1, max_length=50)
    phone_number: str | None = Field(default=None, max_length=50)
    service_id: str | None = Field(default=None, max_length=255)
    channel: str | None = Field(default=None, max_length=50)
    automatic_renewal: Literal["T", "F"] | None = None
    return_url: str | None = Field(default=None, max_length=2000)
    callback_url: str | None = Field(default=None, max_length=2000)


@router.post(
    "/virtualpos/subscriptions",
    dependencies=[Depends(require_permissions("virtualpos.subscriptions.create")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def create_virtualpos_subscription(
    body: VirtualPOSSubscriptionCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create a VirtualPOS subscription via POST /v3/suscription."""
    try:
        sub = await create_subscription(db, body.model_dump(exclude_none=True, mode="json"))
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rechazó la suscripción") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La suscripción requiere reconciliación local") from None

    return {"id": str(sub.id), "external_id": sub.external_id, "source": sub.source, "payload": sub.raw_payload or {}}


@router.delete(
    "/virtualpos/subscriptions/{subscription_id}",
    dependencies=[Depends(require_permissions("virtualpos.subscriptions.cancel")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Cancel an active VirtualPOS subscription via DELETE /v3/suscription/{id}."""
    try:
        sub = await cancel_subscription(db, subscription_id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rechazó la cancelación") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La cancelación requiere reconciliación local") from None

    return {"external_id": sub.external_id, "status": sub.status}


class VirtualPOSChargeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_date: str = Field(min_length=1, max_length=50)
    amount: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=500)
    internal_code: str | None = Field(default=None, max_length=100)


@router.post(
    "/virtualpos/subscriptions/{subscription_id}/charges",
    dependencies=[Depends(require_permissions("virtualpos.charges.create")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def create_virtualpos_charge(
    subscription_id: str,
    body: VirtualPOSChargeCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create a new charge on an active VirtualPOS subscription."""
    subscription = db.scalar(
        select(Subscription).where(
            Subscription.external_id == subscription_id,
            Subscription.source.like("virtualpos%"),
        )
    )
    platform = subscription.source if subscription else "virtualpos1"

    try:
        charge = await create_charge(db, subscription_id, body.model_dump(exclude_none=True, mode="json"), platform=platform)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rejected the charge") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="VirtualPOS charge requires local reconciliation") from None

    return {"id": str(charge.id), "external_id": charge.external_id, "source": charge.source, "payload": charge.raw_payload or {}}


@router.delete(
    "/virtualpos/charges/{charge_id}",
    dependencies=[Depends(require_permissions("virtualpos.charges.cancel")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_charge(
    charge_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Cancel a pending VirtualPOS charge via DELETE /v3/charge/{id}."""
    try:
        charge = await cancel_charge(db, charge_id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except ChargeNotFoundError:
        raise HTTPException(status_code=404, detail="Cargo no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rechazó la cancelación del cargo") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La cancelación requiere reconciliación local") from None

    return {"external_id": charge.external_id, "status": charge.status}


@router.post(
    "/virtualpos/charges/{charge_id}/retry",
    dependencies=[Depends(require_permissions("virtualpos.charges.retry")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def retry_virtualpos_charge(
    charge_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Retry a rejected VirtualPOS charge via GET /v3/charge/{id}/retry."""
    try:
        charge = await retry_charge(db, charge_id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled") from None
    except ChargeNotFoundError:
        raise HTTPException(status_code=404, detail="Cargo no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="VirtualPOS rechazó el reintento del cargo") from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="El reintento requiere reconciliación local") from None

    return {"external_id": charge.external_id, "status": charge.status, "payload": charge.raw_payload or {}}


# ─── Toku writes ─────────────────────────────────────────────────────────────

class TokuCustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    mail: EmailStr | None = None


@router.put(
    "/toku/customers/{customer_id}",
    dependencies=[Depends(require_permissions("toku.customers.update")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def update_toku_customer(
    customer_id: str,
    body: TokuCustomerUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Update a Toku customer via PUT /customers/{id}."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail="Al menos un campo es requerido")
    try:
        client = await update_customer(db, customer_id, changes)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Toku writes are disabled") from None
    except TokuCustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Cliente Toku no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Toku rechazó la actualización") from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La actualización requiere reconciliación local") from None

    return {"external_id": client.external_id, "source": client.source, "payload": client.raw_payload or {}}


@router.delete(
    "/toku/customers/{customer_id}",
    dependencies=[Depends(require_permissions("toku.customers.delete")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def delete_toku_customer(
    customer_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Delete a Toku customer via DELETE /customers/{id}."""
    try:
        client = await delete_customer(db, customer_id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Toku writes are disabled") from None
    except TokuCustomerNotFoundError:
        raise HTTPException(status_code=404, detail="Cliente Toku no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Toku rechazó la eliminación") from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La eliminación requiere reconciliación local") from None

    return {"external_id": client.external_id, "status": client.status}


class TokuSubscriptionStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PAUSED", "ACTIVE", "CANCELLED"]


@router.post(
    "/toku/subscriptions/{subscription_id}/status",
    dependencies=[Depends(require_permissions("toku.subscriptions.manage")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def change_toku_subscription_status(
    subscription_id: str,
    body: TokuSubscriptionStatusChange,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Change Toku subscription status via POST /subscriptions/{id}/status."""
    try:
        sub = await change_subscription_status(db, subscription_id, body.status)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Toku writes are disabled") from None
    except TokuSubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Suscripción Toku no encontrada") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Toku rechazó el cambio de estado") from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="El cambio de estado requiere reconciliación local") from None

    return {"external_id": sub.external_id, "status": sub.status, "payload": sub.raw_payload or {}}


# ─── Payku writes ─────────────────────────────────────────────────────────────

class PaykuClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)


@router.put(
    "/payku/clients/{client_id}",
    dependencies=[Depends(require_permissions("payku.clients.update")), Depends(require_csrf)],
    tags=["Writes - Payku"],
)
async def update_payku_client(
    client_id: str,
    body: PaykuClientUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Update a Payku subscription client via PUT /api/suclient/{id}."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail="Al menos un campo es requerido")
    try:
        client = await payku_update_client(db, client_id, changes)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Payku writes are disabled") from None
    except PaykuClientNotFoundError:
        raise HTTPException(status_code=404, detail="Cliente Payku no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Payku rechazó la actualización") from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La actualización requiere reconciliación local") from None

    return {"external_id": client.external_id, "source": client.source, "payload": client.raw_payload or {}}


@router.delete(
    "/payku/clients/{client_id}",
    dependencies=[Depends(require_permissions("payku.clients.delete")), Depends(require_csrf)],
    tags=["Writes - Payku"],
)
async def delete_payku_client(
    client_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Delete a Payku subscription client via DELETE /api/suclient/{id}."""
    try:
        client = await payku_delete_client(db, client_id)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Payku writes are disabled") from None
    except PaykuClientNotFoundError:
        raise HTTPException(status_code=404, detail="Cliente Payku no encontrado") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Payku rechazó la eliminación") from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La eliminación requiere reconciliación local") from None

    return {"external_id": client.external_id, "status": client.status}


@router.delete(
    "/payku/subscriptions/{subscription_id}",
    dependencies=[Depends(require_permissions("payku.subscriptions.cancel")), Depends(require_csrf)],
    tags=["Writes - Payku"],
)
async def delete_payku_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Cancel a Payku subscription via DELETE /api/sususcription/{id}."""
    try:
        sub = await payku_delete_subscription(db, subscription_id)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail="Payku writes are disabled") from None
    except PaykuSubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Suscripción Payku no encontrada") from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Payku rechazó la cancelación") from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail="La cancelación requiere reconciliación local") from None

    return {"external_id": sub.external_id, "status": sub.status}
