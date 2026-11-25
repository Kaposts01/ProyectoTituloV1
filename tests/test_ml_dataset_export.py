"""Synthetic offline export tests. No DB, provider APIs, fitting or real donor data."""

import copy
import hashlib
import json
import subprocess
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ml import export_files, export_snapshot
from app.ml.annotation_contract import prepare_context
from app.ml.dataset_export import build_bundle, canonical_json
from app.ml.export_snapshot import prepare_snapshot
from scripts.ml import export_dataset

SECRET = b"synthetic-test-only-key-32-bytes"
REVISION = "a" * 40
DEPENDENCIES = "b" * 64


def snapshot(task="p2"):
    document = {
        "schema_version": "rejection-snapshot-v1", "task": task, "purpose": "synthetic",
        "as_of": "2026-02-05T00:00:00Z", "privacy_reviewed": True, "policy_reviewed": True,
        "provenance": {"adapter_version": "synthetic-v1", "query_sha256": "c" * 64,
                       "source_snapshot_sha256": "d" * 64, "code_revision": REVISION,
                       "dependencies_sha256": DEPENDENCIES, "study_mode": "retrospective-limited"},
    }
    if task == "p1":
        context = asdict(prepare_context(source="toku", resource_type="payment", processor="psp",
                                        reason="Sin fondos", privacy_reviewed=True))
        document.update(
            observations=[{"observation_id": str(UUID(int=10)), "context": context,
                           "occurred_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T01:00:00Z"}],
            reviews=[{"context": context, "revision": n, "decision": decision, "category": "FUNDS",
                      "reviewed_at": f"2026-01-0{n + 1}T00:00:00Z", "actor_id": str(UUID(int=n))}
                     for n, decision in [(1, "draft"), (2, "approved")]],
            review_history_complete=True,
        )
    else:
        event = {"event_id": str(UUID(int=10)), "source": "virtualpos1", "obligation_id": str(UUID(int=100)),
                 "kind": "rejection", "occurred_at": "2026-01-01T00:00:00Z", "available_at": "2026-01-01T01:00:00Z",
                 "amount": "1000.00", "currency": "CLP", "link_verified": True, "subscription_id": str(UUID(int=200)),
                 "due_at": None, "due_available_at": None}
        payment = event | {"event_id": str(UUID(int=11)), "kind": "confirmed_full_payment",
                           "occurred_at": "2026-01-20T00:00:00Z", "available_at": "2026-01-21T00:00:00Z"}
        proof = {"evidence_id": str(UUID(int=300)), "source": "virtualpos1", "obligation_id": str(UUID(int=100)),
                 "observed_from": "2026-01-01T00:00:00Z", "observed_through": "2026-01-31T00:00:00Z",
                 "available_at": "2026-02-01T00:00:00Z", "complete": True, "reconciled": True, "history_complete": True}
        document.update(events=[event, payment], coverages=[proof])
    return document


def bundle(document=None, **changes):
    prepared = prepare_snapshot(canonical_json(document or snapshot()))
    values = dict(secret=SECRET, scope="synthetic-study", exporter_revision=REVISION,
                  exporter_dependencies_sha256=DEPENDENCIES, exporter_source_sha256="e" * 64)
    return build_bundle(prepared, **(values | changes))


@pytest.fixture
def io_root(tmp_path, monkeypatch):
    # Filesystem lifecycle/contents tests isolate permission work; native ACL has its own tests below.
    monkeypatch.setattr(export_files, "_permissions", lambda *args, **kwargs: None)
    return tmp_path / "private"


@pytest.mark.parametrize("task", ["p1", "p2"])
def test_reproducible_packages_separate_features_targets_and_metadata(task):
    document = snapshot(task)
    first = bundle(document)
    assert first == bundle(copy.deepcopy(document))
    files = dict(first.files)
    features = json.loads(files["features.jsonl"])
    target = json.loads(files["targets.jsonl"])
    metadata = json.loads(files["metadata.jsonl"])
    assert features["row_key"] == target["row_key"] == metadata["row_key"]
    assert set(features) == {"row_key", "features"} and set(target) == {"row_key", "target"}
    assert not {"subscription_id", "obligation_id", "target", "label_available_at", "actor_id"} & features["features"].keys()
    serialized = b"".join(files.values()) + first.manifest
    for number in (1, 2, 10, 100, 200, 300):
        assert str(UUID(int=number)).encode() not in serialized
    assert SECRET not in serialized
    manifest = json.loads(first.manifest)
    assert manifest["as_of"] == "2026-02-05T00:00:00.000000Z" and manifest["rows"] == 1
    assert manifest["source_counts"][0]["included"] == 1
    assert manifest["input_snapshot_sha256"] == hashlib.sha256(canonical_json(document)).hexdigest()
    assert manifest["access"] == "restricted-not-anonymous"
    if task == "p2":
        assert features["features"]["amount"] == "1000" and features["features"]["days_from_due"] is None
        assert metadata["subscription_group"] != metadata["obligation_group"]
        assert manifest["coverage_proofs"][0]["reconciled"] == 1


def test_key_and_scope_rotation_change_pseudonyms_not_features():
    base = json.loads(dict(bundle().files)["features.jsonl"])
    for changes in ({"secret": b"x" * 32}, {"scope": "another-study"}):
        altered = json.loads(dict(bundle(**changes).files)["features.jsonl"])
        assert altered["row_key"] != base["row_key"] and altered["features"] == base["features"]
    with pytest.raises(ValueError):
        bundle(secret=b"short")


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(privacy_reviewed=False), lambda d: d.update(policy_reviewed=False),
    lambda d: d.update(password="synthetic-sensitive"), lambda d: d["events"][0].update(rut="synthetic-sensitive"),
    lambda d: d["events"][0].update(amount=1000.0), lambda d: d["events"][0].update(occurred_at="2026-01"),
    lambda d: d["provenance"].update(query_sha256="postgresql://synthetic-sensitive"),
    lambda d: d["provenance"].update(sql="synthetic-sensitive"),
    lambda d: d["events"][0].update(link_verified="true"),
])
def test_snapshot_boundary_rejects_pii_extra_fields_and_unverified_claims(mutation):
    document = snapshot()
    mutation(document)
    with pytest.raises(ValueError) as error:
        prepare_snapshot(canonical_json(document))
    assert "synthetic-sensitive" not in str(error.value)


def test_json_duplicates_missing_fields_and_real_opt_in_are_enforced():
    for value in (b'{"task":"p1","task":"p2"}', b'[]', b'{"amount":NaN}', b'{'):
        with pytest.raises(ValueError):
            prepare_snapshot(value)
    document = snapshot("p1")
    del document["observations"][0]["context"]["normalization_version"]
    with pytest.raises(ValueError):
        prepare_snapshot(canonical_json(document))
    document = snapshot() | {"purpose": "reviewed-real"}
    with pytest.raises(ValueError):
        prepare_snapshot(canonical_json(document))
    assert prepare_snapshot(canonical_json(document), allow_reviewed_real=True).purpose == "reviewed-real"
    document = snapshot("p1")
    document["observations"][0]["context"]["normalized_text"] = "prueba@example.invalid"
    with pytest.raises(ValueError):
        prepare_snapshot(canonical_json(document))


def test_size_limits_and_malformed_manifests_fail_closed(io_root, monkeypatch):
    document = canonical_json(snapshot())
    monkeypatch.setattr(export_snapshot, "MAX_BYTES", len(document) - 1)
    with pytest.raises(ValueError):
        prepare_snapshot(document)
    monkeypatch.setattr(export_snapshot, "MAX_BYTES", len(document) + 1)
    monkeypatch.setattr(export_snapshot, "MAX_RECORDS", 1)
    with pytest.raises(ValueError):
        prepare_snapshot(document)
    monkeypatch.setattr(export_snapshot, "MAX_RECORDS", 100_000)
    original = bundle()
    for index, malformed in enumerate(([], {"signature": "\u2603"})):
        export_files.write_bundle(io_root, f"bad{index}", original)
        (io_root / f"bad{index}/manifest.json").write_bytes(canonical_json(malformed))
        with pytest.raises(ValueError):
            export_files.verify_bundle(io_root, f"bad{index}", secret=SECRET)


def test_excluded_and_empty_inputs_do_not_produce_fake_negatives():
    document = snapshot()
    document["coverages"][0]["complete"] = False
    result = bundle(document)
    assert all(content == b"" for _, content in result.files)
    manifest = json.loads(result.manifest)
    assert manifest["rows"] == 0 and sum(manifest["exclusions"].values()) == 1
    document.update(events=[], coverages=[])
    assert json.loads(bundle(document).manifest)["rows"] == 0


def test_write_verify_tampering_wrong_key_and_never_overwrite(io_root):
    original = bundle()
    export_files.write_bundle(io_root, "exports/run", original)
    assert export_files.verify_bundle(io_root, "exports/run", secret=SECRET)["verified"]
    with pytest.raises(FileExistsError):
        export_files.write_bundle(io_root, "exports/run", original)
    with pytest.raises(ValueError, match="Firma"):
        export_files.verify_bundle(io_root, "exports/run", secret=b"x" * 32)
    target = io_root / "exports/run/features.jsonl"
    target.write_bytes(target.read_bytes().replace(b"1000", b"2000"))
    with pytest.raises(ValueError, match="alterado"):
        export_files.verify_bundle(io_root, "exports/run", secret=SECRET)


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "C:/escape", "exports/../../escape", "NUL", "file.", "exports\\run"])
def test_paths_cannot_escape_private_root(io_root, relative):
    with pytest.raises(ValueError):
        export_files.write_bundle(io_root, relative, bundle())


def test_partial_write_failure_has_no_complete_export_and_preserves_other_files(io_root, monkeypatch):
    original = export_files._write

    def failing(path, data):
        if path.name == "targets.jsonl":
            raise OSError("synthetic failure")
        original(path, data)

    monkeypatch.setattr(export_files, "_write", failing)
    with pytest.raises(OSError):
        export_files.write_bundle(io_root, "run", bundle())
    assert not (io_root / "run").exists()
    assert not (io_root / "manifest.json").exists()


def test_missing_extra_files_and_forged_manifest_are_rejected(io_root):
    original = bundle()
    for name in ("missing", "extra", "forged"):
        export_files.write_bundle(io_root, name, original)
    (io_root / "missing/metadata.jsonl").unlink()
    (io_root / "extra/unknown.json").write_text("{}")
    manifest = json.loads(original.manifest)
    manifest["rows"] = 999
    (io_root / "forged/manifest.json").write_bytes(canonical_json(manifest))
    for name in ("missing", "extra", "forged"):
        with pytest.raises(ValueError):
            export_files.verify_bundle(io_root, name, secret=SECRET)


def test_native_private_permissions_key_lifecycle_and_export(tmp_path):
    root = tmp_path / "native-private"
    export_files.generate_key(root, "keys/export.key")
    secret = export_files.load_key(root, "keys/export.key")
    assert len(secret) == 32
    with pytest.raises(FileExistsError):
        export_files.generate_key(root, "keys/export.key")
    export_files.write_bundle(root, "native-run", bundle(secret=secret))
    assert export_files.verify_bundle(root, "native-run", secret=secret)["verified"]
    # A merely ignored/default directory is not automatically accepted as private.
    unprotected = tmp_path / "unprotected"
    unprotected.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        export_files._permissions(unprotected)


def test_cli_export_and_verify_without_echoing_rows_or_key(io_root, monkeypatch, capsys):
    root = io_root.parent
    monkeypatch.setattr(export_dataset, "ROOT", root)
    monkeypatch.setattr(export_dataset, "source_fingerprint", lambda root: "e" * 64)
    (root / ".local").mkdir()
    private = root / ".local/ml-private"
    monkeypatch.setattr(export_dataset.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=REVISION.encode() if "rev-parse" in args[0] else b""))
    (root / "requirements.lock").write_bytes(b"synthetic-lock")
    assert export_dataset.main(["init-key"]) == 0
    (private / "snapshot.json").write_bytes(canonical_json(snapshot()))
    assert export_dataset.main(["export", "--snapshot", "snapshot.json", "--destination", "run", "--scope", "synthetic-study"]) == 0
    assert export_dataset.main(["verify", "--destination", "run"]) == 0
    assert export_dataset.main(["export", "--snapshot", "snapshot.json", "--destination", "run", "--scope", "synthetic-study"]) == 2
    (private / "snapshot.json").write_bytes(canonical_json(snapshot() | {"purpose": "reviewed-real"}))
    monkeypatch.setattr(export_dataset.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=REVISION.encode() if "rev-parse" in args[0] else (b" M synthetic.py" if "status" in args[0] else b"")))
    assert export_dataset.main(["export", "--snapshot", "snapshot.json", "--destination", "real-run", "--scope", "synthetic-study", "--allow-reviewed-real"]) == 2
    assert not (private / "real-run").exists()
    output = capsys.readouterr()
    assert "1000" not in output.out and "Sin fondos" not in output.out and "Traceback" not in output.err


def test_import_remains_offline_and_does_not_load_runtime():
    script = "import sys; from scripts.ml import export_dataset; assert not any(n in sys.modules for n in ('app.db.session','app.core.config','pandas','sklearn')); print('offline')"
    import sys

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True)
    assert result.stdout.strip() == b"offline"
