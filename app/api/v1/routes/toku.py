from typing import Any

from fastapi import APIRouter, HTTPException
from httpx import HTTPStatusError

from app.core.config import settings
from app.integrations.toku.client import TokuClient

router = APIRouter()


def _ensure_configured() -> None:
    if not settings.toku_base_url or not settings.toku_api_key:
        raise HTTPException(status_code=503, detail="Toku read-only integration is not configured")


def _provider_error(exc: HTTPStatusError) -> None:
    raise HTTPException(status_code=exc.response.status_code, detail="Toku request failed")


@router.get("/customers", tags=["Toku - Read only"])
async def list_customers(page_size: int = 100) -> Any:
    _ensure_configured()
    async with TokuClient() as client:
        try:
            return await client.list_customers(page_size=page_size)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/subscriptions", tags=["Toku - Read only"])
async def list_subscriptions(page: int = 1, page_size: int = 100) -> Any:
    _ensure_configured()
    async with TokuClient() as client:
        try:
            return await client.list_subscriptions(page=page, page_size=page_size)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/payment-methods", tags=["Toku - Read only"])
async def list_payment_methods(page: int = 1, page_size: int = 100) -> Any:
    _ensure_configured()
    async with TokuClient() as client:
        try:
            return await client.list_payment_methods(page=page, page_size=page_size)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/invoices", tags=["Toku - Read only"])
async def list_invoices(page_size: int = 100) -> Any:
    _ensure_configured()
    async with TokuClient() as client:
        try:
            return await client.list_invoices(page_size=page_size)
        except HTTPStatusError as exc:
            _provider_error(exc)


@router.get("/transactions", tags=["Toku - Read only"])
async def list_transactions(page: int = 1, page_size: int = 100) -> Any:
    _ensure_configured()
    async with TokuClient() as client:
        try:
            return await client.list_transactions(page=page, page_size=page_size)
        except HTTPStatusError as exc:
            _provider_error(exc)
