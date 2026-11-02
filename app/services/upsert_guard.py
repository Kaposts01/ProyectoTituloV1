"""SYNC-O-07 / SYNC-D-07: guarda `IS DISTINCT FROM` para los `INSERT ... ON CONFLICT DO UPDATE`.

Un upsert sin guarda reescribe la fila aunque llegue identica (tupla nueva, WAL, indices, `updated_at` falso). Con la
guarda, el `DO UPDATE` solo toca las filas en que al menos una columna del `SET` cambia de valor, y el `rowcount` de la
sentencia pasa a ser "filas insertadas + filas realmente cambiadas". `IS DISTINCT FROM` trata NULL como un valor
(NULL vs NULL = igual; NULL vs 'x' = distinto) y compara JSONB por contenido.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Table, false, or_


def distinct_where(table: Table, set_: Mapping[str, Any]) -> Any:
    """`col1 IS DISTINCT FROM <nuevo1> OR col2 IS DISTINCT FROM <nuevo2> ...` sobre las columnas del SET.

    `set_` es el mismo diccionario que recibe `on_conflict_do_update` (valores `excluded.x` o expresiones). Las columnas
    de marca de tiempo que el propio SET fija (`updated_at`) no se comparan: cambiarian siempre.
    """
    conditions = [
        table.c[name].is_distinct_from(value)
        for name, value in set_.items()
        if name != "updated_at" and name in table.c
    ]
    return or_(*conditions) if conditions else false()
