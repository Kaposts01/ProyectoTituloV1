"""ML-06 CLI: preregistration and label-blind preflight only. No training entrypoint."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import re
import subprocess
import sys
from pathlib import Path

from app.ml.dataset_export import canonical_json, signature
from app.ml.evaluation_package import prepare_plan
from app.ml.evaluation_protocol import PROTOCOL_VERSION, parse_protocol
from app.ml.export_files import load_key, read_private_file, write_private_document
from app.ml.export_snapshot import parse_json
from scripts.ml.export_dataset import source_fingerprint

ROOT = Path(__file__).resolve().parents[2]


def template(task: str) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION, "task": task, "experiment_id": "review-required",
        **{name: "REEMPLAZAR-ISO-CON-ZONA" for name in (
            "train_start", "train_end", "calibration_end", "selection_end", "test_end")},
        "group_policy": "temporal", "expected_sources": ["toku" if task == "p1" else "virtualpos1"],
        "minimum_rows_per_source_split": 1, "criteria_status": "draft", "practical_margin": None,
        "minimum_prediction_coverage": None, "criteria_reference_sha256": None,
        "seed": 17, "max_trials": 5, "max_fit_seconds": 60, "max_memory_mb": 1024, "max_threads": 2,
    }


def sign_plan(plan: dict, *, secret: bytes) -> bytes:
    value = dict(plan)
    value["plan_id"] = hashlib.sha256(canonical_json(value)).hexdigest()
    value["signature"] = signature(canonical_json(value), secret, domain="evaluation-plan-v1")
    return canonical_json(value)


def verify_plan(data: bytes, *, secret: bytes) -> None:
    value = parse_json(data)
    if type(value) is not dict:
        raise ValueError("Plan invalido")
    mac = value.pop("signature", None)
    if (not isinstance(mac, str) or not re.fullmatch(r"[a-f0-9]{64}", mac)
            or not hmac.compare_digest(mac, signature(canonical_json(value), secret, domain="evaluation-plan-v1"))):
        raise ValueError("Firma invalida")
    plan_id = value.pop("plan_id", None)
    if value.get("protocol_version") != PROTOCOL_VERSION or plan_id != hashlib.sha256(canonical_json(value)).hexdigest():
        raise ValueError("Version o fingerprint invalido")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preparar evaluacion ML aislada, sin entrenamiento ni lectura de etiquetas")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-protocol")
    init.add_argument("--task", choices=("p1", "p2"), required=True)
    init.add_argument("--destination", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--bundle", required=True)
    plan.add_argument("--protocol", required=True)
    plan.add_argument("--destination", required=True)
    plan.add_argument("--key-file", default="keys/export.key")
    verify = sub.add_parser("verify-plan")
    verify.add_argument("--document", required=True)
    verify.add_argument("--key-file", default="keys/export.key")
    args = parser.parse_args(argv)
    try:
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, check=False, timeout=10)
        if ignored.returncode:
            raise ValueError("Destino no excluido de Git")
        root = ROOT / ".local/ml-private"
        root.parent.mkdir(exist_ok=True)
        if args.command == "init-protocol":
            write_private_document(root, args.destination, canonical_json(template(args.task)))
        else:
            secret = load_key(root, args.key_file)
            if args.command == "verify-plan":
                verify_plan(read_private_file(root, args.document, max_bytes=32 * 1024 * 1024), secret=secret)
            else:
                protocol = parse_protocol(read_private_file(root, args.protocol, max_bytes=64 * 1024))
                result = prepare_plan(root, args.bundle, secret=secret, protocol=protocol)
                revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                          check=True, timeout=10).stdout.decode("ascii").strip()
                dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                                            capture_output=True, check=True, timeout=10).stdout)
                if result["input_purpose"] == "reviewed-real" and dirty:
                    raise ValueError("Confirme codigo antes de planificar datos reales")
                result["runner_revision"] = revision
                result["runner_dirty"] = dirty
                result["runner_dependencies_sha256"] = hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()
                result["runner_source_sha256"] = hashlib.sha256(
                    source_fingerprint(ROOT).encode("ascii") + (ROOT / "scripts/ml/prepare_evaluation.py").read_bytes()).hexdigest()
                write_private_document(root, args.destination, sign_plan(result, secret=secret))
                if result["status"] == "blocked":
                    print("Plan privado guardado con bloqueos; revise criterios, cobertura y tamanos. No se entreno ni evaluo ningun modelo.")
                    return 3
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        print("Operacion rechazada: revise protocolo, integridad, clave, permisos y destino nuevo. No publique datos privados.", file=sys.stderr)
        return 2
    print("Preparacion local completada; sin entrenamiento, metricas de modelos ni apertura de etiquetas del test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
