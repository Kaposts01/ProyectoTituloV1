"""BCK-01a: guardas de los scripts de respaldo (scripts/maintenance/*.ps1). Sin docker ni bases de datos.

Corre los scripts con PowerShell (`pwsh`, o `powershell` en Windows) y comprueba que:
- restore_drill.ps1 se niega con cualquier destino distinto de `crm_restore_test` ANTES de tocar docker
  (se le pasa un -ProjectDir inexistente: si llegara a docker fallaria con otro codigo).
- backup_db.ps1 rechaza nombres de base raros antes de llamar a docker.
- encrypt/decrypt: ida y vuelta byte a byte, clave equivocada sin archivo de salida, y las guardas de la clave
  (fuera del repo, nunca junto al respaldo, minimo 20 caracteres).
- backup_alert.py arma un aviso sin datos crudos.
Si no hay PowerShell en la maquina, las pruebas de .ps1 se saltan.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts" / "maintenance"
SHELL = shutil.which("pwsh") or shutil.which("powershell")
KEY = "frase-sintetica-solo-para-tests-0123"

needs_ps = pytest.mark.skipif(SHELL is None, reason="PowerShell no disponible")


def _run(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k != "CRM_BACKUP_KEY"}
    full_env.update(env or {})
    return subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / script), *args],
        capture_output=True, text=True, timeout=120, env=full_env, check=False)


@needs_ps
@pytest.mark.parametrize("target", ["crm", "crm_sandbox", "crm_test", "CRM_RESTORE_TEST", "crm_restore_test2", " crm_restore_test"])
def test_drill_rejects_any_target_but_crm_restore_test(tmp_path: Path, target: str) -> None:
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    res = _run("restore_drill.ps1", "-DumpFile", str(dump), "-SourceDatabase", "crm_sandbox",
               "-TargetDatabase", target, "-ProjectDir", str(tmp_path / "no_existe"))
    assert res.returncode == 2, res.stdout + res.stderr
    assert "RECHAZADO" in res.stdout
    assert not (tmp_path / "logs").exists()  # no llego ni a escribir el log


@needs_ps
def test_drill_rejects_source_equal_to_target(tmp_path: Path) -> None:
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    res = _run("restore_drill.ps1", "-DumpFile", str(dump), "-SourceDatabase", "crm_restore_test",
               "-ProjectDir", str(tmp_path / "no_existe"))
    assert res.returncode == 2
    assert "RECHAZADO" in res.stdout


@needs_ps
def test_backup_rejects_weird_database_name(tmp_path: Path) -> None:
    res = _run("backup_db.ps1", "-Database", "crm; drop", "-Destination", str(tmp_path / "bk"),
               "-ProjectDir", str(tmp_path / "no_existe"))
    assert res.returncode == 1
    log = (tmp_path / "bk" / "logs" / "backup_db.log").read_text(encoding="utf-8-sig")
    assert "Nombre de base invalido" in log
    assert not list((tmp_path / "bk").glob("*.dump*"))


@needs_ps
def test_encrypt_decrypt_roundtrip_and_wrong_key(tmp_path: Path) -> None:
    data_dir, cloud, out = tmp_path / "bk", tmp_path / "cloud", tmp_path / "out"
    for d in (data_dir, cloud, out):
        d.mkdir()
    original = data_dir / "crm_sandbox_20260101_0500.dump"
    original.write_bytes(os.urandom(3 * 1024 * 1024 + 123))  # mas de un bloque de 1 MB y no multiplo de 16
    enc = cloud / "a.dump.enc"

    res = _run("encrypt_backup.ps1", "-InputFile", str(original), "-OutputFile", str(enc), env={"CRM_BACKUP_KEY": KEY})
    assert res.returncode == 0, res.stdout + res.stderr
    assert enc.read_bytes()[:8] == b"SYNKBK01"
    assert KEY not in res.stdout

    restored = out / "a.dump"
    res = _run("decrypt_backup.ps1", "-InputFile", str(enc), "-OutputFile", str(restored), env={"CRM_BACKUP_KEY": KEY})
    assert res.returncode == 0, res.stdout + res.stderr
    assert restored.read_bytes() == original.read_bytes()

    bad = out / "bad.dump"
    res = _run("decrypt_backup.ps1", "-InputFile", str(enc), "-OutputFile", str(bad),
               env={"CRM_BACKUP_KEY": "otra-frase-equivocada-0123456789"})
    assert res.returncode == 1
    assert "HMAC" in res.stdout
    assert not bad.exists()
    assert not list(out.glob("*.partial"))


@needs_ps
def test_encrypt_rejects_short_or_missing_key(tmp_path: Path) -> None:
    src = tmp_path / "x.dump"
    src.write_bytes(b"datos")
    res = _run("encrypt_backup.ps1", "-InputFile", str(src), env={"CRM_BACKUP_KEY": "corta"})
    assert res.returncode == 1 and "20 caracteres" in res.stdout
    res = _run("encrypt_backup.ps1", "-InputFile", str(src))
    assert res.returncode == 1 and "CRM_BACKUP_KEY" in res.stdout
    assert not (tmp_path / "x.dump.enc").exists()


@needs_ps
def test_encrypt_rejects_key_file_next_to_backup(tmp_path: Path) -> None:
    src = tmp_path / "x.dump"
    src.write_bytes(b"datos")
    key = tmp_path / "clave.key"
    key.write_text(KEY, encoding="utf-8")
    res = _run("encrypt_backup.ps1", "-InputFile", str(src), "-KeyFile", str(key))
    assert res.returncode == 1
    assert "misma carpeta" in res.stdout
    assert not (tmp_path / "x.dump.enc").exists()


@needs_ps
def test_encrypt_rejects_key_file_inside_repo(tmp_path: Path) -> None:
    src = tmp_path / "x.dump"
    src.write_bytes(b"datos")
    res = _run("encrypt_backup.ps1", "-InputFile", str(src), "-KeyFile", str(REPO / "README.md"))
    assert res.returncode == 1
    assert "dentro del repo" in res.stdout


def test_backup_alert_condition_has_no_raw_data() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("backup_alert", SCRIPTS / "backup_alert.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cond = module.build_condition("crm", "pg_dump")
    assert cond.key == "backup_failed:crm"
    assert "crm" in cond.title and "pg_dump" in cond.text

    weird = module.build_condition("crm", "error: juan.perez@correo.cl 12.345.678-9 <script>")
    assert "@" not in weird.text and "(desconocida)" in weird.text
