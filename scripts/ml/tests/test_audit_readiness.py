"""Pure safety/aggregation tests: no application lifespan and no database fixture."""

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from scripts.ml.audit_readiness import (
    connection_args,
    main,
    parse_cutoff,
    summarize_texts,
    validate_session,
)

QA = "crm_qa_synthetic"
URL = f"postgresql://synthetic:private-test-password@127.0.0.1:5433/{QA}"


@pytest.mark.parametrize("url,expected", [
    (URL.replace(QA, "crm"), QA), (URL, "crm"), (URL.replace("127.0.0.1", "example.invalid"), QA),
    (URL.replace("5433", "5432"), QA), (URL + "?options=-cdefault_transaction_read_only=off", QA),
])
def test_rejects_unsafe_targets_before_connecting(url, expected):
    with patch("scripts.ml.audit_readiness.psycopg.connect") as connect:
        with pytest.raises(ValueError):
            connection_args(url, expected)
        connect.assert_not_called()


def test_readonly_timeout_and_namespace_cannot_be_overridden():
    args = connection_args(URL, QA)
    assert "default_transaction_read_only=on" in args["options"]
    assert "statement_timeout=60000" in args["options"]
    assert "search_path=pg_catalog,public" in args["options"]


def test_invalid_url_does_not_disclose_input():
    with pytest.raises(ValueError) as captured:
        connection_args("private-test-password malformed-url", QA)
    assert "private-test-password" not in str(captured.value)


@pytest.mark.parametrize("change", [{"database": "crm"}, {"read_only": "off"}, {"isolation": "read committed"}])
def test_checks_actual_session_not_just_connection_configuration(change):
    with pytest.raises(ValueError):
        validate_session({"database": QA, "read_only": "on", "isolation": "repeatable read", **change}, QA)


def test_cutoff_is_aware_and_not_future():
    assert parse_cutoff("2026-01-02T00:00:00-03:00") == datetime(2026, 1, 2, 3, tzinfo=UTC)
    for value in ("2026-01-02", "2999-01-01T00:00:00Z"):
        with pytest.raises(ValueError):
            parse_cutoff(value)


def test_text_inspection_exports_only_aggregates_and_no_examples():
    rows = [
        {"source": "toku", "code": "TEPSP1001", "reason": "[51] REINTENTAR EL 01-01-2026 A LAS 07:33", "n": 5},
        {"source": "toku", "code": "TEPSP1001", "reason": "[51] REINTENTAR EL 02-01-2026 A LAS 08:33", "n": 3},
        {"source": "tch", "code": None, "reason": "synthetic-person@example.invalid 11.111.111-1", "n": 2},
    ]
    report = summarize_texts(rows)
    toku = next(row for row in report if row["source"] == "toku")
    assert toku["rows"] == 8 and toku["normalized_code_text_pairs"] == 1
    assert toku["catalogue_recognized_rows"] == 8
    serialized = json.dumps(report)
    for personal in ("example.invalid", "11.111.111-1", "TEPSP1001", "REINTENTAR"):
        assert personal not in serialized
    assert next(row for row in report if row["source"] == "tch")["suspected_pii_text_rows"] == 2


def test_failure_does_not_echo_database_exception_or_write_partial_report(tmp_path, monkeypatch, capsys):
    import psycopg

    target = tmp_path / "report.json"
    monkeypatch.setenv("ML_AUDIT_DATABASE_URL", URL)
    monkeypatch.setattr("sys.argv", ["audit", "--expected-database", QA, "--as-of", "2026-01-01T00:00:00Z", "--out", str(target)])
    with patch("scripts.ml.audit_readiness.run_audit", side_effect=psycopg.OperationalError("private-test-password raw-person@example.invalid")):
        assert main() == 1
    assert not target.exists()
    output = capsys.readouterr().out
    assert "private-test-password" not in output and "example.invalid" not in output
