"""Synthetic prospective registration and ordered immutable observation ledger.

Revision ID: 20261125_0087
Revises: 20261125_0086
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "20261125_0087"
down_revision = "20261125_0086"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ml_prospective_studies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("protocol", pg.JSONB(), nullable=False),
        sa.Column("protocol_sha256", sa.String(64), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("head_event_id", sa.String(64)),
        sa.CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_study_source"),
        sa.CheckConstraint("purpose='synthetic'", name="ck_ml_study_purpose"),
        sa.CheckConstraint("resource_type IN ('charge','payment','transaction')", name="ck_ml_study_resource"),
        sa.CheckConstraint("revision BETWEEN 0 AND 2000 AND ((revision=0)=(head_event_id IS NULL))", name="ck_ml_study_revision"))
    op.create_table("ml_prospective_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("study_id", sa.String(64), sa.ForeignKey("ml_prospective_studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("study_id", "revision", name="uq_ml_prospective_revision"),
        sa.UniqueConstraint("study_id", "request_id", name="uq_ml_prospective_request"),
        sa.CheckConstraint("revision BETWEEN 1 AND 2000", name="ck_ml_prospective_revision"),
        sa.CheckConstraint("kind IN ('enrolled','exposed','decision','outcome')", name="ck_ml_prospective_kind"))
    op.execute("""
    CREATE FUNCTION ml_prospective_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Prospective evidence is immutable' USING ERRCODE='23514'; END $$;
    CREATE TRIGGER ml_prospective_event_immutable BEFORE UPDATE OR DELETE ON ml_prospective_events
      FOR EACH ROW EXECUTE FUNCTION ml_prospective_immutable();
    CREATE FUNCTION ml_prospective_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' OR (to_jsonb(NEW)-'revision'-'head_event_id') IS DISTINCT FROM (to_jsonb(OLD)-'revision'-'head_event_id') THEN
        RAISE EXCEPTION 'Prospective protocol is immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER ml_prospective_protocol_immutable BEFORE UPDATE OR DELETE ON ml_prospective_studies
      FOR EACH ROW EXECUTE FUNCTION ml_prospective_identity();
    CREATE FUNCTION ml_prospective_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE s ml_prospective_studies; prior_id text;
    BEGIN
      SELECT * INTO s FROM ml_prospective_studies WHERE id=NEW.study_id FOR UPDATE;
      SELECT id INTO prior_id FROM ml_prospective_events WHERE study_id=NEW.study_id AND revision=NEW.revision-1;
      IF s.revision IS DISTINCT FROM NEW.revision OR s.head_event_id IS DISTINCT FROM NEW.id
         OR (NEW.revision>1 AND prior_id IS NULL)
         OR NEW.record->>'previous_id' IS DISTINCT FROM prior_id
         OR NEW.record->>'event_id' IS DISTINCT FROM NEW.id
         OR NEW.record->>'study_id' IS DISTINCT FROM NEW.study_id
         OR NEW.record->>'protocol_sha256' IS DISTINCT FROM s.protocol_sha256
         OR NEW.record->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
         OR NEW.record->>'request_id' IS DISTINCT FROM NEW.request_id::text
         OR NEW.record->>'kind' IS DISTINCT FROM NEW.kind
         OR (NEW.record->>'revision')::integer IS DISTINCT FROM NEW.revision
         OR (NEW.record->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at
         OR NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.actor_id AND is_active) THEN
        RAISE EXCEPTION 'Prospective event requires current ledger and active actor' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER ml_prospective_order BEFORE INSERT ON ml_prospective_events
      FOR EACH ROW EXECUTE FUNCTION ml_prospective_event_guard();
    CREATE FUNCTION ml_prospective_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE s ml_prospective_studies; e ml_prospective_events; n integer;
    BEGIN
      SELECT * INTO s FROM ml_prospective_studies WHERE id=NEW.id;
      SELECT count(*) INTO n FROM ml_prospective_events WHERE study_id=s.id;
      IF s.revision=0 AND s.head_event_id IS NULL AND n=0 THEN RETURN NULL; END IF;
      SELECT * INTO e FROM ml_prospective_events WHERE study_id=s.id ORDER BY revision DESC LIMIT 1;
      IF e.id IS DISTINCT FROM s.head_event_id OR e.revision IS DISTINCT FROM s.revision OR n<>s.revision THEN
        RAISE EXCEPTION 'Prospective head requires complete ledger' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER ml_prospective_head AFTER INSERT OR UPDATE ON ml_prospective_studies
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ml_prospective_head_guard();
    """)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM ml_prospective_studies)")):
        raise RuntimeError("Downgrade blocked: prospective history requires archival review")
    op.drop_table("ml_prospective_events")
    op.drop_table("ml_prospective_studies")
    op.execute("DROP FUNCTION ml_prospective_head_guard(); DROP FUNCTION ml_prospective_event_guard(); DROP FUNCTION ml_prospective_identity(); DROP FUNCTION ml_prospective_immutable();")
