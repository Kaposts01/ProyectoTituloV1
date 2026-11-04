"""Volcado determinista del esquema de las tablas `tch_*` a partir de la metadata de SQLAlchemy (D32).

Sirve para demostrar que renombrar atributos y clases del modelo TCH NO cambia el esquema: nombres de tabla,
columnas (nombre real, tipo, nulabilidad, PK, default de servidor), indices y constraints.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, UniqueConstraint
from sqlalchemy.dialects import postgresql


def dump_schema(metadata: MetaData, prefix: str = "tch_") -> dict[str, Any]:
    dialect = postgresql.dialect()
    out: dict[str, Any] = {}
    for name, table in sorted(metadata.tables.items()):
        if not name.startswith(prefix):
            continue
        columns = {}
        for column in table.columns:
            default = column.server_default
            columns[column.name] = {
                "type": column.type.compile(dialect=dialect),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
                "server_default": str(default.arg) if default is not None else None,
                "unique": bool(column.unique),
                "index": bool(column.index),
            }
        indexes = sorted(
            [index.name, [c.name for c in index.columns], bool(index.unique)] for index in table.indexes
        )
        uniques = sorted(
            [c.name, [col.name for col in c.columns]] for c in table.constraints if isinstance(c, UniqueConstraint)
        )
        foreign_keys = sorted(
            [fk.constraint.name, fk.parent.name, fk.target_fullname] for fk in table.foreign_keys
        )
        out[name] = {"columns": columns, "indexes": indexes, "unique_constraints": uniques, "foreign_keys": foreign_keys}
    return out
