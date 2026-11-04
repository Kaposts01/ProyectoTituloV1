from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_health_check(monkeypatch) -> None:
    # Independiente del .env local: fija el valor que el endpoint devuelve tal cual.
    monkeypatch.setattr(settings, "app_env", "development")
    client = TestClient(app, base_url="https://testserver")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
