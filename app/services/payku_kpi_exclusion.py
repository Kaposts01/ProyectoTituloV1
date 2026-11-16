"""d207: suscripciones Payku excluidas de los indicadores (`PAYKU_KPI_EXCLUDED_IDS`).

Una suscripcion de prueba (CRM-14C) no debe mover MRR, activas, altas, churn, rechazos ni el recuperador. Sin migracion:
- la consolidacion (`channel_consolidation`) y el ETL Core (`core_payku_etl`) no materializan la suscripcion ni sus
  transacciones/ciclos (el ETL Core ademas retira lo que ya hubiera materializado: es derivado y se rehace solo);
- las lecturas directas de `p_transactions`/`p_cycles` de los tableros filtran por `subscription_id`.
Las tablas crudas `p_*` se conservan (trazabilidad). Quitar un id de la lista lo devuelve en la siguiente corrida.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, true

from app.core.config import settings


def excluded_subscription_ids() -> frozenset[str]:
    """Ids externos (`su...`) excluidos; se lee en cada llamada para respetar cambios de configuracion en tests."""
    return settings.payku_kpi_excluded_id_set


def is_excluded(subscription_id: Any) -> bool:
    return subscription_id is not None and str(subscription_id) in excluded_subscription_ids()


def not_excluded(column: Any) -> Any:
    """Condicion SQL «la suscripcion de esta fila no esta excluida». Sin lista, `true()` (no cambia la consulta).

    Una fila sin suscripcion (`NULL`) no se excluye: `NOT IN` sobre NULL daria NULL y la descartaria.
    """
    ids = excluded_subscription_ids()
    if not ids:
        return true()
    return or_(column.is_(None), column.notin_(sorted(ids)))
