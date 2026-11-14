"""BCK-01a: guardas de los scripts de respaldo (scripts/maintenance/*.ps1). Sin docker ni bases de datos.

Corre los scripts con PowerShell (`pwsh`, o `powershell` en Windows) y comprueba que:
- restore_drill.ps1 se niega con cualquier destino distinto de `crm_restore_test` ANTES de tocar docker
  (se le pasa un -ProjectDir inexistente: si llegara a docker fallaria con otro codigo).
- backup_db.ps1 rechaza nombres de base raros antes de llamar a docker.
- encrypt/decrypt: ida y vuelta byte a byte, clave equivocada sin archivo de salida, y las guardas de la clave
  (fuera del repo, nunca junto al respaldo, minimo 20 caracteres).
- backup_alert.py arma un aviso sin datos crudos.
- copia externa atomica (.partial y renombre; si se corta a la mitad no queda nada con el nombre definitivo),
  retencion local aunque falle la copia externa (sin tocar crm_predeploy_*; limpia .partial de mas de 1 dia),
  rutas raiz (E:\\) bien citadas en la tarea programada y rutas relativas resueltas contra Set-Location.
Si no hay PowerShell en la maquina, las pruebas de .ps1 se saltan.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts" / "maintenance"
SHELL = shutil.which("pwsh") or shutil.which("powershell")
KEY = "frase-sintetica-solo-para-tests-0123"

needs_ps = pytest.mark.skipif(SHELL is None, reason="PowerShell no disponible")
needs_windows = pytest.mark.skipif(sys.platform != "win32", reason="linea de comandos de Windows")


def _ps(command: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Corre un bloque de PowerShell con las funciones de backup_common.ps1 cargadas (sin docker)."""
    prelude = f"$ErrorActionPreference = 'Stop'; . '{SCRIPTS / 'backup_common.ps1'}'; "
    full_env = {k: v for k, v in os.environ.items() if k != "CRM_BACKUP_KEY"}
    return subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prelude + command],
        capture_output=True, text=True, timeout=120, env=full_env, cwd=cwd, check=False)


def _age(path: Path, days: float) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


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


@needs_ps
def test_external_copy_is_atomic_and_cleans_partial_on_failure(tmp_path: Path) -> None:
    src_dir, ext = tmp_path / "bk", tmp_path / "ext"
    src_dir.mkdir()
    ext.mkdir()
    src = src_dir / "crm_20261108_0500.dump"
    src.write_bytes(os.urandom(4096))

    # Copia normal: queda el nombre definitivo, identico, y ningun .partial.
    res = _ps(f"Copy-BackupToExternal -Source '{src}' -Folder '{ext}'")
    assert res.returncode == 0, res.stdout + res.stderr
    assert (ext / src.name).read_bytes() == src.read_bytes()
    assert not list(ext.glob("*.partial"))

    # Copia que se corta a la mitad (Copy-Item simulado: escribe 100 bytes y falla): no queda un archivo definitivo
    # truncado ni el .partial, y el error llega al llamador.
    (ext / src.name).unlink()
    fake_copy = ("function Copy-Item { param([string]$LiteralPath, [string]$Destination) "
                 "[IO.File]::WriteAllBytes($Destination, [byte[]]::new(100)); throw 'disco desconectado a la mitad' }; ")
    res = _ps(fake_copy + f"Copy-BackupToExternal -Source '{src}' -Folder '{ext}'")
    assert res.returncode != 0
    assert "disco desconectado a la mitad" in res.stdout + res.stderr
    assert list(ext.iterdir()) == []


@needs_ps
def test_local_retention_runs_even_if_external_copy_fails(tmp_path: Path) -> None:
    bk = tmp_path / "bk"
    bk.mkdir()
    new = bk / "crm_20261108_0500.dump"
    new.write_bytes(b"x" * 200)
    old = bk / "crm_20261001_0500.dump"
    predeploy = bk / "crm_predeploy_D127_20261001_0039.dump"
    old_partial = bk / "crm_20261020_0500.dump.partial"
    fresh_partial = bk / "crm_20261108_0501.dump.partial"
    other_db = bk / "crm_sandbox_20261001_0500.dump"
    for f, days in ((old, 30), (predeploy, 30), (old_partial, 2), (fresh_partial, 0), (other_db, 30)):
        f.write_bytes(b"x")
        _age(f, days)
    log = bk / "logs" / "backup_db.log"

    res = _ps(f"$r = Invoke-BackupCopyAndRetention -DumpFile '{new}' -Destination '{bk}' -Database crm "
              f"-RetentionDays 14 -LogFile '{log}' -ExternalCopyPath '{tmp_path / 'disco_desconectado'}'; "
              "if ($r) { Write-Output ('EXTERNAL_ERROR=' + $r) }")
    assert res.returncode == 0, res.stdout + res.stderr
    # Devuelve el error de la copia externa (backup_db.ps1 lo relanza: sale con 1 y avisa) pero la retencion corrio.
    assert "EXTERNAL_ERROR=El destino externo no esta disponible" in res.stdout
    assert new.exists() and predeploy.exists() and fresh_partial.exists() and other_db.exists()
    assert not old.exists() and not old_partial.exists()
    text = log.read_text(encoding="utf-8-sig")
    assert "Copia externa fallida" in text and "Retencion: 2 archivo(s)" in text


def test_backup_db_reports_external_failure_after_retention() -> None:
    # backup_db.ps1 necesita docker para llegar a este punto; se verifica el orden en el codigo: la retencion corre
    # dentro de Invoke-BackupCopyAndRetention y el fallo de la copia externa se relanza despues, con su etapa.
    text = (SCRIPTS / "backup_db.ps1").read_text(encoding="utf-8")
    call = text.index("Invoke-BackupCopyAndRetention -DumpFile")
    stage = text.index("$failureStage = 'copia externa'")
    assert call < stage < text.index("throw $externalError") < text.index("exit 0")
    assert "Remove-OldBackups" not in text and "Copy-Item" not in text


@needs_ps
@pytest.mark.parametrize(("path", "expected"), [
    ("E:\\", '"E:\\."'),
    ("E:\\CRM_backups\\", '"E:\\CRM_backups"'),
    ("C:\\Users\\Usuario\\Downloads\\CRM backups", '"C:\\Users\\Usuario\\Downloads\\CRM backups"'),
    ("\\\\nas\\respaldos\\", '"\\\\nas\\respaldos"'),
])
def test_task_path_argument_never_ends_with_backslash(path: str, expected: str) -> None:
    res = _ps(f"ConvertTo-TaskPathArgument '{path}'")
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip() == expected


@needs_ps
@needs_windows
def test_task_arguments_with_root_path_parse_correctly(tmp_path: Path) -> None:
    # La linea de argumentos se pasa tal cual a CreateProcess (como hace el Programador de tareas) y el script recibe
    # cada parametro completo aunque el destino externo sea la raiz de una unidad.
    echo = tmp_path / "echo.ps1"
    echo.write_text(
        "param([string]$Destination, [string]$ExternalCopyPath, [int]$RetentionDays, [switch]$AlertOnFailure)\n"
        "@{d=$Destination; e=$ExternalCopyPath; r=$RetentionDays; a=[bool]$AlertOnFailure} | ConvertTo-Json -Compress\n",
        encoding="utf-8")
    res = _ps(f"@('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "
              f"(ConvertTo-TaskPathArgument '{echo}'), "
              "'-Destination', (ConvertTo-TaskPathArgument 'C:\\CRM backups\\'), '-RetentionDays', 14, "
              "'-ExternalCopyPath', (ConvertTo-TaskPathArgument 'E:\\'), '-AlertOnFailure') -join ' '")
    assert res.returncode == 0, res.stdout + res.stderr
    out = subprocess.run(f'"{SHELL}" {res.stdout.strip()}', capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout) == {"d": "C:\\CRM backups", "e": "E:\\.", "r": 14, "a": True}


@needs_ps
def test_encrypt_resolves_relative_output_against_powershell_location(tmp_path: Path) -> None:
    work, elsewhere = tmp_path / "work", tmp_path / "proceso"
    work.mkdir()
    elsewhere.mkdir()
    (work / "x.dump").write_bytes(b"datos de prueba sinteticos")
    cmd = (f"Set-Location -LiteralPath '{work}'; "
           f"& '{SCRIPTS / 'encrypt_backup.ps1'}' -InputFile x.dump -OutputFile salida.enc -SkipVerify; exit $LASTEXITCODE")
    env = {k: v for k, v in os.environ.items() if k != "CRM_BACKUP_KEY"}
    env["CRM_BACKUP_KEY"] = KEY
    res = subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True, text=True, timeout=120, cwd=elsewhere, env=env, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert (work / "salida.enc").exists()
    assert not list(elsewhere.iterdir())
