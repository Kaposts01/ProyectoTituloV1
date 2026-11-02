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
    "core.identity.read": "Ver candidatos de identidad centralizada",
    "core.identity.review": "Aprobar o rechazar candidatos de identidad",
    "core.identity.merge": "Ejecutar merge técnico de identidades",
    "system.environment.switch": "Cambiar entre ambientes Producción y Sandbox",
    "virtualpos.billing_changes.request": "Solicitar cambios de cobro VirtualPOS",
    "virtualpos.billing_changes.approve": "Aprobar o rechazar cambios de cobro VirtualPOS",
    "virtualpos.billing_changes.view": "Ver bandeja e historial de cambios de cobro VirtualPOS",
    "virtualpos.billing_policy.manage": "Configurar aprobadores de cambios de cobro VirtualPOS",
    "toku.reports.import": "Importar reportes descargados de Toku",
    "virtualpos.reports.import": "Importar reportes PAT descargados del portal de VirtualPOS",
    "export.pii": "Exportar datos personales (RUT, nombre, correo, teléfono, dirección) en las exportaciones CSV",
    "subscriptions.cancellation.request": "Solicitar la baja de suscripciones (todos los canales)",
    "subscriptions.cancellation.approve": "Aprobar, rechazar, aplicar y reabrir solicitudes de baja de suscripciones",
    "subscriptions.cancellation.view": "Ver solicitudes de baja de suscripciones y su historial",
    "general.recovery.view": "Ver el Recuperador general (Operación)",
    "general.recovery.toku.view": "Ver la pestaña Toku del Recuperador general",
    "general.recovery.tch.view": "Ver la pestaña TCH del Recuperador general (solo lectura)",
    "general.billing_changes.view": "Ver Cambios de cobro en Operación",
    "webhooks.manage": "Ver la salud de los webhooks y reprocesar eventos fallidos",
}

# RT-14: panel de salud de webhooks. Permiso de administracion (no termina en `.view`, asi que soporte y ejecutivo no lo
# heredan). Sin migracion: `seed_permissions` (bootstrap_admin o scripts/maintenance/seed_roles.py) lo crea y lo da al rol
# `admin`.
WEBHOOKS_MANAGE = "webhooks.manage"

# --- Operación general (UX-12, REC-04, REC-06) ----------------------------------------------------------------------
# El Recuperador vive en /general/recuperador con una pestaña por canal; cada pestaña tiene su propio permiso y su API
# exige ese permiso. La pestaña VirtualPOS sigue usando `virtualpos.recovery.view` (API sin cambios).
GENERAL_RECOVERY_VIEW = "general.recovery.view"
RECOVERY_TOKU_VIEW = "general.recovery.toku.view"
RECOVERY_TCH_VIEW = "general.recovery.tch.view"
GENERAL_BILLING_VIEW = "general.billing_changes.view"

# Regla de la migracion 20261102_0052 (por datos, sin nombres de rol): cada permiso nuevo se otorga a los roles que
# ya tienen TODOS los permisos de la tupla. Asi nadie pierde ni gana acceso a datos que no veia.
GENERAL_GRANT_RULES: dict[str, tuple[str, ...]] = {
    GENERAL_RECOVERY_VIEW: ("virtualpos.recovery.view",),
    GENERAL_BILLING_VIEW: ("virtualpos.billing_changes.view",),
    RECOVERY_TOKU_VIEW: ("virtualpos.recovery.view", "toku.subscriptions.view"),
    RECOVERY_TCH_VIEW: ("virtualpos.recovery.view", "tch.suscripciones.view"),
}

# --- Baja de suscripciones multicanal (MGT-16) ---------------------------------------------------------------------
# D12: JEFATURA solicita; ADMIN o JEFATURA aprueban; EJECUTIVO solo lee. D28: los permisos «fantasma»
# (`virtualpos.payments.cancel`, `toku.invoices.update`, `toku.invoices.delete`) NO se siembran y el flujo nuevo no
# depende de ellos.
CANCELLATION_REQUEST = "subscriptions.cancellation.request"
CANCELLATION_APPROVE = "subscriptions.cancellation.approve"
CANCELLATION_VIEW = "subscriptions.cancellation.view"
JEFATURA_ROLE_NAME = "jefatura"
COORDINATOR_ROLE_NAME = "coordinador"

# Matriz rol -> permisos de baja que siembra la migracion 20261029_0050 (solo si el rol YA existe; nunca lo crea).
# `coordinador` no tiene permisos definidos en el codigo (la base de datos manda): hoy solo se le garantiza LECTURA de
# las solicitudes de baja; no solicita ni aprueba. `soporte` y `ejecutivo` heredan `.view` por sufijo.
CANCELLATION_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "admin": frozenset({CANCELLATION_REQUEST, CANCELLATION_APPROVE, CANCELLATION_VIEW}),
    JEFATURA_ROLE_NAME: frozenset({CANCELLATION_REQUEST, CANCELLATION_APPROVE, CANCELLATION_VIEW}),
    "soporte": frozenset({CANCELLATION_VIEW}),
    "ejecutivo": frozenset({CANCELLATION_VIEW}),
    COORDINATOR_ROLE_NAME: frozenset({CANCELLATION_VIEW}),
}

SUPPORT_ROLE_NAME = "soporte"
SUPPORT_ROLE_DESCRIPTION = "Soporte: consulta de todos los módulos, reintento de cargos y cambio de ambiente"
SUPPORT_EXTRA_PERMISSIONS = ("virtualpos.charges.retry", "system.environment.switch")


def support_permission_codes() -> set[str]:
    """Permisos del rol soporte: todos los `.view` + reintento de cargos + cambio de ambiente."""
    return {code for code in PERMISSIONS if code.endswith(".view")} | set(SUPPORT_EXTRA_PERMISSIONS)

EXECUTIVE_ROLE_NAME = "ejecutivo"
EXECUTIVE_ROLE_DESCRIPTION = "Ejecutivo: solo lectura de todos los módulos"


def executive_permission_codes() -> set[str]:
    """Permisos del rol ejecutivo: únicamente los `.view` (nada que escriba, exporte ni reintente)."""
    return {code for code in PERMISSIONS if code.endswith(".view")}


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


def _ensure_role(db: Session, name: str, description: str, wanted: set[str]) -> int:
    by_code = {p.code: p for p in db.scalars(select(Permission).where(Permission.code.in_(wanted))).all()}
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=description)
        db.add(role)
    present = {p.code for p in role.permissions}
    for code in sorted(wanted - present):
        role.permissions.append(by_code[code])
    db.flush()
    return len(role.permissions)


def ensure_cancellation_grants(db: Session) -> dict[str, int]:
    """Agrega los permisos de baja (`CANCELLATION_ROLE_GRANTS`) a los roles que YA existen; nunca crea roles ni quita
    permisos. Idempotente. Equivale a la migracion 20261029_0050 y sirve para roles creados despues de aplicarla
    (p. ej. `jefatura` o `coordinador`). Devuelve {rol_existente: permisos_agregados}."""
    wanted = {code for codes in CANCELLATION_ROLE_GRANTS.values() for code in codes}
    by_code = {p.code: p for p in db.scalars(select(Permission).where(Permission.code.in_(wanted))).all()}
    added: dict[str, int] = {}
    for role_name, codes in CANCELLATION_ROLE_GRANTS.items():
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            continue
        present = {p.code for p in role.permissions}
        missing = sorted(code for code in codes if code not in present and code in by_code)
        for code in missing:
            role.permissions.append(by_code[code])
        added[role_name] = len(missing)
    db.flush()
    return added


def ensure_general_grants(db: Session) -> dict[str, int]:
    """Equivale a la migracion 20261102_0052: otorga cada permiso `general.*` a los roles existentes que ya tienen todos
    los permisos de su regla (`GENERAL_GRANT_RULES`). Nunca crea roles ni quita permisos. Idempotente.
    Devuelve {rol: permisos_agregados} solo de los roles que recibieron alguno."""
    by_code = {p.code: p for p in db.scalars(select(Permission).where(Permission.code.in_(GENERAL_GRANT_RULES))).all()}
    added: dict[str, int] = {}
    for role in db.scalars(select(Role)).all():
        present = {p.code for p in role.permissions}
        for code, required in GENERAL_GRANT_RULES.items():
            if code in by_code and code not in present and set(required) <= present:
                role.permissions.append(by_code[code])
                added[role.name] = added.get(role.name, 0) + 1
    db.flush()
    return added


def seed_default_roles(db: Session) -> dict[str, int]:
    """Crea los roles `soporte` y `ejecutivo` o les agrega los permisos faltantes (nunca quita). Idempotente.

    No modifica admin/coordinador/jefatura, salvo por agregarles los permisos de BAJA de suscripciones si el rol ya
    existe (`ensure_cancellation_grants`) y los `general.*` de Operación a quien ya ve lo equivalente
    (`ensure_general_grants`). Devuelve {nombre_de_rol: cantidad_de_permisos} de soporte y ejecutivo.
    """
    seed_permissions(db)
    ensure_cancellation_grants(db)
    ensure_general_grants(db)
    return {
        SUPPORT_ROLE_NAME: _ensure_role(db, SUPPORT_ROLE_NAME, SUPPORT_ROLE_DESCRIPTION, support_permission_codes()),
        EXECUTIVE_ROLE_NAME: _ensure_role(
            db, EXECUTIVE_ROLE_NAME, EXECUTIVE_ROLE_DESCRIPTION, executive_permission_codes()
        ),
    }


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
