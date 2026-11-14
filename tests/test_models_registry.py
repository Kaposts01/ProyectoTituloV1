"""Cualquier import de un modelo suelto debe registrar todos los modelos (OPS-11: NoReferencedTableError en scripts)."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "app.models.toku_report",
        "app.services.core_vp_etl",
        "app.services.core_payku_etl",
        "scripts.maintenance.project_toku_rejections",
    ],
)
def test_every_foreign_key_resolves_in_a_clean_process(module: str) -> None:
    code = "\n".join(
        [
            f"import {module}",
            "from app.db.session import Base",
            "for table in Base.metadata.tables.values():",
            "    for fk in table.foreign_keys:",
            "        fk.column",
            "print('ok')",
        ]
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr[-500:]
