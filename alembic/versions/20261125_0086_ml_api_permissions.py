"""Register ML permissions without granting existing roles access.

Revision ID: 20261125_0086
Revises: 20261125_0085
"""

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20261125_0086"
down_revision = "20261125_0085"
branch_labels = None
depends_on = None
PERMISSIONS = {
    "ml.rejections.read": "Leer resultados sinteticos de ML",
    "ml.labels.read": "Leer etiquetas y revisiones de rechazos",
    "ml.labels.propose": "Proponer etiquetas de rechazo revisadas",
    "ml.labels.review": "Revisar y retirar etiquetas de rechazo",
    "ml.artifacts.read": "Leer metadatos seguros de artefactos ML",
    "ml.artifacts.review": "Revisar artefactos sinteticos ML",
    "ml.artifacts.simulate": "Simular publicacion y rollback de artefactos ML",
    **{f"ml.{source}.access": f"Acceso ML a {source}" for source in ("virtualpos1", "virtualpos2", "toku", "payku", "tch")},
}


def upgrade():
    for code, description in PERMISSIONS.items():
        op.get_bind().execute(sa.text("INSERT INTO permissions(id,code,description) VALUES(:id,:code,:description) ON CONFLICT(code) DO NOTHING"),
                              {"id": uuid4(), "code": code, "description": description})


def downgrade():
    # Preserve any operator assignments. Historical migrations/ML evidence remain intact.
    for code in PERMISSIONS:
        if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM role_permissions r JOIN permissions p ON p.id=r.permission_id WHERE p.code=:code)"), {"code": code}):
            raise RuntimeError("Downgrade blocked: ML permissions are assigned; review access first")
    for code in PERMISSIONS:
        op.get_bind().execute(sa.text("DELETE FROM permissions WHERE code=:code"), {"code": code})
