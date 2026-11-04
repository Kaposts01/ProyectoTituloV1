"""Conftest de la suite de contrato VirtualPOS: guardas duras, informe de drift y limpieza de cargos.

Sin base de datos. Solo corre con APP_ENV=sandbox, host de sandbox y CONTRACT_TESTS=1.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests_contract.virtualpos import guards, provider
from tests_contract.virtualpos.drift import ClaimRecorder

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "contract" / "virtualpos"
_STATE: dict[str, ClaimRecorder] = {}


def _settings():
    try:
        from app.core.config import settings
    except Exception as exc:  # noqa: BLE001 - configuracion invalida: abortar sin mostrar valores
        pytest.exit(f"[guarda contrato VP] No se pudo cargar la configuracion ({type(exc).__name__}).", returncode=2)
    return settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "contract(claim): prueba de contrato contra el sandbox (claim='VP-Cxx')")
    config.addinivalue_line("markers", "contract_write: prueba de contrato que escribe en el sandbox")
    s = _settings()
    problems = guards.base_guard_problems(s.env_mode, s.virtualpos_base_url, os.environ.get(guards.ENV_CONTRACT_TESTS))
    if problems:
        pytest.exit("[guarda contrato VP] " + " | ".join(problems), returncode=2)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if any(item.get_closest_marker("contract_write") for item in items):
        s = _settings()
        problems = guards.write_guard_problems(os.environ.get(guards.ENV_CONTRACT_WRITES), s.virtualpos_writes_enabled)
        if problems:
            pytest.exit("[guarda contrato VP escritura] " + " | ".join(problems), returncode=2)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    recorder = _STATE.get("recorder")
    if recorder is not None and recorder.records:
        json_path, md_path = recorder.write(REPORT_DIR)
        print(f"\n[contrato VP] informe de drift: {json_path.relative_to(ROOT)} y {md_path.name}")


@pytest.fixture(scope="session")
def recorder() -> ClaimRecorder:
    s = _settings()
    rec = ClaimRecorder(secrets=(s.virtualpos_api_key, s.virtualpos_secret_key))
    _STATE["recorder"] = rec
    return rec


@pytest.fixture
def claim(recorder: ClaimRecorder) -> ClaimRecorder:
    """`claim.check(claim_id, document, expected, observed, note="")` registra el drift sin fallar."""
    return recorder


def _sub_from_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        pytest.skip(f"Falta la variable {name} (suscripcion de prueba del sandbox).")
    return value


@pytest.fixture
def sub_fixed() -> str:
    return _sub_from_env(guards.ENV_SUB_FIXED)


@pytest.fixture
def sub_variable() -> str:
    return _sub_from_env(guards.ENV_SUB_VARIABLE)


@dataclass
class ChargeRegistry:
    charges: list[tuple[str, str]] = field(default_factory=list)  # (suscription_id, charge_id)

    def add(self, sub_id: str, charge_id: str) -> None:
        self.charges.append((sub_id, charge_id))

    @staticmethod
    def internal_code(claim_id: str) -> str:
        return f"CT-{claim_id}-{uuid.uuid4().hex[:8]}-{datetime.now(UTC):%Y%m%d%H%M}"

    def create(
        self, sub_id: str, claim_id: str, *, days: int = 20, internal_code: str | None = None,
        charge_date: str | None = None, amount: int = 1000,
    ) -> provider.Resp:
        """POST /v3/charge (sin reintentos). Registra el cargo si la respuesta trae id."""
        date = charge_date or (provider.chile_today() + timedelta(days=days)).strftime("%Y-%m-%d")
        resp = provider.call("POST", "/v3/charge", payload={
            "suscription_id": sub_id, "charge_date": date, "amount": amount,
            "description": f"contract test {claim_id}", "internal_code": internal_code or self.internal_code(claim_id),
        })
        cid = provider.charge_id_of(resp.body)
        if cid:
            self.add(sub_id, cid)
        return resp

    def cleanup(self) -> list[str]:
        """Cancela cada cargo registrado que siga `pendiente` (reconsultando antes). Devuelve los fallos."""
        failures: list[str] = []
        for _sub_id, cid in self.charges:
            got = provider.call("GET", f"/v3/charge/{cid}")
            if not got.ok:
                failures.append(f"no se pudo reconsultar el cargo {cid} (HTTP {got.status})")
            elif provider.charge_obj(got.body).get("status") == "pendiente":
                done = provider.call("DELETE", f"/v3/charge/{cid}")
                if not done.ok:
                    failures.append(f"no se pudo cancelar el cargo {cid} (HTTP {done.status}, {done.error_code})")
        return failures


@pytest.fixture(scope="session")
def created_charges():
    """Registro de cargos creados; al terminar la sesion cancela los que sigan pendientes (si falla, ERROR)."""
    registry = ChargeRegistry()
    yield registry
    failures = registry.cleanup()
    if failures:
        raise RuntimeError("Limpieza de cargos de contrato incompleta: " + "; ".join(failures))
