"""Contextual rejection annotation with immutable evidence and review history.

Revision ID: 20261124_0083
Revises: 20261118_0082
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261124_0083"
down_revision = "20261118_0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rejection_reason_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("processor", sa.String(40), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("processor_code", sa.String(3), nullable=False),
        sa.Column("normalized_text", sa.String(200), nullable=False),
        sa.Column("normalization_version", sa.String(40), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("privacy_reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "resource_type", "processor", "code", "processor_code", "normalized_text", "normalization_version", "taxonomy_version", name="uq_rejection_label_context"),
        sa.CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_label_source"),
        sa.CheckConstraint("resource_type IN ('charge','payment','transaction','subscription_state')", name="ck_label_resource"),
    )
    op.create_table(
        "rejection_reason_label_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rejection_reason_labels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("category", sa.String(16), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rationale", sa.String(24), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("label_id", "revision", name="uq_rejection_label_revision"),
        sa.CheckConstraint("revision > 0", name="ck_label_revision_positive"),
        sa.CheckConstraint("decision IN ('draft','approved','rejected','abstained','withdrawn')", name="ck_label_decision"),
        sa.CheckConstraint("category IS NULL OR category IN ('FUNDS','LIMIT','TECH','EXPIRED','BLOCKED','INVALID','FRAUD','ISSUER')", name="ck_label_category"),
        sa.CheckConstraint("severity IN ('temporary','permanent','unknown')", name="ck_label_severity"),
        sa.CheckConstraint("decision <> 'approved' OR category IS NOT NULL", name="ck_label_approved_category"),
        sa.CheckConstraint("decision IN ('draft','approved') OR (category IS NULL AND severity = 'unknown')", name="ck_label_no_false_label"),
    )
    op.execute("""
        CREATE FUNCTION ml_annotation_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Annotation history is immutable' USING ERRCODE = '23514';
        END $$;
        CREATE TRIGGER ml_context_immutable BEFORE UPDATE OR DELETE ON rejection_reason_labels
            FOR EACH ROW EXECUTE FUNCTION ml_annotation_immutable();
        CREATE TRIGGER ml_revision_immutable BEFORE UPDATE OR DELETE ON rejection_reason_label_revisions
            FOR EACH ROW EXECUTE FUNCTION ml_annotation_immutable();
        CREATE FUNCTION ml_annotation_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE previous rejection_reason_label_revisions%ROWTYPE; scope_processor text;
        BEGIN
            SELECT processor INTO scope_processor FROM rejection_reason_labels WHERE id = NEW.label_id FOR UPDATE;
            SELECT * INTO previous FROM rejection_reason_label_revisions
                WHERE label_id = NEW.label_id ORDER BY revision DESC LIMIT 1;
            IF NEW.revision <> COALESCE(previous.revision, 0) + 1 THEN
                RAISE EXCEPTION 'Stale annotation revision' USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.actor_id AND is_active) THEN
                RAISE EXCEPTION 'Active reviewer required' USING ERRCODE = '23514';
            END IF;
            IF previous.id IS NULL AND NEW.decision <> 'draft' THEN
                RAISE EXCEPTION 'Initial draft required' USING ERRCODE = '23514';
            END IF;
            IF NEW.decision IN ('approved','rejected','abstained') AND
                (previous.decision IS DISTINCT FROM 'draft' OR previous.actor_id = NEW.actor_id) THEN
                RAISE EXCEPTION 'Independent reviewer required' USING ERRCODE = '23514';
            END IF;
            IF NEW.decision = 'approved' AND (scope_processor = 'unresolved' OR
                NEW.category IS DISTINCT FROM previous.category OR NEW.severity IS DISTINCT FROM previous.severity) THEN
                RAISE EXCEPTION 'Review must match resolved proposal' USING ERRCODE = '23514';
            END IF;
            IF NEW.decision = 'withdrawn' AND COALESCE(previous.decision, '') NOT IN ('draft','approved') THEN
                RAISE EXCEPTION 'No active decision to withdraw' USING ERRCODE = '23514';
            END IF;
            IF NOT ((NEW.decision = 'draft' AND NEW.rationale IN ('annotation','correction')) OR
                    (NEW.decision = 'approved' AND NEW.rationale = 'independent_review') OR
                    (NEW.decision = 'rejected' AND NEW.rationale = 'conflicting_evidence') OR
                    (NEW.decision = 'abstained' AND NEW.rationale IN ('insufficient_evidence','conflicting_evidence')) OR
                    (NEW.decision = 'withdrawn' AND NEW.rationale = 'withdrawal')) THEN
                RAISE EXCEPTION 'Invalid rationale' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER ml_revision_guard BEFORE INSERT ON rejection_reason_label_revisions
            FOR EACH ROW EXECUTE FUNCTION ml_annotation_revision_guard();
    """)


def downgrade() -> None:
    # Never erase an annotation/review history silently, even in a rollback.
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM rejection_reason_labels)")):
        raise RuntimeError("Downgrade blocked: annotation history requires an explicit archival decision")
    op.drop_table("rejection_reason_label_revisions")
    op.drop_table("rejection_reason_labels")
    op.execute("DROP FUNCTION ml_annotation_revision_guard(); DROP FUNCTION ml_annotation_immutable();")
