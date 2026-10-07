"""Create the additive centralized Core foundation and QA catalog.

Revision ID: 20261007_0024
Revises: 20261001_0023
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0024"
down_revision = "20261001_0023"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)


def upgrade() -> None:
    op.create_table("core_clients", _id_column(), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("external_identities", _id_column(), sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_clients.id")), sa.Column("source", sa.String(50), nullable=False), sa.Column("resource_type", sa.String(50), nullable=False), sa.Column("external_id", sa.String(255), nullable=False), sa.Column("linked_at", sa.DateTime(timezone=True)), sa.Column("link_reason", sa.String(50)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("source", "resource_type", "external_id", name="uq_external_identity"))
    op.create_index("ix_external_identities_client_id", "external_identities", ["client_id"])
    op.create_table("core_subscriptions", _id_column(), sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_clients.id")), sa.Column("amount", sa.Numeric(18, 2)), sa.Column("currency", sa.String(3)), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_core_subscriptions_client_id", "core_subscriptions", ["client_id"])
    op.create_index("ix_core_subscriptions_started_at", "core_subscriptions", ["started_at"])
    op.create_index("ix_core_subscriptions_ended_at", "core_subscriptions", ["ended_at"])
    op.create_table("core_charges", _id_column(), sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_subscriptions.id"), nullable=False), sa.Column("period_reference", sa.String(50)), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("amount", sa.Numeric(18, 2)), sa.Column("currency", sa.String(3)), sa.Column("latest_rejection_payment_id", postgresql.UUID(as_uuid=True)), sa.Column("latest_rejection_code", sa.String(100)), sa.Column("latest_rejection_reason", sa.Text()), sa.Column("latest_rejection_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_core_charges_subscription_id", "core_charges", ["subscription_id"])
    op.create_index("ix_core_charges_due_at", "core_charges", ["due_at"])
    op.create_index("ix_core_charges_latest_rejection_at", "core_charges", ["latest_rejection_at"])
    op.create_table("core_payments", _id_column(), sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_subscriptions.id")), sa.Column("charge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_charges.id")), sa.Column("source_status", sa.String(100)), sa.Column("occurred_at", sa.DateTime(timezone=True)), sa.Column("amount", sa.Numeric(18, 2)), sa.Column("currency", sa.String(3)), sa.Column("rejection_code", sa.String(100)), sa.Column("rejection_reason", sa.Text()), sa.Column("rejection_reported_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    for column in ("subscription_id", "charge_id", "source_status", "occurred_at"):
        op.create_index(f"ix_core_payments_{column}", "core_payments", [column])
    op.create_foreign_key("fk_core_charges_latest_rejection_payment", "core_charges", "core_payments", ["latest_rejection_payment_id"], ["id"])
    op.create_table("source_record_observations", _id_column(), sa.Column("source_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_records.id"), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("payload_sanitized", postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column("provider_observed_at", sa.DateTime(timezone=True)), sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("source_record_id", "payload_hash", name="uq_source_observation_hash"))
    op.create_index("ix_source_record_observations_source_record_id", "source_record_observations", ["source_record_id"])
    op.create_table("data_catalog_mappings", _id_column(), sa.Column("source", sa.String(50), nullable=False), sa.Column("source_resource", sa.String(100), nullable=False), sa.Column("source_field", sa.String(150), nullable=False), sa.Column("staging_table", sa.String(100)), sa.Column("core_entity", sa.String(100), nullable=False), sa.Column("core_field", sa.String(150), nullable=False), sa.Column("transformation", sa.Text()), sa.Column("verification_status", sa.String(30), nullable=False, server_default="proposed"), sa.Column("limitation", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("source", "source_resource", "source_field", "core_entity", "core_field", name="uq_catalog_mapping"))
    op.create_index("ix_data_catalog_mappings_source", "data_catalog_mappings", ["source"])
    op.create_index("ix_data_catalog_mappings_core_entity", "data_catalog_mappings", ["core_entity"])
    op.create_table("qa_scenarios", _id_column(), sa.Column("code", sa.String(100), nullable=False), sa.Column("source", sa.String(50), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("expected_result", sa.Text(), nullable=False), sa.Column("coverage_status", sa.String(30), nullable=False, server_default="planned"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("code", name="uq_qa_scenario_code"))
    op.create_index("ix_qa_scenarios_source", "qa_scenarios", ["source"])


def downgrade() -> None:
    for table in ("qa_scenarios", "data_catalog_mappings", "source_record_observations", "core_payments", "core_charges", "core_subscriptions", "external_identities", "core_clients"):
        op.drop_table(table)
