"""ML-07 private evaluator for external predictions. No training or model loading."""

from __future__ import annotations

import argparse
import hashlib
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.ml.dataset_export import canonical_json
from app.ml.evaluation_signing import seal, unseal
from app.ml.export_files import (
    load_key,
    read_private_file,
    require_new_private_destination,
    write_private_document,
)
from app.ml.model_evaluation import (
    ARTIFACT_FIELDS,
    VERSION,
    evaluate,
    load_input,
    parse_predictions,
    rowset_sha,
)
from scripts.ml.export_dataset import source_fingerprint

ROOT = Path(__file__).resolve().parents[2]
RECORDS = {"report": ("evaluation-report-v1", "report_id"), "freeze": ("model-freeze-v1", "freeze_id"),
           "receipt": ("test-opening-v1", "receipt_id")}


def read_record(root, relative, *, secret, kind):
    domain, identity = RECORDS[kind]
    return unseal(read_private_file(root, relative, max_bytes=32*1024*1024), secret=secret, domain=domain, id_field=identity)


def assert_identity(record, context):
    if (record["package_id"] != context.plan["package_id"] or record["plan_id"] != context.plan["plan_id"]
            or record["criteria_sha256"] != context.criteria_sha256 or record["version"] != VERSION):
        raise ValueError("Registro pertenece a otro experimento")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluar predicciones externas congeladas, sin entrenar modelos")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-criteria")
    init.add_argument("--plan", required=True)
    init.add_argument("--destination", required=True)
    init.add_argument("--key-file", default="keys/export.key")
    verify = sub.add_parser("verify")
    verify.add_argument("--kind", choices=tuple(RECORDS), required=True)
    verify.add_argument("--document", required=True)
    verify.add_argument("--key-file", default="keys/export.key")
    for name in ("prediction-template", "selection", "freeze", "test"):
        command = sub.add_parser(name)
        for option in ("bundle", "plan", "protocol", "criteria", "destination"):
            command.add_argument(f"--{option}", required=True)
        command.add_argument("--key-file", default="keys/export.key")
        if name == "prediction-template":
            command.add_argument("--candidate", required=True)
            command.add_argument("--phase", choices=("selection", "test"), required=True)
        elif name in {"selection", "test"}:
            command.add_argument("--prediction", action="append", required=True)
        if name == "freeze":
            command.add_argument("--selection-report", required=True)
            command.add_argument("--candidate", required=True)
            command.add_argument("--approval-reference", required=True)
        if name == "test":
            command.add_argument("--freeze", required=True)
            command.add_argument("--open-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "test" and not args.open_test:
            raise ValueError("Apertura explicita de test requerida")
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, timeout=10, check=False)
        if ignored.returncode:
            raise ValueError("Almacenamiento no excluido de Git")
        root = ROOT / ".local/ml-private"
        secret = load_key(root, args.key_file)
        if args.command != "verify":
            require_new_private_destination(root, args.destination)

        def read(relative, limit=32*1024*1024):
            return read_private_file(root, relative, max_bytes=limit)

        def save(kind, value):
            domain, identity = RECORDS[kind]
            write_private_document(root, args.destination, seal(value, secret=secret, domain=domain, id_field=identity))

        if args.command == "verify":
            read_record(root, args.document, secret=secret, kind=args.kind)
        elif args.command == "init-criteria":
            plan = unseal(read(args.plan), secret=secret, domain="evaluation-plan-v1", id_field="plan_id")
            from app.ml.taxonomy import Category

            value = {"version": VERSION, "agreement_sha256": plan["criteria"]["reference_sha256"],
                     "classes": [c.value for c in Category] if plan["task"] == "p1" else [0, 1],
                     "minimum_class_rows": None, "minimum_independent_units": None,
                     "bootstrap_repetitions": 500, "calibration_bins": 10, "comparison_rule": "REVIEW_REQUIRED",
                     "uncertainty_unit": "context" if plan["task"] == "p1" else "subscription"}
            write_private_document(root, args.destination, canonical_json(value))
        else:
            context = load_input(root, args.bundle, secret=secret, plan_data=read(args.plan),
                                 protocol_data=read(args.protocol, 64*1024), criteria_data=read(args.criteria, 64*1024))
            runner = hashlib.sha256(source_fingerprint(ROOT).encode("ascii") + (ROOT / "scripts/ml/evaluate_models.py").read_bytes()).hexdigest()
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, timeout=10, check=True).stdout.decode("ascii").strip()
            if not re.fullmatch(r"[a-f0-9]{40}", revision):
                raise ValueError("Revision de ejecutor invalida")
            environment = {"python": platform.python_version(), "implementation": platform.python_implementation(),
                           "system": platform.system(), "requirements_lock_sha256": hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()}
            environment_sha256 = hashlib.sha256(canonical_json(environment)).hexdigest()
            dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                                        capture_output=True, timeout=10, check=True).stdout)
            if context.manifest["purpose"] == "reviewed-real" and dirty:
                raise ValueError("Confirme codigo local antes de evaluar datos reales")
            if args.command == "prediction-template":
                if args.candidate not in context.plan["comparison"]["candidate_ids"]:
                    raise ValueError("Candidato no predeclarado")
                artifacts = dict.fromkeys(sorted(ARTIFACT_FIELDS))
                artifacts["training_rows_sha256"] = None if args.candidate == "ml02_rules" else rowset_sha(context.plan["partitions"]["train"])
                value = {"version": VERSION, "task": context.plan["task"], "package_id": context.plan["package_id"],
                         "plan_id": context.plan["plan_id"], "phase": args.phase, "candidate_id": args.candidate,
                         "artifacts": artifacts, "rows": [{"row_key": key, "prediction": None} for key in context.plan["partitions"][args.phase]]}
                write_private_document(root, args.destination, canonical_json(value))
            elif args.command == "freeze":
                report = read_record(root, args.selection_report, secret=secret, kind="report")
                assert_identity(report, context)
                if (report["phase"] != "selection" or report["runner_source_sha256"] != runner
                        or report["runner_environment_sha256"] != environment_sha256
                        or args.candidate not in report["candidates"] or not report["candidates"][args.candidate]["eligible_for_manual_freeze"]):
                    raise ValueError("Seleccion no cumple criterios o cambio codigo")
                approval = read(args.approval_reference, 64*1024)
                if not approval.strip():
                    raise ValueError("Aprobacion documentada requerida")
                baseline = context.plan["comparison"]["candidate_ids"][0]
                selected = {name: report["candidates"][name]["artifacts"] for name in {baseline, args.candidate}}
                save("freeze", {"version": VERSION, "package_id": context.plan["package_id"], "plan_id": context.plan["plan_id"],
                                "criteria_sha256": context.criteria_sha256, "selection_report_id": report["report_id"],
                                "candidate_id": args.candidate, "artifacts": selected, "runner_source_sha256": runner,
                                "runner_environment_sha256": environment_sha256,
                                "approval_sha256": hashlib.sha256(approval).hexdigest(),
                                "frozen_at": datetime.now(UTC).isoformat(), "activation_authorized": False})
            else:
                phase = "selection" if args.command == "selection" else "test"
                predictions = [parse_predictions(read(path), context, phase=phase) for path in args.prediction]
                receipt = None
                if phase == "test":
                    frozen = read_record(root, args.freeze, secret=secret, kind="freeze")
                    assert_identity(frozen, context)
                    if (frozen["runner_source_sha256"] != runner or frozen["runner_environment_sha256"] != environment_sha256
                            or len({p["candidate_id"] for p in predictions}) != len(predictions)
                            or {p["candidate_id"]: p["artifacts"] for p in predictions} != frozen["artifacts"]):
                        raise ValueError("Predicciones no corresponden a modelos/pipeline/politica congelados")
                    value = {"version": VERSION, "package_id": context.plan["package_id"], "plan_id": context.plan["plan_id"],
                             "freeze_id": frozen["freeze_id"], "prediction_sha256s": {p["candidate_id"]: p["input_sha256"] for p in predictions},
                             "opened_at": datetime.now(UTC).isoformat(),
                             "report_destination_sha256": hashlib.sha256(args.destination.encode("utf-8")).hexdigest()}
                    receipt = seal(value, secret=secret, domain="test-opening-v1", id_field="receipt_id")
                    # Exclusive marker BEFORE reading any test label; even failed scoring consumes it.
                    write_private_document(root, f"receipts/{context.plan['package_id']}/test.json", receipt)
                report = evaluate(context, predictions, phase=phase, test_receipt=receipt)
                report.update(runner_source_sha256=runner, runner_dirty=dirty, runner_revision=revision,
                              runner_environment=environment, runner_environment_sha256=environment_sha256)
                save("report", report)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError, subprocess.SubprocessError):
        print("Evaluacion rechazada: revise integridad, contratos, congelacion, apertura de test y destino nuevo. Sin entrenamiento.", file=sys.stderr)
        return 2
    print("Operacion privada completada. Sin entrenar, cargar modelos ni autorizar activacion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
