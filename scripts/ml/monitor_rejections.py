"""ML-13 private synthetic reports and candidate requests; never trains or promotes."""

import argparse
import subprocess
from pathlib import Path

from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import parse_protocol
from app.ml.evaluation_signing import seal, unseal
from app.ml.export_files import (
    load_key,
    read_private_file,
    require_new_private_destination,
    write_private_document,
)
from app.ml.export_snapshot import parse_json
from app.ml.monitoring import (
    REQUEST_VERSION,
    VERSION,
    analyze,
    candidate_request,
    policy_template,
)
from app.ml.pipelines import TASKS

ROOT = Path(__file__).resolve().parents[2]
KINDS = {"report": ("ml-monitor-v1", "report_id", VERSION),
         "candidate": ("ml-candidate-request-v1", "request_id", REQUEST_VERSION)}


def verify_record(root, relative, *, kind, secret):
    domain, id_field, version = KINDS[kind]
    record = unseal(read_private_file(root, relative, max_bytes=256_000), secret=secret, domain=domain, id_field=id_field)
    if (record.get("version") != version or record.get("purpose") != "synthetic"
            or record.get("training_authorized") is not False or record.get("promotion_authorized") is not False):
        raise ValueError("Registro incompatible")
    return record


def prepare_report(root, *, input_relative, policy_relative, destination, secret):
    snapshot = parse_json(read_private_file(root, input_relative, max_bytes=16_000_000))
    policy = parse_json(read_private_file(root, policy_relative, max_bytes=16_000))
    report = analyze(snapshot, policy)
    encoded = seal(report, secret=secret, domain=KINDS["report"][0], id_field="report_id")
    if len(encoded) > 256_000:
        raise ValueError("Informe demasiado grande")
    write_private_document(root, destination, encoded)


def prepare_candidate(root, *, input_relative, policy_relative, report_relative, protocol_relative,
                      candidate_id, destination, secret):
    record = verify_record(root, report_relative, kind="report", secret=secret)
    report_id = record.pop("report_id")
    snapshot = parse_json(read_private_file(root, input_relative, max_bytes=16_000_000))
    policy = parse_json(read_private_file(root, policy_relative, max_bytes=16_000))
    if canonical_json(analyze(snapshot, policy)) != canonical_json(record):
        raise ValueError("El informe no corresponde a la entrada y politica verificadas")
    protocol = parse_protocol(read_private_file(root, protocol_relative, max_bytes=128_000))
    request = candidate_request(record, report_id=report_id, candidate_id=candidate_id, protocol=protocol)
    encoded = seal(request, secret=secret, domain=KINDS["candidate"][0], id_field="request_id")
    write_private_document(root, destination, encoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Monitoreo sintetico y solicitudes; sin entrenamiento o activacion")
    commands = parser.add_subparsers(dest="command", required=True)
    policy = commands.add_parser("init-policy")
    policy.add_argument("--destination", required=True)
    for name in ("monitor", "candidate", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--key-file", default="keys/export.key")
        if name == "verify":
            command.add_argument("--record", required=True)
            command.add_argument("--kind", choices=tuple(KINDS), required=True)
        else:
            command.add_argument("--synthetic", action="store_true", required=True)
            command.add_argument("--input", required=True)
            command.add_argument("--policy", required=True)
            command.add_argument("--destination", required=True)
        if name == "candidate":
            command.add_argument("--report", required=True)
            command.add_argument("--protocol", required=True)
            command.add_argument("--candidate", choices=tuple(TASKS), required=True)
    args = parser.parse_args(argv)
    try:
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, timeout=10, check=False)
        if ignored.returncode:
            raise ValueError("Destino privado no excluido de Git")
        root = ROOT / ".local/ml-private"
        if args.command != "verify":
            require_new_private_destination(root, args.destination)
        if args.command == "init-policy":
            write_private_document(root, args.destination, canonical_json(policy_template()))
        else:
            secret = load_key(root, args.key_file)
            if args.command == "verify":
                verify_record(root, args.record, kind=args.kind, secret=secret)
            elif args.command == "monitor":
                prepare_report(root, input_relative=args.input, policy_relative=args.policy, destination=args.destination, secret=secret)
            else:
                prepare_candidate(root, input_relative=args.input, policy_relative=args.policy, report_relative=args.report,
                    protocol_relative=args.protocol, candidate_id=args.candidate, destination=args.destination, secret=secret)
        print("Preparacion sintetica verificada. Sin entrenamiento, aprobacion operativa o promocion.")
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("No se completo ML-13: revise el contrato, los permisos privados y las referencias. No se habilito ninguna operacion.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
