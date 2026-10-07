"""Seed verified limits and mappings for the four source channels.

Revision ID: 20261007_0025
Revises: 20261007_0024
Create Date: 2026-10-07
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0025"
down_revision = "20261007_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    mappings = sa.table(
        "data_catalog_mappings",
        sa.column("id", postgresql.UUID(as_uuid=True)), sa.column("source", sa.String),
        sa.column("source_resource", sa.String), sa.column("source_field", sa.String),
        sa.column("staging_table", sa.String), sa.column("core_entity", sa.String),
        sa.column("core_field", sa.String), sa.column("transformation", sa.Text),
        sa.column("verification_status", sa.String), sa.column("limitation", sa.Text),
    )
    scenarios = sa.table(
        "qa_scenarios", sa.column("id", postgresql.UUID(as_uuid=True)), sa.column("code", sa.String),
        sa.column("source", sa.String), sa.column("description", sa.Text),
        sa.column("expected_result", sa.Text), sa.column("coverage_status", sa.String),
    )
    op.bulk_insert(mappings, [
        {"id": uuid.uuid4(), "source": "virtualpos", "source_resource": "charge", "source_field": "subscription_external_id", "staging_table": "vp_charges", "core_entity": "core_charges", "core_field": "subscription_id", "transformation": "Resolve only by platform and external subscription ID.", "verification_status": "observed", "limitation": "Global payments lack a verified charge reference."},
        {"id": uuid.uuid4(), "source": "toku", "source_resource": "invoice", "source_field": "subscription_id", "staging_table": "tk_invoices", "core_entity": "core_charges", "core_field": "subscription_id", "transformation": "Resolve provider subscription ID when present.", "verification_status": "observed", "limitation": None},
        {"id": uuid.uuid4(), "source": "payku", "source_resource": "transaction", "source_field": "subscription_id", "staging_table": "p_transactions", "core_entity": "core_payments", "core_field": "subscription_id", "transformation": "Resolve provider subscription ID when present.", "verification_status": "observed", "limitation": "Historical transaction coverage is not certified."},
        {"id": uuid.uuid4(), "source": "tch", "source_resource": "transaction", "source_field": "numero_ficha", "staging_table": "tch_transacciones", "core_entity": "core_payments", "core_field": "subscription_id", "transformation": "Resolve through the TCH subscription ficha.", "verification_status": "observed", "limitation": "A monthly charge requires deterministic period evidence."},
    ])
    op.bulk_insert(scenarios, [
        {"id": uuid.uuid4(), "code": "VP-PAYMENT-WITHOUT-CHARGE", "source": "virtualpos", "description": "A payment without a verified charge relation remains unassigned to a charge.", "expected_result": "No inferred charge link is created.", "coverage_status": "planned"},
        {"id": uuid.uuid4(), "code": "TK-INVOICE-SUBSCRIPTION", "source": "toku", "description": "An invoice with a subscription ID creates a traceable charge relation.", "expected_result": "Charge resolves only through the provider subscription ID.", "coverage_status": "planned"},
        {"id": uuid.uuid4(), "code": "PK-HISTORY-LIMIT", "source": "payku", "description": "A transaction source can be materialized despite incomplete historical coverage.", "expected_result": "Catalog exposes the coverage limitation.", "coverage_status": "planned"},
        {"id": uuid.uuid4(), "code": "TCH-REJECTION-REASON", "source": "tch", "description": "A rejected transaction retains its response code and rejection reason.", "expected_result": "The payment preserves the source rejection evidence.", "coverage_status": "planned"},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM qa_scenarios WHERE code IN ('VP-PAYMENT-WITHOUT-CHARGE', 'TK-INVOICE-SUBSCRIPTION', 'PK-HISTORY-LIMIT', 'TCH-REJECTION-REASON')")
    op.execute("DELETE FROM data_catalog_mappings WHERE source IN ('virtualpos', 'toku', 'payku', 'tch')")
