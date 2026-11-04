"""D38: los valores en español guardados en la base NO cambian; solo los nombres de las constantes van en inglés."""

from app.models import billing


def test_request_statuses_keep_their_stored_spanish_values() -> None:
    assert billing.REQUEST_STATUSES == (
        "pendiente", "aprobada", "aplicando", "ejecutada", "rechazada", "expirada", "retirada", "fallida",
        "requiere_conciliacion", "no_ejecutable",
    )


def test_event_types_keep_their_stored_spanish_values() -> None:
    assert billing.EVENT_TYPES == (
        "creada", "aprobada", "autoaprobada", "rechazada", "retirada", "expirada", "aplicando", "aplicada", "fallida",
        "requiere_conciliacion", "no_ejecutable", "reintentada",
    )


def test_managed_charge_and_task_statuses_keep_their_stored_spanish_values() -> None:
    assert billing.MANAGED_CHARGE_STATUSES == ("creado", "cancelado", "compensado", "requiere_conciliacion")
    assert billing.TASK_STATUSES == ("abierta", "vencida", "cerrada", "no_aplica")


def test_column_defaults_still_store_the_spanish_value() -> None:
    assert billing.BillingChangeRequest.__table__.c.status.server_default.arg == "pendiente"
    assert billing.VpManagedCharge.__table__.c.status.server_default.arg == "creado"
    assert billing.BillingRenewalTask.__table__.c.status.server_default.arg == "abierta"
