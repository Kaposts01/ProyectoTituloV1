"""ML-14 private synthetic report from a bounded exported ledger. No DB/GUI hooks."""

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.ml.dataset_export import canonical_json
from app.ml.evaluation_protocol import instant
from app.ml.evaluation_signing import seal, unseal
from app.ml.export_files import (
    load_key,
    read_private_file,
    require_new_private_destination,
    write_private_document,
)
from app.ml.export_snapshot import exact, parse_json
from app.ml.prospective import VERSION, measure, template

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "ml-prospective-report-v1"


def prepare_report(root, relative, destination, *, as_of, secret):
    bundle = parse_json(read_private_file(root, relative, max_bytes=8_000_000))
    exact(bundle, {"protocol", "events"})
    report = measure(bundle["protocol"], bundle["events"], as_of=as_of)
    data = seal(report, secret=secret, domain=DOMAIN, id_field="report_id")
    write_private_document(root, destination, data)


def verify_report(root, relative, *, secret):
    report = unseal(read_private_file(root, relative, max_bytes=256_000), secret=secret, domain=DOMAIN, id_field="report_id")
    if (report.get("version") != VERSION or report.get("purpose") != "synthetic"
            or report.get("causal_effect") is not None or report.get("causal_comparison") is not None
            or any(report.get(key) is not False for key in ("execution_authorized", "training_authorized", "promotion_authorized"))):
        raise ValueError("Informe incompatible")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Medicion prospectiva sintetica; sin gestiones o efecto causal")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("template")
    init.add_argument("--destination", required=True)
    for name in ("report", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--key-file", default="keys/export.key")
        if name == "report":
            command.add_argument("--synthetic", action="store_true", required=True)
            command.add_argument("--input", required=True)
            command.add_argument("--destination", required=True)
            command.add_argument("--as-of")
        else:
            command.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, timeout=10, check=False)
        if ignored.returncode:
            raise ValueError("Destino no excluido")
        root = ROOT / ".local/ml-private"
        if args.command != "verify":
            require_new_private_destination(root, args.destination)
        if args.command == "template":
            write_private_document(root, args.destination, canonical_json(template()))
        else:
            key = load_key(root, args.key_file)
            if args.command == "verify":
                verify_report(root, args.report, secret=key)
            else:
                now = datetime.now(UTC)
                cutoff = instant(args.as_of) if args.as_of else now
                if cutoff > now:
                    raise ValueError("No informar un corte futuro")
                prepare_report(root, args.input, args.destination, as_of=cutoff.isoformat(), secret=key)
        print("Preparacion prospectiva sintetica verificada. Sin aprobacion, ejecucion o efecto causal estimado.")
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("No se completo ML-14: revise protocolo, historial, corte y permisos privados. No se ejecuto una gestion.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
