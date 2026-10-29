"""Offline package contracts for the nine repository-scoped Codex skills.

These tests verify discoverable artifacts, not the model's behavior. Behavioral
reviews use the separate synthetic cases and an explicitly assessed report.
No application imports, environment credentials, database or network are needed.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills"
SKILLS = (
    "synkmetrix-python-api",
    "synkmetrix-postgres-orm",
    "synkmetrix-react-typescript",
    "synkmetrix-dashboard-recharts",
    "synkmetrix-etl-pandas",
    "synkmetrix-integrations-httpx",
    "synkmetrix-scheduler-sse",
    "synkmetrix-quality-tests",
    "synkmetrix-runtime-ci",
)
CASES = json.loads((ROOT / "tests/fixtures/skills/cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_discoverable_manifest(name: str) -> None:
    content = (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
    assert match is not None, "Codex needs YAML frontmatter at the start"
    metadata = yaml.safe_load(match.group(1))
    assert isinstance(metadata, dict)
    assert metadata["name"] == name
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
    assert len(name) <= 64
    assert isinstance(metadata["description"], str)
    assert 1 <= len(metadata["description"].strip()) <= 1024
    assert content[match.end() :].strip(), "A manifest alone has no working instructions"


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_invocable_ui_metadata(name: str) -> None:
    metadata = yaml.safe_load((SKILL_ROOT / name / "agents/openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]
    assert isinstance(interface["display_name"], str) and interface["display_name"].strip()
    assert 25 <= len(interface["short_description"]) <= 64
    assert f"${name}" in interface["default_prompt"]
    assert metadata.get("policy", {}).get("allow_implicit_invocation", True) is True


@pytest.mark.parametrize("name", SKILLS)
def test_skill_bundled_references_resolve(name: str) -> None:
    folder = (SKILL_ROOT / name).resolve()
    manifest = (folder / "SKILL.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)]+)\)", manifest)
    local_targets = [target for target in targets if not target.startswith(("https://", "http://", "#"))]
    assert local_targets, "Each current package ships a linked review reference"
    for target in local_targets:
        reference = (folder / target.split("#", 1)[0]).resolve()
        assert reference.is_relative_to(folder), "Bundled links must stay inside the skill package"
        assert reference.is_file(), f"Missing reference: {target}"
        assert reference.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("name", SKILLS)
def test_skill_has_three_offline_behavior_cases(name: str) -> None:
    cases = [case for case in CASES if case["skill"] == name]
    assert len(cases) == 3
    for case in cases:
        assert isinstance(case["request"], str) and case["request"].strip()
        assert isinstance(case["artifact"], str) and case["artifact"].strip()
        assert "expected" not in case and "answer" not in case, "Evaluator input must not contain a gold answer"


def test_behavior_case_ids_and_skill_inventory_are_unambiguous() -> None:
    counts = Counter(case["id"] for case in CASES)
    assert len(counts) == 27
    assert all(count == 1 for count in counts.values())
    assert {case["skill"] for case in CASES} == set(SKILLS)
    discovered = {path.name for path in SKILL_ROOT.iterdir() if (path / "SKILL.md").is_file()}
    assert set(SKILLS).issubset(discovered)
