"""Tests OFFLINE de la infraestructura de la suite de contrato VirtualPOS (guardas, informe de drift, aislamiento)."""

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import VP_PRODUCTION_HOST, VP_SANDBOX_HOST
from tests_contract.virtualpos import guards
from tests_contract.virtualpos.drift import ClaimRecorder

SANDBOX_URL = f"https://{VP_SANDBOX_HOST}"
ROOT = Path(__file__).resolve().parent.parent


def test_base_guards_pass_when_everything_is_right():
    assert guards.base_guard_problems("sandbox", SANDBOX_URL, "1") == []


def test_guard_rejects_non_sandbox_env_mode():
    for mode in ("production", "qa"):
        assert any("APP_ENV" in p for p in guards.base_guard_problems(mode, SANDBOX_URL, "1"))


def test_guard_rejects_production_host():
    problems = guards.base_guard_problems("sandbox", f"https://{VP_PRODUCTION_HOST}/", "1")
    assert any("PRODUCCION" in p for p in problems)


def test_guard_rejects_lookalike_and_empty_hosts():
    for url in (f"https://{VP_SANDBOX_HOST}.evil.com", f"https://x.{VP_SANDBOX_HOST}", "", "https://example.com"):
        assert guards.base_guard_problems("sandbox", url, "1"), url


def test_guard_requires_contract_tests_flag():
    for value in (None, "", "0", "true"):
        assert any(guards.ENV_CONTRACT_TESTS in p for p in guards.base_guard_problems("sandbox", SANDBOX_URL, value))


def test_write_guards_each_condition_separately():
    assert guards.write_guard_problems("1", True) == []
    only_flag_missing = guards.write_guard_problems(None, True)
    assert len(only_flag_missing) == 1 and guards.ENV_CONTRACT_WRITES in only_flag_missing[0]
    only_enabled_missing = guards.write_guard_problems("1", False)
    assert len(only_enabled_missing) == 1 and "VIRTUALPOS_SANDBOX_WRITES_ENABLED" in only_enabled_missing[0]


def test_missing_subscription_variables_are_named_not_valued():
    assert guards.missing_sub_vars(None, "abc", (guards.ENV_SUB_FIXED,)) == [guards.ENV_SUB_FIXED]
    assert guards.missing_sub_vars("x", " ", (guards.ENV_SUB_FIXED, guards.ENV_SUB_VARIABLE)) == [
        guards.ENV_SUB_VARIABLE
    ]
    assert guards.missing_sub_vars("x", "y", (guards.ENV_SUB_FIXED, guards.ENV_SUB_VARIABLE)) == []


def test_guard_messages_never_contain_values():
    secret_url = f"https://{VP_PRODUCTION_HOST}/token-abc123"
    text = " ".join(guards.base_guard_problems("production", secret_url, "nope"))
    assert "abc123" not in text and "nope" not in text


def test_drift_report_format_and_sanitizing():
    with tempfile.TemporaryDirectory() as tmp:
        _check_drift_report(Path(tmp))


def _check_drift_report(tmp_path: Path):
    api_key, secret = "KEY-super-secret-111", "SEC-super-secret-222"
    recorder = ClaimRecorder(secrets=(api_key, secret))
    recorder.check(
        "VP-C99", "docs/x.md", "HTTP 400 E-113", "HTTP 200", note=f"usa {api_key}", http_status=200,
        error_code=None,
    )
    recorder.check(
        "VP-C98", "docs/y.md",
        {"api_key": api_key, "Signature": "eyJhbGciOi.eyJhcGlf.abcdef", "rut": "12.345.678-9"},
        {"texto": f"cliente 12.345.678-9 pan 4111111111111111 secreto {secret}", "ok": True},
        error_code="E-079",
    )
    json_path, md_path = recorder.write(tmp_path, now=datetime(2026, 10, 27, 9, 30, 15, tzinfo=UTC))
    assert json_path.name == "drift-20261027-093015.json" and md_path.name == "drift-20261027-093015.md"
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    assert {"claim", "document", "expected", "observed", "matches", "date", "http_status", "error_code"} <= set(rows[0])
    assert rows[0]["matches"] is False and rows[1]["error_code"] == "E-079"
    everything = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    for leak in (api_key, secret, "eyJhbGciOi", "12.345.678-9", "4111111111111111"):
        assert leak not in everything
    assert re.search(r"\| VP-C99 \|", md_path.read_text(encoding="utf-8"))


def test_drift_check_does_not_raise_on_disagreement():
    recorder = ClaimRecorder()
    record = recorder.check("VP-C97", "d.md", "a", "b")
    assert record.matches is False and len(recorder.records) == 1
    assert recorder.check("VP-C97", "d.md", "a", "b", matches=True).matches is True


def test_default_suite_does_not_collect_contract_tests():
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert re.search(r"^testpaths = tests$", ini, re.M)
    assert 'addopts = -m "not contract"' in ini
    assert not list((ROOT / "tests").glob("**/test_*claims.py"))


def test_vp_c19_json_kind_treats_int_and_float_as_number():
    from tests_contract.virtualpos.test_read_claims import _json_kind

    assert _json_kind(9900) == "number" and _json_kind(99.5) == "number"
    assert _json_kind(True) == "boolean" and _json_kind("9900") == "str"


def test_vp_c07_first_post_expected_matches_observed_http_200():
    rec = ClaimRecorder()
    record = rec.check("VP-C07", "doc", "HTTP 200", "HTTP 200", http_status=200)
    assert record.matches is True
