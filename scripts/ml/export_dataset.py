"""Offline ML-05 CLI. All inputs/keys/outputs stay under ignored .local/ml-private."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from app.ml.dataset_export import build_bundle
from app.ml.export_files import (
    generate_key,
    load_key,
    read_private_file,
    verify_bundle,
    write_bundle,
)
from app.ml.export_snapshot import MAX_BYTES, prepare_snapshot

ROOT = Path(__file__).resolve().parents[2]


def source_fingerprint(root: Path) -> str:
    paths = [*sorted((root / "app/ml").glob("*.py")), root / "scripts/ml/export_dataset.py",
             *(root / "app/services" / name for name in (
                 "vp_rejection_codes.py", "toku_rejection_codes.py", "payku_rejection_codes.py"))]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("ascii") + b"\x00")
        digest.update(path.read_bytes() + b"\x00")
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exportacion ML restringida, sin entrenamiento ni conexiones")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-key", help="Crear una clave privada; nunca imprime ni sobrescribe su valor")
    init.add_argument("--key-file", default="keys/export.key")
    export = sub.add_parser("export", help="Validar y exportar un snapshot revisado ML-04")
    export.add_argument("--snapshot", required=True, help="Ruta relativa dentro de .local/ml-private")
    export.add_argument("--destination", required=True, help="Directorio nuevo relativo dentro de .local/ml-private")
    export.add_argument("--key-file", default="keys/export.key")
    export.add_argument("--scope", required=True, help="Alcance estable de seudonimos, sin datos personales")
    export.add_argument("--allow-reviewed-real", action="store_true", help="Habilitar un snapshot real ya revisado")
    verify = sub.add_parser("verify", help="Comprobar permisos, firma e integridad del paquete")
    verify.add_argument("--destination", required=True)
    verify.add_argument("--key-file", default="keys/export.key")
    args = parser.parse_args(argv)
    try:
        # Ignored does not mean private; both Git exclusion and OS permissions are checked.
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".local/ml-private/"], cwd=ROOT,
                                 capture_output=True, check=False, timeout=10)
        if ignored.returncode:
            raise ValueError("El almacenamiento local debe estar excluido de Git")
        private = ROOT / ".local" / "ml-private"
        private.parent.mkdir(exist_ok=True)
        if args.command == "init-key":
            generate_key(private, args.key_file)
        else:
            secret = load_key(private, args.key_file)
            if args.command == "verify":
                verify_bundle(private, args.destination, secret=secret)
            else:
                snapshot = prepare_snapshot(read_private_file(private, args.snapshot, max_bytes=MAX_BYTES),
                                            allow_reviewed_real=args.allow_reviewed_real)
                revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                          check=True, timeout=10).stdout.decode("ascii").strip()
                # Real exports require reproducible checked-in code, not an unrecorded working tree.
                dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                                       capture_output=True, check=True, timeout=10).stdout
                if snapshot.purpose == "reviewed-real" and dirty:
                    raise ValueError("Confirme el codigo local antes de exportar datos reales")
                bundle = build_bundle(snapshot, secret=secret, scope=args.scope, exporter_revision=revision,
                                      exporter_dependencies_sha256=hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
                                      exporter_source_sha256=source_fingerprint(ROOT), exporter_dirty=bool(dirty))
                write_bundle(private, args.destination, bundle)
                verify_bundle(private, args.destination, secret=secret)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Operacion rechazada. Revise contratos, permisos privados, clave, procedencia y destino nuevo; no registre datos sensibles.", file=sys.stderr)
        return 2
    print("Operacion local completada; no se entrenaron modelos ni se enviaron datos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
