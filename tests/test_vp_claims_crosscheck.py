"""CT-01 lote 4: script de cruce [CLAIM:VP-Cxx] doc vs suite de contrato. Solo lee archivos (no ejecuta la suite)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("vp_claims_crosscheck", ROOT / "scripts/diagnostics/vp_claims_crosscheck.py")
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_repo_contract_tests_are_all_tagged_and_consistent(capsys):
    result = cc.crosscheck(ROOT)
    assert result.errors == []
    assert len(result.tests) >= 17 and all(len(refs) >= 1 for refs in result.tests.values())
    assert result.status("VP-C07") == "ok"
    assert cc.main([]) == 0
    assert "VP-C07" in capsys.readouterr().out


def test_detects_missing_and_mismatched_tags_and_gaps(tmp_path, capsys):
    _write(tmp_path, "docs/integrations/virtualpos/resources/a.md", "x [CLAIM:VP-C01] y\n[CLAIM:VP-C02]\n")
    _write(tmp_path, "tests_contract/virtualpos/test_x.py", '''
import pytest

@pytest.mark.contract(claim="VP-C01")
def test_ok(claim):
    """[CLAIM:VP-C01] Doc: a.md."""

@pytest.mark.contract(claim="VP-C03")
@pytest.mark.contract_write
def test_untagged(claim):
    """Doc: sin etiqueta."""

@pytest.mark.contract(claim="VP-C04")
def test_wrong(claim):
    """[CLAIM:VP-C05] Doc: otra."""

def test_helper_without_marker():
    """[CLAIM:VP-C09] no cuenta: sin marcador."""
''')
    result = cc.crosscheck(tmp_path)
    assert {c: result.status(c) for c in result.claims()} == {
        "VP-C01": "ok", "VP-C02": "sin_prueba", "VP-C03": "sin_doc", "VP-C04": "sin_doc"}
    assert len(result.errors) == 2
    assert any("test_untagged" in e and "sin etiqueta" in e for e in result.errors)
    assert any("test_wrong" in e and "VP-C05" in e for e in result.errors)
    assert result.docs["VP-C01"] == ["docs/integrations/virtualpos/resources/a.md:1"]
    assert cc.main(["--root", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["claims"][0] == {"claim": "VP-C01", "status": "ok",
                                    "docs": ["docs/integrations/virtualpos/resources/a.md:1"],
                                    "tests": ["tests_contract/virtualpos/test_x.py::test_ok"]}
