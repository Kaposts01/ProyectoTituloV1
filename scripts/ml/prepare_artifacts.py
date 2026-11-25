"""ML-08 preparation CLI: no fitting, deserialization, DB writes or CRM activation."""

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

from app.ml.artifacts import ARTIFACT_VERSION, prepare_artifact, verify_artifact
from app.ml.dataset_export import canonical_json
from app.ml.export_files import (
    load_key,
    read_private_file,
    require_new_private_destination,
    write_private_document,
)
from app.ml.export_snapshot import parse_json
from app.ml.pipelines import (
    PIPELINE_VERSION,
    TASKS,
    build_pipeline,
    environment,
    recipe,
)
from app.ml.temporal_dataset import SOURCES

ROOT = Path(__file__).resolve().parents[2]


def template(candidate, source, *, seed=17):
    definition, runtime = recipe(candidate, seed=seed), environment()
    return {"version": ARTIFACT_VERSION, "task": TASKS[candidate], "source": source, "candidate_id": candidate,
            "purpose": "synthetic", "training_status": "unfitted", "provenance_reviewed": False,
            "pipeline_version": PIPELINE_VERSION, "feature_schema_sha256": definition["schema_sha256"],
            "seed": seed, "recipe_sha256": hashlib.sha256(canonical_json(definition)).hexdigest(),
            "environment": runtime, "package_id": None, "plan_id": None, "training_rows_sha256": None,
            "calibration_rows_sha256": None, "calibrator_sha256": None, "fit_code_sha256": None,
            "fit_environment_sha256": hashlib.sha256(canonical_json(runtime)).hexdigest(),
            "pipeline_sha256": None, "decision_policy_sha256": None,
            "payload": {"path": "REVIEW-REQUIRED", "sha256": None, "bytes": None, "format": "skops"}, "evaluation": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preparar pipelines y artefactos privados, sin entrenamiento ni activacion")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("pipeline", "template", "environment", "seal", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--key-file", default="keys/export.key")
        if name != "verify":
            command.add_argument("--destination", required=True)
        if name in {"pipeline", "template"}:
            command.add_argument("--candidate", choices=tuple(TASKS), required=True)
            command.add_argument("--seed", type=int, default=17)
        if name == "pipeline":
            command.add_argument("--construct-unfitted", action="store_true")
        if name == "template":
            command.add_argument("--source", choices=tuple(sorted(SOURCES)), required=True)
        if name == "seal":
            command.add_argument("--descriptor", required=True)
        if name == "verify":
            command.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, timeout=10, check=False)
        if ignored.returncode:
            raise ValueError("Destino no excluido de Git")
        root = ROOT / ".local/ml-private"
        secret = load_key(root, args.key_file)
        if args.command != "verify":
            require_new_private_destination(root, args.destination)
        if args.command == "verify":
            if not verify_artifact(root, args.manifest, secret=secret).compatible:
                raise ValueError("El entorno actual no coincide con el del artefacto")
        elif args.command == "environment":
            write_private_document(root, args.destination, canonical_json(environment()))
        elif args.command == "template":
            write_private_document(root, args.destination, canonical_json(template(args.candidate, args.source, seed=args.seed)))
        elif args.command == "pipeline":
            description = recipe(args.candidate, seed=args.seed)
            if args.construct_unfitted:
                pipeline = build_pipeline(args.candidate, seed=args.seed)
                from sklearn.exceptions import NotFittedError
                from sklearn.utils.validation import check_is_fitted

                try:
                    check_is_fitted(pipeline)
                except NotFittedError:
                    description["constructed_unfitted"] = True
                else:
                    raise ValueError("La fabrica devolvio un estimador ajustado inesperadamente")
            write_private_document(root, args.destination, canonical_json(description))
        else:
            descriptor = parse_json(read_private_file(root, args.descriptor, max_bytes=128_000))
            if descriptor.get("purpose") == "reviewed-real":
                dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                                       capture_output=True, timeout=10, check=True).stdout
                if dirty:
                    raise ValueError("Confirme codigo local antes de preparar artefactos reales")
            encoded = prepare_artifact(root, args.destination, descriptor, secret=secret)
            write_private_document(root, args.destination, encoded)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, zipfile.BadZipFile, subprocess.SubprocessError):
        print("Preparacion rechazada: revise contrato, entorno, procedencia, tipos, permisos y destino nuevo. Sin cargar ni entrenar modelos.", file=sys.stderr)
        return 2
    print("Preparacion privada completada; sin entrenamiento, carga de modelos, cambios de base o activacion del CRM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
