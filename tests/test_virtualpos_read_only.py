import inspect

from app.integrations.virtualpos.client import VirtualPOSClient
from app.main import app


def test_virtualpos_client_exposes_only_approved_read_operations() -> None:
    methods = {
        name
        for name, method in inspect.getmembers(VirtualPOSClient, inspect.iscoroutinefunction)
        if not name.startswith("__")
    }

    assert methods == {"_get", "list_charges", "list_clients", "list_payments", "list_plans", "list_subscriptions"}


def test_api_does_not_register_virtualpos_proxy() -> None:
    paths = set(app.openapi()["paths"])

    assert not any(path.startswith("/api/v1/virtualpos") for path in paths)


def test_toku_and_payku_expose_only_get_routes() -> None:
    provider_paths = {
        path: methods
        for path, methods in app.openapi()["paths"].items()
        if path.startswith(("/api/v1/payku", "/api/v1/toku"))
    }

    assert provider_paths
    assert all(set(methods) == {"get"} for methods in provider_paths.values())
