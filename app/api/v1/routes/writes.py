from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.services.write_virtualpos import (
    ClientNotFoundError,
    DuplicateClientError,
    InvalidClientDataError,
    LocalStateUnavailableError,
    ReconciliationRequiredError,
    WriteDisabledError,
    create_client,
    create_plan,
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


class VirtualPOSPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
