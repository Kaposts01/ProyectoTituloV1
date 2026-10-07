"""Tests for pure helper functions in Core ETL services and Core model structure.

No database connection required: all tests exercise stateless logic.
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.core import CoreClientAttribute, CoreSubscription
from app.services.core_payku_etl import _parse_amount as payku_parse_amount
from app.services.core_payku_etl import _parse_date as payku_parse_date
from app.services.core_tch_etl import _parse_amount as tch_parse_amount
from app.services.core_tch_etl import _parse_date as tch_parse_date
from app.services.core_tch_etl import _resolve_currency
from app.services.core_toku_etl import _parse_amount as toku_parse_amount
from app.services.core_toku_etl import _parse_date as toku_parse_date
from app.services.core_vp_etl import _parse_amount as vp_parse_amount
from app.services.core_vp_etl import _parse_date as vp_parse_date


# ── _parse_date (shared across all four ETLs) ────────────────────────────────

@pytest.mark.parametrize("parse_date", [tch_parse_date, toku_parse_date, payku_parse_date, vp_parse_date])
class TestParseDate:
    def test_returns_none_for_none(self, parse_date):
        assert parse_date(None) is None

    def test_returns_none_for_empty_string(self, parse_date):
        assert parse_date("") is None

    def test_parses_iso_date_string(self, parse_date):
        result = parse_date("2024-03-15")
        assert result == datetime(2024, 3, 15, tzinfo=timezone.utc)

    def test_parses_iso_datetime_string_truncating_to_date(self, parse_date):
        result = parse_date("2024-03-15T14:30:00")
        assert result == datetime(2024, 3, 15, tzinfo=timezone.utc)

    def test_result_is_timezone_aware_utc(self, parse_date):
        result = parse_date("2024-01-01")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_returns_none_for_invalid_format(self, parse_date):
        assert parse_date("not-a-date") is None

    def test_returns_none_for_partial_date(self, parse_date):
        assert parse_date("2024-99-99") is None


# ── TCH _parse_amount (formato chileno: puntos de miles, coma decimal) ────────

class TestTchParseAmount:
    def test_returns_none_for_none(self):
        assert tch_parse_amount(None) is None

    def test_returns_none_for_empty_string(self):
        assert tch_parse_amount("") is None

    def test_parses_integer_amount(self):
        assert tch_parse_amount("12500") == Decimal("12500")

    def test_parses_chilean_thousands_separator(self):
        # "1.234" → miles → 1234 (el punto es separador de miles, no decimal)
        assert tch_parse_amount("1.234") == Decimal("1234")

    def test_parses_chilean_thousands_and_comma_decimal(self):
        # "1.234,56" → "1234.56"
        assert tch_parse_amount("1.234,56") == Decimal("1234.56")

    def test_returns_none_for_non_numeric_string(self):
        assert tch_parse_amount("abc") is None

    def test_strips_whitespace(self):
        assert tch_parse_amount("  500  ") == Decimal("500")


# ── Toku _parse_amount (coma decimal simple, quantize a 2 decimales) ─────────

class TestTokuParseAmount:
    def test_returns_none_for_none(self):
        assert toku_parse_amount(None) is None

    def test_returns_none_for_empty_string(self):
        assert toku_parse_amount("") is None

    def test_parses_integer_as_decimal(self):
        result = toku_parse_amount("6490")
        assert result == Decimal("6490.00")

    def test_parses_dot_decimal(self):
        result = toku_parse_amount("6490.50")
        assert result == Decimal("6490.50")

    def test_parses_comma_as_decimal_separator(self):
        result = toku_parse_amount("6490,50")
        assert result == Decimal("6490.50")

    def test_quantizes_to_two_decimal_places(self):
        result = toku_parse_amount("100")
        assert result == Decimal("100.00")
        assert result is not None
        assert str(result) == "100.00"

    def test_returns_none_for_non_numeric_string(self):
        assert toku_parse_amount("abc") is None


# ── Payku _parse_amount (formato limpio, solo strip) ─────────────────────────

class TestPaykuParseAmount:
    def test_returns_none_for_none(self):
        assert payku_parse_amount(None) is None

    def test_returns_none_for_empty_string(self):
        assert payku_parse_amount("") is None

    def test_parses_integer(self):
        assert payku_parse_amount("5000") == Decimal("5000")

    def test_parses_decimal(self):
        assert payku_parse_amount("5000.50") == Decimal("5000.50")

    def test_strips_whitespace(self):
        assert payku_parse_amount("  200  ") == Decimal("200")

    def test_returns_none_for_non_numeric(self):
        assert payku_parse_amount("abc") is None


# ── VP _parse_amount (idéntico a Payku) ─────────────────────────────────────

class TestVpParseAmount:
    def test_returns_none_for_none(self):
        assert vp_parse_amount(None) is None

    def test_parses_integer(self):
        assert vp_parse_amount("8000") == Decimal("8000")

    def test_parses_decimal(self):
        assert vp_parse_amount("8000.75") == Decimal("8000.75")

    def test_returns_none_for_non_numeric(self):
        assert vp_parse_amount("no_num") is None


# ── TCH _resolve_currency ────────────────────────────────────────────────────

class TestResolveCurrency:
    def _sub(self, reajuste: str | None) -> SimpleNamespace:
        return SimpleNamespace(reajuste=reajuste)

    def test_returns_uf_when_reajuste_is_uf_uppercase(self):
        assert _resolve_currency(self._sub("UF")) == "UF"  # type: ignore[arg-type]

    def test_returns_uf_when_reajuste_is_uf_lowercase(self):
        assert _resolve_currency(self._sub("uf")) == "UF"  # type: ignore[arg-type]

    def test_returns_uf_when_reajuste_has_whitespace(self):
        assert _resolve_currency(self._sub("  UF  ")) == "UF"  # type: ignore[arg-type]

    def test_returns_clp_when_reajuste_is_clp(self):
        assert _resolve_currency(self._sub("CLP")) == "CLP"  # type: ignore[arg-type]

    def test_returns_clp_when_reajuste_is_none(self):
        assert _resolve_currency(self._sub(None)) == "CLP"  # type: ignore[arg-type]

    def test_returns_clp_when_reajuste_is_empty(self):
        assert _resolve_currency(self._sub("")) == "CLP"  # type: ignore[arg-type]

    def test_returns_clp_for_other_values(self):
        assert _resolve_currency(self._sub("PESOS")) == "CLP"  # type: ignore[arg-type]


# ── Core model structure ─────────────────────────────────────────────────────

class TestCoreSubscriptionModel:
    def test_status_column_exists(self):
        columns = {c.name for c in CoreSubscription.__table__.columns}
        assert "status" in columns

    def test_status_column_is_nullable(self):
        col = CoreSubscription.__table__.columns["status"]
        assert col.nullable


class TestCoreClientAttributeModel:
    def test_table_exists(self):
        assert CoreClientAttribute.__tablename__ == "core_client_attributes"

    def test_required_columns_exist(self):
        columns = {c.name for c in CoreClientAttribute.__table__.columns}
        expected = {"id", "client_id", "source", "attribute_type", "attribute_value", "observed_at", "created_at"}
        assert expected.issubset(columns)

    def test_unique_constraint_exists(self):
        constraint_names = {c.name for c in CoreClientAttribute.__table__.constraints}
        assert "uq_core_client_attribute" in constraint_names

    def test_source_and_attribute_type_are_not_nullable(self):
        cols = {c.name: c for c in CoreClientAttribute.__table__.columns}
        assert not cols["source"].nullable
        assert not cols["attribute_type"].nullable
        assert not cols["attribute_value"].nullable

    def test_client_id_is_nullable(self):
        cols = {c.name: c for c in CoreClientAttribute.__table__.columns}
        assert cols["client_id"].nullable
