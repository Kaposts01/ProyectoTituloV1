"""Private local storage and verification; no recursive deletion or overwriting exports."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path

from app.ml.dataset_export import (
    EXPORT_VERSION,
    MAX_PACKAGE_BYTES,
    PAYLOAD_FILES,
    ExportBundle,
    canonical_json,
    signature,
    validate_secret,
)
from app.ml.export_snapshot import parse_json

_ACL = r"""
$ErrorActionPreference = 'Stop'
$path = $env:SYNKMETRIX_PRIVATE_PATH
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($env:SYNKMETRIX_PRIVATE_CREATE -eq '1') {
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($identity in @($sid, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    [System.IO.Directory]::SetAccessControl($path, $acl)
}
$isDirectory = [System.IO.Directory]::Exists($path)
$acl = if ($isDirectory) { [System.IO.Directory]::GetAccessControl($path) } else { [System.IO.File]::GetAccessControl($path) }
if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { exit 2 }
if ($isDirectory -and !$acl.AreAccessRulesProtected) { exit 3 }
$own = $false
foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq 'Allow') {
        if ($rule.IdentityReference.Value -notin @($sid.Value, 'S-1-5-18')) { exit 4 }
        if ($rule.IdentityReference.Value -eq $sid.Value) { $own = $true }
    }
}
if (!$own) { exit 5 }
"""


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("No se admiten enlaces o puntos de redireccion")


def _permissions(path: Path, *, create: bool = False) -> None:
    if os.name == "nt":
        environment = os.environ.copy()
        environment.update(SYNKMETRIX_PRIVATE_PATH=str(path), SYNKMETRIX_PRIVATE_CREATE="1" if create else "0")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _ACL],
                                env=environment, capture_output=True, timeout=20, check=False)
        if result.returncode:
            raise ValueError("No se pudo comprobar almacenamiento privado; no se exportaron datos")
    else:
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Destino debe pertenecer al usuario y excluir acceso de otros")


def private_root(root: Path) -> Path:
    root = root.absolute()
    _no_links(root)
    if not root.parent.is_dir():
        raise ValueError("El padre del directorio privado debe existir")
    if not root.exists():
        root.mkdir(mode=0o700)
        _permissions(root, create=True)
    _permissions(root)
    return root


def _child(root: Path, relative: str) -> Path:
    # Relative portable names only. Never let a manifest or CLI argument select arbitrary paths.
    parts = relative.split("/")
    if (not parts or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", p)
                         or p.split(".")[0].lower() in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
                         or p.endswith(".") for p in parts)):
        raise ValueError("Ruta relativa privada invalida")
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Ruta fuera del directorio privado")
    _no_links(target)
    return target


def _parents(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts[:-1]:
        current = current / part
        if not current.exists():
            current.mkdir(mode=0o700)
            _permissions(current, create=True)
        _permissions(current)


def _write(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink()
        raise


def generate_key(root: Path, relative: str) -> None:
    root = private_root(root)
    target = _child(root, relative)
    _parents(root, target)
    _write(target, secrets.token_bytes(32))
    _permissions(target)


def load_key(root: Path, relative: str) -> bytes:
    root = private_root(root)
    target = _child(root, relative)
    _permissions(target)
    if not target.is_file() or target.stat().st_size != 32:
        raise ValueError("Archivo de clave invalido")
    secret = target.read_bytes()
    validate_secret(secret)
    return secret


def write_bundle(root: Path, relative: str, bundle: ExportBundle) -> None:
    """Exclusive destination. Manifest is the completion marker, written last.

    Failures leave no valid manifest; crashes may leave a private incomplete directory.
    Never recursively delete a supplied path. Existing packages are never modified.
    """
    if tuple(name for name, _ in bundle.files) != PAYLOAD_FILES:
        raise ValueError("Archivos de paquete invalidos")
    root = private_root(root)
    destination = _child(root, relative)
    _parents(root, destination)
    destination.mkdir(mode=0o700)  # Fails if already present, even empty.
    _permissions(destination, create=True)
    written = []
    try:
        for name, data in (*bundle.files, ("manifest.json", bundle.manifest)):
            path = destination / name
            _write(path, data)
            written.append(path)
            _permissions(path)
    except (OSError, ValueError, subprocess.SubprocessError):
        for path in reversed(written):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        if not any(destination.iterdir()):
            destination.rmdir()
        raise


def verify_bundle(root: Path, relative: str, *, secret: bytes, include_manifest: bool = False) -> dict:
    """Authenticate manifest and exact payloads before any future training consumes them.

    This does not certify source data quality, anonymity or permission to train.
    """
    validate_secret(secret)
    root = private_root(root)
    destination = _child(root, relative)
    _permissions(destination)
    if {path.name for path in destination.iterdir()} != {*PAYLOAD_FILES, "manifest.json"}:
        raise ValueError("Paquete incompleto o con archivos no admitidos")
    for path in destination.iterdir():
        _no_links(path)
        _permissions(path)
        if not path.is_file():
            raise ValueError("Paquete invalido")
    manifest_path = destination / "manifest.json"
    if manifest_path.stat().st_size > 128_000:
        raise ValueError("Manifiesto demasiado grande")
    manifest = parse_json(manifest_path.read_bytes())
    if type(manifest) is not dict:
        raise ValueError("Manifiesto invalido")
    mac = manifest.pop("signature", None)
    if (not isinstance(mac, str) or not re.fullmatch(r"[a-f0-9]{64}", mac)
            or not hmac.compare_digest(mac, signature(canonical_json(manifest), secret, domain="manifest-v1"))
            or manifest.get("export_version") != EXPORT_VERSION):
        raise ValueError("Firma o version del manifiesto invalida")
    package_id = manifest.pop("package_id", None)
    if package_id != hashlib.sha256(canonical_json(manifest)).hexdigest():
        raise ValueError("Fingerprint del paquete invalido")
    if set(manifest.get("files", {})) != set(PAYLOAD_FILES):
        raise ValueError("Inventario de archivos invalido")
    total = 0
    for name in PAYLOAD_FILES:
        path = destination / name
        expected = manifest["files"][name]
        total += path.stat().st_size
        if total > MAX_PACKAGE_BYTES or path.stat().st_size != expected["bytes"]:
            raise ValueError("Tamano de archivo invalido")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected["sha256"]:
            raise ValueError("Contenido del paquete alterado")
    result = {"verified": True, "package_id": package_id}
    if include_manifest:
        result["manifest"] = manifest
    return result


def read_private_file(root: Path, relative: str, *, max_bytes: int) -> bytes:
    root = private_root(root)
    target = _child(root, relative)
    _permissions(target)
    if not target.is_file() or target.stat().st_size > max_bytes:
        raise ValueError("Archivo privado invalido o demasiado grande")
    with target.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Archivo demasiado grande")
    return data


def write_private_document(root: Path, relative: str, data: bytes) -> None:
    """Exclusive private document, without changing existing files or broadening access."""
    root = private_root(root)
    target = _child(root, relative)
    _parents(root, target)
    _write(target, data)
    _permissions(target)


def require_new_private_destination(root: Path, relative: str) -> None:
    """Fail on obvious destination errors before a one-shot holdout opening is consumed."""
    root = private_root(root)
    target = _child(root, relative)
    if target.exists():
        raise FileExistsError("El destino privado ya existe")
    _parents(root, target)
