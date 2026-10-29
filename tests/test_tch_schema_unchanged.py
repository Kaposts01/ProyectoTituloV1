"""D32: renombrar clases/atributos del modelo TCH a ingles NO cambia el esquema de la base (sin migracion).

- La metadata actual produce el mismo esquema `tch_*` que el modelo ANTERIOR (referencia en `tests/golden/tch_schema.json`,
  generada con el modelo en español): tablas, columnas reales, tipos, indices y constraints.
- La metadata coincide con la base migrada de la sesion de test (`crm_test`): `alembic revision --autogenerate`
  saldria vacio para las tablas `tch_*` (comparacion de solo lectura; no se ejecuta ninguna migracion aqui).
"""

import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from schema_dump import dump_schema

from app.db.session import Base, engine
from app.models import tch

GOLDEN = Path(__file__).parent / "golden" / "tch_schema.json"


def test_tch_schema_matches_the_pre_rename_reference() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert dump_schema(Base.metadata) == expected


def test_tch_metadata_has_no_diff_against_the_migrated_database() -> None:
    def only_tch(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name.startswith("tch_")
        table = getattr(obj, "table", None)
        return table is None or table.name.startswith("tch_")

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": only_tch, "compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_renamed_attributes_keep_the_real_column_names() -> None:
    assert tch.TchTransaction.__table__.c.numero_ficha is tch.TchTransaction.file_number.property.columns[0]
    assert tch.TchTransaction.charge_date.property.columns[0].name == "fecha_cargo"
    assert tch.TchSubscription.__tablename__ == "tch_suscripciones"
    assert tch.TchMonthlyCollection.__tablename__ == "tch_recaudacion_mensual"
