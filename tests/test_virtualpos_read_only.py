import inspect

from app.integrations.virtualpos.client import VirtualPOSClient
from app.main import app


def test_virtualpos_client_exposes_only_approved_operations() -> None:
    methods = {
        name
        for name, method in inspect.getmembers(VirtualPOSClient, inspect.iscoroutinefunction)
        if not name.startswith("__")
    }

    assert methods == {
        "_get",
        "cancel_subscription",
        "create_card_change_link",
        "create_charge",
        "create_client",
        "create_plan",
        "create_subscription",
        "delete_charge",
        "delete_payment",
        "get_charge",
        "get_client",
        "get_payment",
        "get_plan",
        "get_subscription",
        "list_charges",
        "list_clients",
        "list_payments",
        "list_plans",
        "list_subscriptions",
        "retry_charge",
        "update_client",
    }


def test_api_does_not_register_virtualpos_proxy() -> None:
    paths = set(app.openapi()["paths"])

    assert not any(path.startswith("/api/v1/virtualpos") for path in paths)
    assert "/api/v1/writes/virtualpos/clients/{client_id}" in paths


def test_api_exposes_local_staging_instead_of_provider_proxies() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/staging/records" in paths
    assert "/api/v1/staging/summary" in paths
    assert not any(path.startswith(("/api/v1/payku", "/api/v1/toku")) for path in paths)
