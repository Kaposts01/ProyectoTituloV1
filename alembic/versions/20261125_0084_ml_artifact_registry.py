"""Prepared artifact registry, scoped release pointer and immutable audit.

Revision ID: 20261125_0084
Revises: 20261124_0083
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261125_0084"
down_revision = "20261124_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_artifacts",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("task", sa.String(2), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("manifest_relative", sa.String(255), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False), sa.Column("descriptor", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("id", "task", "source", name="uq_ml_artifact_scope"),
        sa.CheckConstraint("task IN ('p1','p2')", name="ck_ml_artifact_task"),
        sa.CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_artifact_source"),
    )
    op.create_table(
        "ml_artifact_releases",
        sa.Column("task", sa.String(2), primary_key=True), sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("active_artifact_id", sa.String(64), nullable=True), sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["active_artifact_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_release_scope", ondelete="RESTRICT"),
        sa.CheckConstraint("revision >= 0", name="ck_ml_release_revision"),
        sa.CheckConstraint("task IN ('p1','p2')", name="ck_ml_release_task"),
        sa.CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_release_source"),
    )
    op.create_table(
        "ml_artifact_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task", sa.String(2), nullable=False), sa.Column("source", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("action", sa.String(16), nullable=False),
        sa.Column("artifact_id", sa.String(64), nullable=True), sa.Column("active_after_id", sa.String(64), nullable=True),
        sa.Column("approval_sha256", sa.String(64), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task", "source", "revision", name="uq_ml_artifact_event_revision"),
        sa.ForeignKeyConstraint(["task", "source"], ["ml_artifact_releases.task", "ml_artifact_releases.source"], name="fk_ml_event_release", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_event_artifact_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["active_after_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_event_active_scope", ondelete="RESTRICT"),
        sa.CheckConstraint("revision > 0", name="ck_ml_event_revision"),
        sa.CheckConstraint("action IN ('registered','approved','promoted','rolled_back','disabled')", name="ck_ml_event_action"),
    )
    op.execute("""
    CREATE FUNCTION ml_registry_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Artifact registry history is immutable' USING ERRCODE='23514'; END $$;
    CREATE TRIGGER ml_artifact_immutable BEFORE UPDATE OR DELETE ON ml_artifacts
      FOR EACH ROW EXECUTE FUNCTION ml_registry_immutable();
    CREATE TRIGGER ml_event_immutable BEFORE UPDATE OR DELETE ON ml_artifact_events
      FOR EACH ROW EXECUTE FUNCTION ml_registry_immutable();
    CREATE TRIGGER ml_release_no_delete BEFORE DELETE ON ml_artifact_releases
      FOR EACH ROW EXECUTE FUNCTION ml_registry_immutable();
    CREATE FUNCTION ml_registry_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE current_release ml_artifact_releases%ROWTYPE; last_revision integer;
    BEGIN
      SELECT * INTO current_release FROM ml_artifact_releases WHERE task=NEW.task AND source=NEW.source FOR UPDATE;
      SELECT COALESCE(MAX(revision),0) INTO last_revision FROM ml_artifact_events WHERE task=NEW.task AND source=NEW.source;
      IF NEW.revision <> last_revision+1 OR NEW.revision IS DISTINCT FROM current_release.revision
         OR NEW.active_after_id IS DISTINCT FROM current_release.active_artifact_id THEN
        RAISE EXCEPTION 'Registry event/release mismatch' USING ERRCODE='23514';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM users WHERE id=NEW.actor_id AND is_active) THEN
        RAISE EXCEPTION 'Active registry actor required' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER ml_event_guard BEFORE INSERT ON ml_artifact_events
      FOR EACH ROW EXECUTE FUNCTION ml_registry_event_guard();
    CREATE FUNCTION ml_registry_release_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE current_release ml_artifact_releases%ROWTYPE; latest ml_artifact_events%ROWTYPE;
    BEGIN
      SELECT * INTO current_release FROM ml_artifact_releases WHERE task=NEW.task AND source=NEW.source;
      SELECT * INTO latest FROM ml_artifact_events WHERE task=NEW.task AND source=NEW.source ORDER BY revision DESC LIMIT 1;
      IF current_release.revision=0 AND current_release.active_artifact_id IS NULL AND latest.id IS NULL THEN RETURN NULL; END IF;
      IF latest.revision IS DISTINCT FROM current_release.revision
         OR latest.active_after_id IS DISTINCT FROM current_release.active_artifact_id THEN
        RAISE EXCEPTION 'Release requires matching immutable audit' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER ml_release_audit AFTER INSERT OR UPDATE ON ml_artifact_releases
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ml_registry_release_guard();
    """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM ml_artifacts) OR EXISTS(SELECT 1 FROM ml_artifact_releases)")):
        raise RuntimeError("Downgrade blocked: registry/history requires archival review")
    op.drop_table("ml_artifact_events")
    op.drop_table("ml_artifact_releases")
    op.drop_table("ml_artifacts")
    op.execute("DROP FUNCTION ml_registry_release_guard(); DROP FUNCTION ml_registry_event_guard(); DROP FUNCTION ml_registry_immutable();")
