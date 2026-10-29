"""Contrato de rutas y parametros de consulta (D33): renombrar variables/funciones internas no cambia las URLs ni
los parametros de consulta (`?canal=`, `?nombre=`, `?estado=`...) que usa el frontend.

La referencia `tests/golden/openapi_operations.json` se genero con el codigo ANTERIOR al refactor de identificadores.
Los nombres de los parametros de RUTA (`{numero_ficha}` -> `{file_number}`) no son parte de la URL y se normalizan.
"""

import json
import re
from pathlib import Path

from app.main import app

GOLDEN = Path(__file__).parent / "golden" / "openapi_operations.json"


def _operations() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path, item in app.openapi()["paths"].items():
        normalized = re.sub(r"\{[^}]+\}", "{}", path)
        for method, operation in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                params = sorted(f'{p["in"]}:{p["name"]}' for p in operation.get("parameters", []) if p["in"] != "path")
                out[f"{method.upper()} {normalized}"] = params
    return out


def test_routes_and_query_parameters_are_unchanged() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = _operations()
    assert set(actual) == set(expected), {"faltan": sorted(set(expected) - set(actual)), "sobran": sorted(set(actual) - set(expected))}
    changed = {key: (expected[key], actual[key]) for key in expected if expected[key] != actual[key]}
    assert not changed, changed
