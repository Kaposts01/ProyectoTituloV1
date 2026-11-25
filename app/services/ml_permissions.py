"""ML access is additive to channel/resource rights and concrete VP account scope.

Names do not end in .view: default support/executive seeding must not grant these.
"""

ML_PERMISSIONS = {
    "ml.rejections.read": "Leer resultados sinteticos de ML",
    "ml.labels.read": "Leer etiquetas y revisiones de rechazos",
    "ml.labels.propose": "Proponer etiquetas de rechazo revisadas",
    "ml.labels.review": "Revisar y retirar etiquetas de rechazo",
    "ml.artifacts.read": "Leer metadatos seguros de artefactos ML",
    "ml.artifacts.review": "Revisar artefactos sinteticos ML",
    "ml.artifacts.simulate": "Simular publicacion y rollback de artefactos ML",
    **{f"ml.{source}.access": f"Acceso ML a {source}" for source in ("virtualpos1", "virtualpos2", "toku", "payku", "tch")},
}

RESOURCE_PERMISSIONS = {
    "virtualpos": {"charge": "virtualpos.charges.view", "payment": "virtualpos.payments.view",
                   "transaction": "virtualpos.payments.view", "subscription_state": "virtualpos.subscriptions.view"},
    "toku": {"charge": "toku.invoices.view", "payment": "toku.transactions.view",
             "transaction": "toku.transactions.view", "subscription_state": "toku.subscriptions.view"},
    "payku": {"charge": "payku.transactions.view", "payment": "payku.transactions.view",
              "transaction": "payku.transactions.view", "subscription_state": "payku.subscriptions.view"},
    "tch": {"charge": "tch.transacciones.view", "payment": "tch.transacciones.view",
            "transaction": "tch.transacciones.view", "subscription_state": "tch.suscripciones.view"},
}


def required_permissions(operation: str, source: str, resource: str | None = None) -> set[str]:
    if operation not in ML_PERMISSIONS or source not in {"virtualpos1", "virtualpos2", "toku", "payku", "tch"}:
        raise ValueError("Ambito ML invalido")
    provider = "virtualpos" if source.startswith("virtualpos") else source
    scope = RESOURCE_PERMISSIONS[provider]
    if resource is not None and resource not in scope:
        raise ValueError("Recurso ML invalido")
    return {operation, f"ml.{source}.access"} | ({scope[resource]} if resource else set(scope.values()))
