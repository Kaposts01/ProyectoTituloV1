from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Permission, Role, User

PERMISSIONS: dict[str, str] = {
    "users.manage": "Administrar usuarios",
    "roles.manage": "Administrar roles y sus permisos",
    "dashboard.view": "Ver dashboard global",
    "virtualpos.dashboard.view": "Ver dashboard VirtualPOS",
    "virtualpos.clients.view": "Ver clientes VirtualPOS",
    "virtualpos.plans.view": "Ver planes VirtualPOS",
    "virtualpos.subscriptions.view": "Ver suscripciones VirtualPOS",
    "virtualpos.subscriptions.create": "Crear suscripciones VirtualPOS",
    "virtualpos.subscriptions.cancel": "Cancelar suscripciones activas VirtualPOS",
    "virtualpos.charges.view": "Ver cargos VirtualPOS",
    "virtualpos.payments.view": "Ver pagos VirtualPOS",
    "virtualpos.clients.update": "Editar clientes VirtualPOS",
    "virtualpos.plans.update": "Crear y editar planes VirtualPOS",
    "virtualpos.charges.create": "Crear cargos en suscripciones VirtualPOS",
    "virtualpos.charges.cancel": "Cancelar cargos pendientes VirtualPOS",
    "virtualpos.charges.retry": "Reintentar cargos rechazados VirtualPOS",
    "virtualpos.recovery.view": "Ver Recuperador de Socios VirtualPOS",
    "virtualpos.recovery.export": "Exportar suscripciones canceladas VirtualPOS",
    "virtualpos.cards.change": "Generar links de cambio de tarjeta VirtualPOS",
    "toku.dashboard.view": "Ver dashboard Toku",
    "toku.customers.view": "Ver clientes Toku",
    "toku.customers.update": "Editar clientes Toku",
    "toku.customers.delete": "Eliminar clientes Toku",
    "toku.subscriptions.manage": "Gestionar estado de suscripciones Toku",
    "toku.subscriptions.view": "Ver suscripciones Toku",
    "toku.payment_methods.view": "Ver métodos de pago Toku",
    "toku.invoices.view": "Ver deudas Toku",
    "toku.transactions.view": "Ver transacciones Toku",
    "payku.dashboard.view": "Ver dashboard Payku",
    "payku.clients.view": "Ver clientes Payku",
    "payku.clients.update": "Editar clientes Payku",
    "payku.clients.delete": "Eliminar clientes Payku",
    "payku.plans.view": "Ver planes Payku",
    "payku.subscriptions.view": "Ver suscripciones Payku",
    "payku.subscriptions.cancel": "Cancelar suscripciones Payku",
    "payku.transactions.view": "Ver transacciones Payku",
    "tch.dashboard.view": "Ver dashboard TCH",
    "tch.clientes.view": "Ver clientes TCH",
    "tch.suscripciones.view": "Ver suscripciones TCH",
    "tch.transacciones.view": "Ver transacciones TCH",
    "etl.run": "Ejecutar ETL y sincronización completa",
    "sync.run": "Ejecutar sincronizaciones por canal",
    "sync_runs.view": "Ver historial de sincronizaciones",
}

_RESOURCE_PERMISSIONS = {
    "virtualpos": {
        "client": "virtualpos.clients.view",
        "plan": "virtualpos.plans.view",
        "subscription": "virtualpos.subscriptions.view",
        "charge": "virtualpos.charges.view",
        "payment": "virtualpos.payments.view",
    },
    "toku": {
        "customer": "toku.customers.view",
        "subscription": "toku.subscriptions.view",
        "payment_method": "toku.payment_methods.view",
        "invoice": "toku.invoices.view",
        "transaction": "toku.transactions.view",
    },
    "payku": {
        "client": "payku.clients.view",
        "plan": "payku.plans.view",
        "subscription": "payku.subscriptions.view",
        "transaction": "payku.transactions.view",
    },
}


def seed_permissions(db: Session) -> None:
    existing = {permission.code: permission for permission in db.scalars(select(Permission)).all()}
    for code, description in PERMISSIONS.items():
        if code not in existing:
            permission = Permission(code=code, description=description)
            db.add(permission)
            existing[code] = permission

    admin = db.scalar(select(Role).where(Role.name == "admin"))
    if admin is not None:
        admin.permissions = list(existing.values())
    db.flush()


def get_user(db: Session, user_id: str) -> User | None:
    return db.scalar(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )


def permission_codes(user: User) -> set[str]:
    return {permission.code for role in user.roles for permission in role.permissions}


def source_permission(source: str, resource_type: str | None = None) -> str:
    provider = "virtualpos" if source.startswith("virtualpos") else source
    if resource_type:
        try:
            return _RESOURCE_PERMISSIONS[provider][resource_type]
        except KeyError as exc:
            raise ValueError("Unknown provider resource") from exc
    if provider not in _RESOURCE_PERMISSIONS:
        raise ValueError("Unknown provider")
    return f"{provider}.dashboard.view"


def serialize_user(user: User) -> dict:
    roles = sorted(user.roles, key=lambda role: role.name)
    return {
        "id": str(user.id),
        "username": user.username,
        "is_active": user.is_active,
        "roles": [{"id": str(role.id), "name": role.name} for role in roles],
        "permissions": sorted(permission_codes(user)),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
