"""Durable synthetic ML batches, separate from operational run records.

Revision ID: 20261125_0085
Revises: 20261125_0084
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "20261125_0085"
down_revision = "20261125_0084"
branch_labels = None
depends_on = None
SCOPE = "source IN ('virtualpos1','virtualpos2','toku','payku','tch')"


def upgrade():
    op.create_table("ml_core_receipts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("core_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("id", "source", name="uq_ml_core_receipt_scope"),
        sa.CheckConstraint(SCOPE, name="ck_ml_core_receipt_source"))
    op.create_table("ml_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("receipt_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("max_age_seconds", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id", "source", name="uq_ml_batch_scope"),
        sa.ForeignKeyConstraint(["receipt_id", "source"], ["ml_core_receipts.id", "ml_core_receipts.source"], ondelete="RESTRICT"),
        sa.CheckConstraint(SCOPE, name="ck_ml_batch_source"),
        sa.CheckConstraint("purpose = 'synthetic'", name="ck_ml_batch_purpose"),
        sa.CheckConstraint("total >= 0 AND total <= 1000 AND max_age_seconds BETWEEN 1 AND 86400 AND max_attempts BETWEEN 1 AND 5", name="ck_ml_batch_limits"),
        sa.CheckConstraint("state IN ('queued','running','completed','completed_with_errors')", name="ck_ml_batch_state"))
    op.create_table("ml_batch_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("id", "source", name="uq_ml_batch_result_scope"),
        sa.CheckConstraint(SCOPE, name="ck_ml_batch_result_source"),
        sa.CheckConstraint("purpose = 'synthetic'", name="ck_ml_batch_result_purpose"))
    op.create_table("ml_batch_items",
        sa.Column("batch_id", sa.String(64), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("resource_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("result_id", sa.String(64)),
        sa.ForeignKeyConstraint(["batch_id", "source"], ["ml_batches.id", "ml_batches.source"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_id", "source"], ["ml_batch_results.id", "ml_batch_results.source"], ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "input_sha256", name="uq_ml_batch_item_input"),
        sa.CheckConstraint("state IN ('queued','running','succeeded','failed')", name="ck_ml_batch_item_state"),
        sa.CheckConstraint("ordinal >= 0 AND attempts BETWEEN 0 AND 5", name="ck_ml_batch_item_attempts"),
        sa.CheckConstraint("resource_type IN ('charge','payment','transaction')", name="ck_ml_batch_item_resource"),
        sa.CheckConstraint("(state = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)", name="ck_ml_batch_item_lease"),
        sa.CheckConstraint("(state = 'succeeded') = (result_id IS NOT NULL)", name="ck_ml_batch_item_result"))
    op.create_index("ix_ml_batch_item_pending", "ml_batch_items", ["batch_id", "state", "ordinal"])
    op.create_table("ml_batch_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_token", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id", "ordinal"], ["ml_batch_items.batch_id", "ml_batch_items.ordinal"], ondelete="RESTRICT"),
        sa.CheckConstraint("action IN ('claimed','succeeded','retry','failed','lease_exhausted')", name="ck_ml_batch_event_action"),
        sa.CheckConstraint("error_code IS NULL OR error_code IN ('snapshot_changed','invalid_snapshot','calculation_failed','lease_expired')", name="ck_ml_batch_event_error"),
        sa.CheckConstraint("attempt BETWEEN 1 AND 5", name="ck_ml_batch_event_attempt"))
    op.execute("""
    CREATE FUNCTION ml_batch_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'ML batch evidence is immutable' USING ERRCODE='23514'; END $$;
    CREATE TRIGGER ml_core_receipt_immutable BEFORE UPDATE OR DELETE ON ml_core_receipts
      FOR EACH ROW EXECUTE FUNCTION ml_batch_immutable();
    CREATE TRIGGER ml_batch_result_immutable BEFORE UPDATE OR DELETE ON ml_batch_results
      FOR EACH ROW EXECUTE FUNCTION ml_batch_immutable();
    CREATE TRIGGER ml_batch_event_immutable BEFORE UPDATE OR DELETE ON ml_batch_events
      FOR EACH ROW EXECUTE FUNCTION ml_batch_immutable();
    CREATE FUNCTION ml_batch_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'ML batch history requires retention review' USING ERRCODE='23514'; END IF;
      IF TG_TABLE_NAME='ml_batches' THEN
        IF (to_jsonb(NEW)-'state'-'finished_at') IS DISTINCT FROM (to_jsonb(OLD)-'state'-'finished_at') THEN
          RAISE EXCEPTION 'ML batch manifest is immutable' USING ERRCODE='23514'; END IF;
      ELSE
        IF ROW(NEW.batch_id,NEW.ordinal,NEW.source,NEW.resource_type,NEW.resource_id,NEW.evidence_id,NEW.input_sha256)
            IS DISTINCT FROM ROW(OLD.batch_id,OLD.ordinal,OLD.source,OLD.resource_type,OLD.resource_id,OLD.evidence_id,OLD.input_sha256) THEN
          RAISE EXCEPTION 'ML batch input is immutable' USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER ml_batch_identity BEFORE UPDATE OR DELETE ON ml_batches
      FOR EACH ROW EXECUTE FUNCTION ml_batch_identity_guard();
    CREATE TRIGGER ml_batch_item_identity BEFORE UPDATE OR DELETE ON ml_batch_items
      FOR EACH ROW EXECUTE FUNCTION ml_batch_identity_guard();
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM ml_core_receipts) OR EXISTS(SELECT 1 FROM ml_batches) OR EXISTS(SELECT 1 FROM ml_batch_results)")):
        raise RuntimeError("Downgrade blocked: ML batch evidence requires archival review")
    for table in ("ml_batch_events", "ml_batch_items", "ml_batch_results", "ml_batches", "ml_core_receipts"):
        op.drop_table(table)
    op.execute("DROP FUNCTION ml_batch_identity_guard(); DROP FUNCTION ml_batch_immutable();")
