"""Contrato de claves JSON de la API (decision D33).

Las claves de las respuestas se quedan como estan (en español) aunque los identificadores internos pasen a ingles.
`assert_keys(nombre, payload)` compara el conjunto de rutas de claves de `payload` con `tests/golden/<nombre>.json`.
Para regenerar la referencia a proposito: `UPDATE_CONTRACT_KEYS=1` (solo cuando cambie el contrato a proposito).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden"
_DYNAMIC_KEY = re.compile(r"^(\d{4}-\d{2}(-\d{2})?|\d+|[0-9a-f]{8}-[0-9a-f-]{27,})$")


def key_paths(obj: Any, prefix: str = "") -> set[str]:
    """Rutas de claves (`a.b[].c`); las claves dinamicas (meses, ids numericos) se normalizan a `*`."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = "*" if _DYNAMIC_KEY.match(str(key)) else str(key)
            out.add(f"{prefix}.{name}")
            out |= key_paths(value, f"{prefix}.{name}")
    elif isinstance(obj, list):
        for item in obj:
            out |= key_paths(item, f"{prefix}[]")
    return out


def assert_keys(name: str, payload: Any) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    actual = sorted(key_paths(payload))
    if os.environ.get("UPDATE_CONTRACT_KEYS") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected, {
        "faltan": sorted(set(expected) - set(actual)),
        "sobran": sorted(set(actual) - set(expected)),
    }
