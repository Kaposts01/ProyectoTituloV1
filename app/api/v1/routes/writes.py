from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import (
    get_current_user,
    require_csrf,
    require_permissions,
    require_role,
)
from app.integrations.payku.client import PaykuApiError
from app.integrations.payku.write_guard import PaykuWriteBlockedError
from app.integrations.toku.write_guard import TokuWriteBlockedError
from app.integrations.virtualpos.client import VirtualPOSAPIError
from app.models.auth import User
from app.models.crm import Charge as CCharge
from app.models.crm import Payment as CPayment
from app.models.crm import Subscription
from app.services.billing_apply import SubscriptionBusyError
from app.services.write_payku import (
    ClientNotFoundError as PaykuClientNotFoundError,
)
from app.services.write_payku import (
    ReconciliationRequiredError as PaykuReconciliationRequiredError,
)
from app.services.write_payku import (
    SubscriptionNotFoundError as PaykuSubscriptionNotFoundError,
)
from app.services.write_payku import (
    WriteDisabledError as PaykuWriteDisabledError,
)
from app.services.write_payku import (
    delete_client as payku_delete_client,
)
from app.services.write_payku import (
    delete_subscription as payku_delete_subscription,
)
from app.services.write_payku import (
    update_client as payku_update_client,
)
from app.services.write_toku import (
    CustomerNotFoundError as TokuCustomerNotFoundError,
)
from app.services.write_toku import (
    DeleteAbortedError as TokuDeleteAbortedError,
)
from app.services.write_toku import (
    InvoiceNotFoundError as TokuInvoiceNotFoundError,
)
from app.services.write_toku import (
    ReconciliationRequiredError as TokuReconciliationRequiredError,
)
from app.services.write_toku import (
    SubscriptionNotFoundError as TokuSubscriptionNotFoundError,
)
from app.services.write_toku import (
    WriteDisabledError as TokuWriteDisabledError,
)
from app.services.write_toku import (
    change_subscription_status,
    delete_customer,
    update_customer,
)
from app.services.write_toku import (
    delete_invoice as toku_delete_invoice,
)
from app.services.write_toku import (
    delete_subscription as toku_delete_subscription,
)
from app.services.write_toku import (
    update_invoice as toku_update_invoice,
)
from app.services.write_virtualpos import (
    BillingFlowConflictError,
    ChargeNotFoundError,
    ClientNotFoundError,
    DuplicateClientError,
    DuplicateSubscriptionError,
    FixedPlanChargeBlockedError,
    InvalidClientDataError,
    PaymentNotFoundError,
    PluralCancelForbiddenError,
    ProviderListingError,
    ReconciliationRequiredError,
    RetryBlockedError,
    SubscriptionNotFoundError,
    WriteDisabledError,
    cancel_charge,
    cancel_future_charges,
    cancel_payment,
    cancel_subscription_with_outcome,
    create_charge,
    create_client,
    create_plan,
    create_subscription,
    reassign_subscription_amount,
    retry_charge,
    update_client,
)

# VirtualPOS responde errores de negocio con HTTP 200 + NOK (VirtualPOSAPIError); .response.status_code = code del cuerpo.
_VP_ERRORS = (HTTPStatusError, VirtualPOSAPIError)

router = APIRouter()


def _toku_blocked_detail(exc: TokuWriteBlockedError) -> str:
    """Texto fijo para el cliente: solo el codigo estable. El mensaje completo (con nombres de variables
    internas) queda unicamente en el write_run `blocked`."""
    return f"Escritura Toku bloqueada por las guardas de ambiente ({exc.code})."


def _payku_blocked_detail(exc: PaykuWriteBlockedError) -> str:
    """Igual que Toku: solo el codigo estable; el mensaje completo queda en el write_run `blocked`."""
    return f"Escritura Payku bloqueada por las guardas de ambiente ({exc.code})."


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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Update an approved VirtualPOS client field set through the internal API."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "at_least_one_field_required", "message": "Se requiere al menos un campo."})
    try:
        client = await update_client(db, client_id, changes, requested_by_user_id=current_user.id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except ClientNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "virtualpos_client_not_found", "message": "No se encontró el cliente en VirtualPOS."}) from None
    except InvalidClientDataError:
        raise HTTPException(status_code=422, detail={"code": "invalid_rut", "message": "El RUT no es válido."}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_update", "message": "VirtualPOS rechazó la actualización."}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "virtualpos_update_requires_reconciliation", "message": "La actualización requiere conciliación local."}) from None

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Create an approved VirtualPOS client through the internal API."""
    try:
        client = await create_client(
            db, body.model_dump(exclude_none=True, mode="json"), requested_by_user_id=current_user.id
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except DuplicateClientError:
        raise HTTPException(status_code=409, detail={"code": "virtualpos_client_duplicate_document", "message": "Ya existe un cliente con ese documento de identidad en VirtualPOS"}) from None
    except InvalidClientDataError:
        raise HTTPException(status_code=422, detail={"code": "invalid_rut", "message": "El RUT no es válido."}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_client", "message": "VirtualPOS rechazó el cliente."}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "virtualpos_client_requires_reconciliation", "message": "La operación sobre el cliente requiere conciliación local."}) from None

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Create a VirtualPOS plan through the internal API."""
    try:
        plan = await create_plan(
            db, body.model_dump(exclude_none=True, mode="json"), requested_by_user_id=current_user.id
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_plan", "message": "VirtualPOS rechazó el plan."}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "virtualpos_plan_requires_reconciliation", "message": "La operación sobre el plan requiere conciliación local."}) from None

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Create a VirtualPOS subscription via POST /v3/suscription."""
    try:
        sub = await create_subscription(
            db, body.model_dump(exclude_none=True, mode="json"), requested_by_user_id=current_user.id
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except DuplicateSubscriptionError as exc:
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": str(exc)}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_subscription", "message": "VirtualPOS rechazó la suscripción"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "subscription_requires_reconciliation", "message": "La suscripción requiere reconciliación local"}) from None

    return {"id": str(sub.id), "external_id": sub.external_id, "source": sub.source, "payload": sub.raw_payload or {}}


@router.delete(
    "/virtualpos/subscriptions/{subscription_id}",
    dependencies=[Depends(require_permissions("virtualpos.subscriptions.cancel")), Depends(require_role("admin")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Cancel an active VirtualPOS subscription via DELETE /v3/suscription/{id}.

    Toma el mismo lock que la Opción A, cierra sus solicitudes abiertas y verifica que no queden cobros pendientes
    (campos `requires_reconciliation`/`reconciliation_reason`/`pending_charges`/`processing_charges` en la respuesta)."""
    try:
        sub, outcome = await cancel_subscription_with_outcome(db, subscription_id, requested_by_user_id=current_user.id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "subscription_not_found", "message": "Suscripción no encontrada"}) from None
    except (BillingFlowConflictError, SubscriptionBusyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": str(exc)}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_cancellation", "message": "VirtualPOS rechazó la cancelación"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "cancellation_requires_reconciliation", "message": "La cancelación requiere reconciliación local"}) from None

    return {
        "external_id": sub.external_id,
        "status": sub.status,
        "requires_reconciliation": outcome.requires_reconciliation,
        "reconciliation_reason": outcome.reason,
        "pending_charges": outcome.pending_charges,
        "processing_charges": outcome.processing_charges,
    }


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
    current_user: Annotated[User, Depends(get_current_user)],
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
        charge = await create_charge(
            db, subscription_id, body.model_dump(exclude_none=True, mode="json"), platform=platform,
            requested_by_user_id=current_user.id,
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except FixedPlanChargeBlockedError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_operation", "message": str(exc)}) from None
    except ProviderListingError:
        raise HTTPException(status_code=502, detail={"code": "virtualpos_charge_listing_incomplete", "message": "Listado de cobros de VirtualPOS incompleto o inesperado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_charge", "message": "VirtualPOS rechazó el cargo."}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "virtualpos_charge_requires_reconciliation", "message": "La operación sobre el cargo requiere conciliación local."}) from None

    return {"id": str(charge.id), "external_id": charge.external_id, "source": charge.source, "payload": charge.raw_payload or {}}


@router.delete(
    "/virtualpos/subscriptions/{subscription_id}/charges",
    dependencies=[Depends(require_permissions("virtualpos.charges.cancel")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_future_charges(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    dry_run: bool = True,
) -> dict:
    """Cancela los cargos futuros `pendiente` de una suscripción (sin cancelar la suscripción).

    Con `dry_run=true` (por defecto) solo informa qué se cancelaría; la escritura real exige `dry_run=false`.
    """
    try:
        return await cancel_future_charges(
            db, subscription_id, dry_run=dry_run, requested_by_user_id=current_user.id
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except PluralCancelForbiddenError as exc:
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": str(exc)}) from None
    except ProviderListingError:
        raise HTTPException(status_code=502, detail={"code": "virtualpos_charge_listing_incomplete", "message": "Listado de cobros de VirtualPOS incompleto o inesperado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_charges_cancellation", "message": "VirtualPOS rechazó la cancelación de cargos"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "cancellation_requires_reconciliation", "message": "La cancelación requiere reconciliación local"}) from None


class VirtualPOSAmountReassign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_amount: int = Field(ge=1)
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str | None = Field(default=None, max_length=500)
    internal_code: str | None = Field(default=None, max_length=100)


@router.post(
    "/virtualpos/subscriptions/{subscription_id}/reassign-amount",
    dependencies=[
        Depends(require_permissions("virtualpos.charges.create", "virtualpos.charges.cancel")),
        Depends(require_csrf),
    ],
    tags=["Writes - VirtualPOS"],
)
async def reassign_virtualpos_subscription_amount(
    subscription_id: str,
    body: VirtualPOSAmountReassign,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    dry_run: bool = True,
) -> dict:
    """Crea un cargo nuevo con otro monto y luego cancela los pendientes del periodo reemplazado.

    Con `dry_run=true` (por defecto) no escribe en el proveedor; la confirmación real exige `dry_run=false`.
    """
    try:
        return await reassign_subscription_amount(
            db, subscription_id, body.new_amount, body.effective_date,
            description=body.description, internal_code=body.internal_code, dry_run=dry_run,
            requested_by_user_id=current_user.id,
        )
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except FixedPlanChargeBlockedError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_operation", "message": str(exc)}) from None
    except (BillingFlowConflictError, SubscriptionBusyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": str(exc)}) from None
    except ProviderListingError:
        raise HTTPException(status_code=502, detail={"code": "virtualpos_charge_listing_incomplete", "message": "Listado de cobros de VirtualPOS incompleto o inesperado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_amount_reassignment", "message": "VirtualPOS rechazó la reasignación de monto"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "reassignment_requires_reconciliation", "message": "La reasignación requiere reconciliación local"}) from None


@router.delete(
    "/virtualpos/charges/{charge_id}",
    dependencies=[Depends(require_permissions("virtualpos.charges.cancel")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_charge(
    charge_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Cancel a pending VirtualPOS charge via DELETE /v3/charge/{id}."""
    try:
        charge = await cancel_charge(db, charge_id, requested_by_user_id=current_user.id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except ChargeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "charge_not_found", "message": "Cargo no encontrado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_charge_cancellation", "message": "VirtualPOS rechazó la cancelación del cargo"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "cancellation_requires_reconciliation", "message": "La cancelación requiere reconciliación local"}) from None

    return {"external_id": charge.external_id, "status": charge.status}


@router.post(
    "/virtualpos/charges/{charge_id}/retry",
    dependencies=[Depends(require_permissions("virtualpos.charges.retry")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def retry_virtualpos_charge(
    charge_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Retry a rejected VirtualPOS charge via GET /v3/charge/{id}/retry."""
    try:
        charge = await retry_charge(db, charge_id, requested_by_user_id=current_user.id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except RetryBlockedError as exc:
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": str(exc)}) from None
    except ChargeNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "charge_not_found", "message": "Cargo no encontrado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_charge_retry", "message": "VirtualPOS rechazó el reintento del cargo"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "retry_requires_reconciliation", "message": "El reintento requiere reconciliación local"}) from None

    return {"external_id": charge.external_id, "status": charge.status, "payload": charge.raw_payload or {}}


_VP_SRCS = ("virtualpos", "virtualpos1", "virtualpos2")
_REJECTED_STATUSES = ("rechazado", "rejected", "failed", "failure", "declined", "error")


@router.get(
    "/virtualpos/charges/rejection-reasons",
    dependencies=[Depends(require_permissions("virtualpos.charges.retry"))],
    tags=["Writes - VirtualPOS"],
)
def list_rejection_reasons(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Devuelve los motivos de rechazo distintos registrados en cargos y pagos VirtualPOS."""
    from sqlalchemy import distinct as sa_distinct

    charge_msgs = db.scalars(
        select(sa_distinct(CCharge.raw_payload["rejected_object"]["message"].astext)).where(
            CCharge.source.in_(_VP_SRCS),
            or_(*[func.lower(CCharge.status) == s for s in _REJECTED_STATUSES]),
            CCharge.raw_payload["rejected_object"]["message"].astext.isnot(None),
        )
    ).all()

    payment_msgs = db.scalars(
        select(sa_distinct(CPayment.raw_payload["rejected_object"]["message"].astext)).where(
            CPayment.source.in_(_VP_SRCS),
            CPayment.raw_payload["rejected_object"]["message"].astext.isnot(None),
        )
    ).all()

    reasons = sorted({r for r in (*charge_msgs, *payment_msgs) if r and r.strip()})
    return {"reasons": reasons}


@router.get(
    "/virtualpos/charges/rejected",
    dependencies=[Depends(require_permissions("virtualpos.charges.retry"))],
    tags=["Writes - VirtualPOS"],
)
def list_rejected_virtualpos_charges(
    db: Annotated[Session, Depends(get_db)],
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    platform: Literal["all", "virtualpos", "virtualpos1", "virtualpos2"] = Query(default="all"),
    rejection_reason: str | None = Query(default=None, description="Substring del motivo o código de rechazo"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Lista cargos rechazados de VirtualPOS con filtros de fecha, plataforma y motivo de rechazo."""
    sources = (
        [platform]
        if platform != "all"
        else list(_VP_SRCS)
    )
    q = (
        select(CCharge)
        .where(
            CCharge.source.in_(sources),
            or_(*[func.lower(CCharge.status) == s for s in _REJECTED_STATUSES]),
        )
        .order_by(CCharge.charge_date.desc())
    )
    if date_from:
        q = q.where(func.substring(CCharge.charge_date, 1, 10) >= date_from)
    if date_to:
        q = q.where(func.substring(CCharge.charge_date, 1, 10) <= date_to)
    if rejection_reason:
        pattern = f"%{rejection_reason.lower()}%"
        charge_msg = func.lower(CCharge.raw_payload["rejected_object"]["message"].astext).like(pattern)
        charge_code = func.lower(CCharge.raw_payload["rejected_object"]["code"].astext).like(pattern)
        charge_fallback = func.lower(CCharge.raw_payload["razon_rechazo"].astext).like(pattern)
        payment_subq = exists(
            select(CPayment.id).where(
                CPayment.charge_external_id == CCharge.external_id,
                CPayment.source.in_(sources),
                or_(
                    func.lower(CPayment.raw_payload["rejected_object"]["message"].astext).like(pattern),
                    func.lower(CPayment.raw_payload["rejected_object"]["code"].astext).like(pattern),
                ),
            )
        )
        q = q.where(or_(charge_msg, charge_code, charge_fallback, payment_subq))

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    charges = db.scalars(q.offset(offset).limit(limit)).all()

    charge_external_ids = [c.external_id for c in charges if c.external_id]
    payments_by_charge: dict[str, CPayment] = {}
    if charge_external_ids:
        payments = db.scalars(
            select(CPayment).where(
                CPayment.charge_external_id.in_(charge_external_ids),
                CPayment.source.in_(sources),
            )
        ).all()
        for p in payments:
            if p.charge_external_id and p.charge_external_id not in payments_by_charge:
                payments_by_charge[p.charge_external_id] = p

    def _extract_rejected_object(payload: dict) -> dict:
        return payload.get("rejected_object") or {}

    def _serialize(c: CCharge) -> dict:
        charge_payload = c.raw_payload or {}
        payment = payments_by_charge.get(c.external_id or "")
        payment_payload = payment.raw_payload or {} if payment else {}
        rejected_obj = (
            _extract_rejected_object(charge_payload)
            or _extract_rejected_object(payment_payload)
        )
        rejection_reason = (
            rejected_obj.get("message")
            or charge_payload.get("razon_rechazo")
            or charge_payload.get("reason")
            or charge_payload.get("rejection_reason")
            or payment_payload.get("razon_rechazo")
            or payment_payload.get("reason")
        )
        return {
            "id": str(c.id),
            "external_id": c.external_id,
            "source": c.source,
            "subscription_external_id": c.subscription_external_id,
            "client_external_id": c.client_external_id,
            "amount": c.amount,
            "currency": c.currency,
            "charge_date": c.charge_date,
            "rejection_code": rejected_obj.get("code"),
            "rejection_reason": rejection_reason,
            "rejection_doc_url": rejected_obj.get("doc_url"),
        }

    return {"items": [_serialize(c) for c in charges], "total": total, "offset": offset, "limit": limit}


class BatchRetryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    charge_ids: list[str] = Field(min_length=1, max_length=200)


@router.post(
    "/virtualpos/charges/batch-retry",
    dependencies=[Depends(require_permissions("virtualpos.charges.retry")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def batch_retry_virtualpos_charges(
    body: BatchRetryBody,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Reintenta una lista de cargos rechazados de VirtualPOS."""
    results = []
    for charge_id in body.charge_ids:
        try:
            charge = await retry_charge(db, charge_id, requested_by_user_id=current_user.id)
            results.append({"charge_id": charge_id, "success": True, "status": charge.status, "error": None})
        except WriteDisabledError:
            results.append({"charge_id": charge_id, "success": False, "status": None, "error": "Escrituras deshabilitadas"})
        except RetryBlockedError as exc:
            results.append({"charge_id": charge_id, "success": False, "status": None, "error": str(exc)})
        except ChargeNotFoundError:
            results.append({"charge_id": charge_id, "success": False, "status": None, "error": "Cargo no encontrado"})
        except _VP_ERRORS as exc:
            try:
                if isinstance(exc, VirtualPOSAPIError):
                    vp_msg = f"{exc.error_code or 'NOK'}: {exc.message}"[:300]
                else:
                    body = exc.response.json()
                    vp_msg = body.get("message") or body.get("error") or body.get("detail")
            except (TypeError, ValueError):
                vp_msg = exc.response.text[:300] if exc.response.text else None
            error_msg = vp_msg or f"Error HTTP {exc.response.status_code}"
            results.append({"charge_id": charge_id, "success": False, "status": None, "error": error_msg})
        except Exception as exc:  # noqa: BLE001 - each batch item must report unexpected provider errors.
            results.append({"charge_id": charge_id, "success": False, "status": None, "error": str(exc)})

    succeeded = sum(1 for r in results if r["success"])
    return {"results": results, "succeeded": succeeded, "failed": len(results) - succeeded}


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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Update a Toku customer via PUT /customers/{id}."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "at_least_one_field_required", "message": "Al menos un campo es requerido"})
    try:
        client = await update_customer(db, customer_id, changes, requested_by_user_id=current_user.id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuCustomerNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_client_not_found", "message": "Cliente Toku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_update", "message": "Toku rechazó la actualización"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "update_requires_reconciliation", "message": "La actualización requiere reconciliación local"}) from None

    return {"external_id": client.external_id, "source": client.source, "payload": client.raw_payload or {}}


@router.delete(
    "/toku/customers/{customer_id}",
    dependencies=[Depends(require_permissions("toku.customers.delete")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def delete_toku_customer(
    customer_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Delete a Toku customer via DELETE /customers/{id}."""
    try:
        client = await delete_customer(db, customer_id, requested_by_user_id=current_user.id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuCustomerNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_client_not_found", "message": "Cliente Toku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_deletion", "message": "Toku rechazó la eliminación"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "deletion_requires_reconciliation", "message": "La eliminación requiere reconciliación local"}) from None

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Change Toku subscription status via POST /subscriptions/{id}/status.

    `CANCELLED` es una baja: solo `admin` por esta via directa (las demás bajas pasan por /api/v1/cancellations)."""
    if body.status == "CANCELLED" and not any(role.name == "admin" for role in current_user.roles):
        raise HTTPException(status_code=403, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
    try:
        sub = await change_subscription_status(
            db, subscription_id, body.status, requested_by_user_id=current_user.id
        )
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuSubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_subscription_not_found", "message": "Suscripción Toku no encontrada"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_status_change", "message": "Toku rechazó el cambio de estado"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "status_change_requires_reconciliation", "message": "El cambio de estado requiere reconciliación local"}) from None

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Update a Payku subscription client via PUT /api/suclient/{id}."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "at_least_one_field_required", "message": "Al menos un campo es requerido"})
    try:
        client = await payku_update_client(db, client_id, changes, requested_by_user_id=current_user.id)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "payku_writes_disabled", "message": "Las escrituras a Payku están deshabilitadas en este ambiente."}) from None
    except PaykuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "payku_write_blocked", "message": _payku_blocked_detail(exc)}) from None
    except PaykuClientNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "payku_client_not_found", "message": "Cliente Payku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "payku_rejected_update", "message": "Payku rechazó la actualización"}) from None
    except PaykuApiError:  # d188: HTTP 2xx con status "failed"
        raise HTTPException(status_code=502, detail={"code": "payku_rejected_update", "message": "Payku rechazó la actualización"}) from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "update_requires_reconciliation", "message": "La actualización requiere reconciliación local"}) from None

    return {"external_id": client.external_id, "source": client.source, "payload": client.raw_payload or {}}


@router.delete(
    "/payku/clients/{client_id}",
    dependencies=[Depends(require_permissions("payku.clients.delete")), Depends(require_csrf)],
    tags=["Writes - Payku"],
)
async def delete_payku_client(
    client_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Delete a Payku subscription client via DELETE /api/suclient/{id}."""
    try:
        client = await payku_delete_client(db, client_id, requested_by_user_id=current_user.id)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "payku_writes_disabled", "message": "Las escrituras a Payku están deshabilitadas en este ambiente."}) from None
    except PaykuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "payku_write_blocked", "message": _payku_blocked_detail(exc)}) from None
    except PaykuClientNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "payku_client_not_found", "message": "Cliente Payku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "payku_rejected_deletion", "message": "Payku rechazó la eliminación"}) from None
    except PaykuApiError:  # d188: HTTP 2xx con status "failed"
        raise HTTPException(status_code=502, detail={"code": "payku_rejected_deletion", "message": "Payku rechazó la eliminación"}) from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "deletion_requires_reconciliation", "message": "La eliminación requiere reconciliación local"}) from None

    return {"external_id": client.external_id, "status": client.status}


@router.delete(
    "/payku/subscriptions/{subscription_id}",
    dependencies=[Depends(require_permissions("payku.subscriptions.cancel")), Depends(require_role("admin")), Depends(require_csrf)],
    tags=["Writes - Payku"],
)
async def delete_payku_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Cancel a Payku subscription via DELETE /api/sususcription/{id}."""
    try:
        sub = await payku_delete_subscription(db, subscription_id, requested_by_user_id=current_user.id)
    except PaykuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "payku_writes_disabled", "message": "Las escrituras a Payku están deshabilitadas en este ambiente."}) from None
    except PaykuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "payku_write_blocked", "message": _payku_blocked_detail(exc)}) from None
    except PaykuSubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "payku_subscription_not_found", "message": "Suscripción Payku no encontrada"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "payku_rejected_cancellation", "message": "Payku rechazó la cancelación"}) from None
    except PaykuApiError:  # d188: HTTP 2xx con status "failed"
        raise HTTPException(status_code=502, detail={"code": "payku_rejected_cancellation", "message": "Payku rechazó la cancelación"}) from None
    except PaykuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "cancellation_requires_reconciliation", "message": "La cancelación requiere reconciliación local"}) from None

    return {"external_id": sub.external_id, "status": sub.status}


# ─── VirtualPOS payment writes ───────────────────────────────────────────────

@router.delete(
    "/virtualpos/payments/{payment_id}",
    dependencies=[Depends(require_permissions("virtualpos.payments.cancel")), Depends(require_csrf)],
    tags=["Writes - VirtualPOS"],
)
async def cancel_virtualpos_payment(
    payment_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Cancel a VirtualPOS payment via DELETE /v3/payment/{uuid}."""
    try:
        payment = await cancel_payment(db, payment_id, requested_by_user_id=current_user.id)
    except WriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "virtualpos_writes_disabled", "message": "Las escrituras a VirtualPOS están deshabilitadas en este ambiente."}) from None
    except PaymentNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Pago no encontrado"}) from None
    except _VP_ERRORS as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "virtualpos_rejected_payment_cancellation", "message": "VirtualPOS rechazó la cancelación del pago"}) from None
    except ReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "cancellation_requires_reconciliation", "message": "La cancelación requiere reconciliación local"}) from None

    return {"external_id": payment.external_id, "status": payment.status}


# ─── Toku subscription & invoice writes ──────────────────────────────────────

@router.delete(
    "/toku/subscriptions/{subscription_id}",
    dependencies=[Depends(require_permissions("toku.subscriptions.manage")), Depends(require_role("admin")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def delete_toku_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Delete a Toku subscription via DELETE /subscriptions/{id}."""
    try:
        sub = await toku_delete_subscription(db, subscription_id, requested_by_user_id=current_user.id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuSubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_subscription_not_found", "message": "Suscripción Toku no encontrada"}) from None
    except TokuDeleteAbortedError as exc:
        if exc.code == "INVOICE_IN_PROGRESS":
            # D30: factura en curso niega la baja; nada se anuló.
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INVOICE_IN_PROGRESS",
                    "message": "La suscripción tiene una factura en proceso de cobro: la baja no se realizó.",
                },
            ) from None
        # Fail-closed (MGT-05): la suscripción NO se eliminó. Solo el código fijo, sin texto del proveedor.
        raise HTTPException(
            status_code=502, detail={"code": "toku_deletion_aborted", "message": f"Eliminación abortada: la suscripción no se eliminó ({exc.code})."}
        ) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_deletion", "message": "Toku rechazó la eliminación"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "deletion_requires_reconciliation", "message": "La eliminación requiere reconciliación local"}) from None

    return {"external_id": sub.external_id, "status": sub.status}


class TokuInvoiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int | None = Field(default=None, ge=1)
    due_date: str | None = Field(default=None, max_length=50)


@router.put(
    "/toku/invoices/{invoice_id}",
    dependencies=[Depends(require_permissions("toku.invoices.update")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def update_toku_invoice(
    invoice_id: str,
    body: TokuInvoiceUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Update a Toku invoice amount or due date via PUT /invoices/{id}."""
    changes = body.model_dump(exclude_none=True, mode="json")
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "at_least_one_field_required", "message": "Al menos un campo es requerido"})
    try:
        record = await toku_update_invoice(db, invoice_id, changes, requested_by_user_id=current_user.id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuInvoiceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_invoice_not_found", "message": "Invoice Toku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_invoice_update", "message": "Toku rechazó la actualización del invoice"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "update_requires_reconciliation", "message": "La actualización requiere reconciliación local"}) from None

    return {"external_id": record.external_id, "source": record.source, "payload": record.payload or {}}


@router.delete(
    "/toku/invoices/{invoice_id}",
    dependencies=[Depends(require_permissions("toku.invoices.delete")), Depends(require_csrf)],
    tags=["Writes - Toku"],
)
async def delete_toku_invoice(
    invoice_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Delete a Toku invoice via DELETE /invoices/{id}."""
    try:
        record = await toku_delete_invoice(db, invoice_id, requested_by_user_id=current_user.id)
    except TokuWriteDisabledError:
        raise HTTPException(status_code=403, detail={"code": "toku_writes_disabled", "message": "Las escrituras a Toku están deshabilitadas en este ambiente."}) from None
    except TokuWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail={"code": "toku_write_blocked", "message": _toku_blocked_detail(exc)}) from None
    except TokuInvoiceNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "toku_invoice_not_found", "message": "Invoice Toku no encontrado"}) from None
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "toku_rejected_invoice_deletion", "message": "Toku rechazó la eliminación del invoice"}) from None
    except TokuReconciliationRequiredError:
        raise HTTPException(status_code=503, detail={"code": "deletion_requires_reconciliation", "message": "La eliminación requiere reconciliación local"}) from None

    return {"external_id": record.external_id, "status": (record.payload or {}).get("status", "deleted")}
