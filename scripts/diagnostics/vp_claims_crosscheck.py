"""Cruce de afirmaciones [CLAIM:VP-Cxx] entre la doc de VirtualPOS y la suite de contrato (CT-01, lote 4).

SOLO LEE ARCHIVOS: no importa la app, no abre la base, no llama a VirtualPOS y no ejecuta la suite de contrato.

Fuentes
- Doc: `docs/integrations/virtualpos/**/*.md`, etiquetas `[CLAIM:VP-Cxx]` (archivo y linea).
- Pruebas: `tests_contract/virtualpos/test_*.py`, marcador `@pytest.mark.contract(claim="VP-Cxx")` y la etiqueta
  `[CLAIM:VP-Cxx]` al inicio del docstring de la prueba.

Resultado por afirmacion: `ok` (doc y prueba), `sin_prueba` (solo en la doc), `sin_doc` (prueba sin observacion en la
doc todavia). Errores de estructura (codigo de salida 1): prueba con marcador y sin etiqueta en el docstring, o con
etiqueta distinta del marcador. Uso:

    python scripts/diagnostics/vp_claims_crosscheck.py [--root RUTA] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = Path("docs/integrations/virtualpos")
TESTS_DIR = Path("tests_contract/virtualpos")
TAG = re.compile(r"\[CLAIM:(VP-C\d+)\]")
MARKER = re.compile(r'@pytest\.mark\.contract\(\s*claim\s*=\s*"(VP-C\d+)"\s*\)')
DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")


@dataclass
class TestRef:
    file: str
    line: int
    name: str
    marker: str
    docstring_tags: list[str]


@dataclass
class CrossCheck:
    docs: dict[str, list[str]] = field(default_factory=dict)  # claim -> ["archivo:linea", ...]
    tests: dict[str, list[TestRef]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def status(self, claim: str) -> str:
        if claim in self.docs and claim in self.tests:
            return "ok"
        return "sin_prueba" if claim in self.docs else "sin_doc"

    def claims(self) -> list[str]:
        return sorted(set(self.docs) | set(self.tests), key=lambda c: int(c.split("C")[1]))

    def as_dict(self) -> dict:
        return {
            "claims": [{"claim": c, "status": self.status(c), "docs": self.docs.get(c, []),
                        "tests": [f"{t.file}::{t.name}" for t in self.tests.get(c, [])]} for c in self.claims()],
            "errors": self.errors,
        }


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def scan_docs(root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted((root / DOCS_DIR).rglob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for claim in TAG.findall(line):
                out.setdefault(claim, []).append(f"{_rel(path, root)}:{n}")
    return out


def _docstring_head(lines: list[str], start: int) -> str:
    """Primera linea no vacia tras la definicion (el inicio del docstring), si es un docstring."""
    for line in lines[start:start + 3]:
        text = line.strip()
        if text:
            return text if text.startswith(('"""', "'''")) else ""
    return ""


def scan_tests(root: Path) -> tuple[dict[str, list[TestRef]], list[str]]:
    out: dict[str, list[TestRef]] = {}
    errors: list[str] = []
    for path in sorted((root / TESTS_DIR).glob("test_*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        pending: tuple[str, int] | None = None
        for i, line in enumerate(lines):
            marker = MARKER.search(line)
            if marker:
                pending = (marker.group(1), i + 1)
                continue
            match = DEF.match(line)
            if match and pending is not None:
                claim, _marker_line = pending
                tags = TAG.findall(_docstring_head(lines, i + 1))
                ref = TestRef(_rel(path, root), i + 1, match.group(1), claim, tags)
                out.setdefault(claim, []).append(ref)
                where = f"{ref.file}:{ref.line} {ref.name}"
                if not tags:
                    errors.append(f"{where}: marcador {claim} sin etiqueta [CLAIM:{claim}] en el docstring")
                elif tags != [claim]:
                    errors.append(f"{where}: el docstring dice {', '.join(tags)} pero el marcador es {claim}")
                pending = None
            elif match:
                pending = None
    return out, errors


def crosscheck(root: Path = ROOT) -> CrossCheck:
    tests, errors = scan_tests(root)
    return CrossCheck(docs=scan_docs(root), tests=tests, errors=errors)


def format_text(result: CrossCheck) -> str:
    rows = ["claim    estado      pruebas  doc"]
    for claim in result.claims():
        tests = len(result.tests.get(claim, []))
        docs = result.docs.get(claim, [])
        rows.append(f"{claim:<8} {result.status(claim):<11} {tests:>7}  {docs[0] if docs else '-'}"
                    + (f" (+{len(docs) - 1})" if len(docs) > 1 else ""))
    totals = {s: sum(1 for c in result.claims() if result.status(c) == s) for s in ("ok", "sin_prueba", "sin_doc")}
    rows.append(f"total={len(result.claims())} " + " ".join(f"{k}={v}" for k, v in totals.items()))
    rows.extend(f"ERROR {e}" for e in result.errors)
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="raiz del repositorio (por defecto, la de este script)")
    parser.add_argument("--json", action="store_true", help="salida JSON")
    args = parser.parse_args(argv)
    result = crosscheck(args.root.resolve())
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=1) if args.json else format_text(result))
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
