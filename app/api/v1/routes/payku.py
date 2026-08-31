from typing import Any

from fastapi import APIRouter, HTTPException
from httpx import HTTPStatusError

from app.core.config import settings
from app.integrations.payku.client import PaykuClient

router = APIRouter()


def _ensure_configured() -> None:
    if not settings.payku_base_url or not settings.payku_api_key:
        raise HTTPException(status_code=503, detail="Payku read-only integration is not configured")


def _provider_error(exc: HTTPStatusError) -> None:
    raise HTTPException(status_code=exc.response.status_code, detail="Payku request failed")


@router.get("/clients", tags=["Payku - Read only"])
async def list_clients(page: int = 1, per_page: int = 50) -> Any:
    _ensure_configured()
    async with PaykuClient() as client:
        try:
            return await client.list_clients(page=page, per_page=per_page)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/plans", tags=["Payku - Read only"])
async def list_plans() -> Any:
    _ensure_configured()
    async with PaykuClient() as client:
        try:
            return await client.list_plans()
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/subscriptions", tags=["Payku - Read only"])
async def list_subscriptions(page: int = 1, per_page: int = 50) -> Any:
    _ensure_configured()
    async with PaykuClient() as client:
        try:
            return await client.list_subscriptions(page=page, per_page=per_page)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/transactions", tags=["Payku - Read only"])
async def list_transactions(page: int = 1, per_page: int = 50) -> Any:
    _ensure_configured()
    async with PaykuClient() as client:
        try:
            return await client.list_transactions(page=page, per_page=per_page)
        except HTTPStatusError as exc:
            _provider_error(exc)
