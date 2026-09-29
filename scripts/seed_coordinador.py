"""Crea el rol 'coordinador' (solo lectura) y los usuarios Tomas y Nico."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.auth import Permission, Role, User

READ_ONLY_PERMISSIONS = {
    "dashboard.view",
    "virtualpos.dashboard.view",
    "virtualpos.clients.view",
    "virtualpos.plans.view",
    "virtualpos.subscriptions.view",
    "virtualpos.charges.view",
    "virtualpos.payments.view",
    "toku.dashboard.view",
    "toku.customers.view",
    "toku.subscriptions.view",
    "toku.payment_methods.view",
    "toku.invoices.view",
    "toku.transactions.view",
    "payku.dashboard.view",
    "payku.clients.view",
    "payku.plans.view",
    "payku.subscriptions.view",
    "payku.transactions.view",
    "tch.dashboard.view",
    "tch.clientes.view",
    "tch.suscripciones.view",
    "tch.transacciones.view",
    "sync_runs.view",
}

USERS = [
    {"username": "tomas", "password": "123456"},
    {"username": "nico",  "password": "123456"},
]


def run() -> None:
    db = SessionLocal()
    try:
        # 1. Obtener o crear permisos (deben existir tras seed normal)
        perms = db.scalars(
            select(Permission).where(Permission.code.in_(READ_ONLY_PERMISSIONS))
        ).all()
        found_codes = {p.code for p in perms}
        missing = READ_ONLY_PERMISSIONS - found_codes
        if missing:
            print(f"ADVERTENCIA: permisos no inicializados aún: {missing}")
            print("Ejecuta primero el servidor para que seed_permissions se dispare.")
            sys.exit(1)

        # 2. Crear o actualizar rol coordinador
        role = db.scalar(select(Role).where(Role.name == "coordinador").options(selectinload(Role.permissions)))
        if role is None:
            role = Role(name="coordinador", description="Acceso de solo lectura — puede ver todo pero no editar, cancelar ni eliminar")
            db.add(role)
            print("Rol 'coordinador' creado.")
        else:
            print("Rol 'coordinador' ya existía — actualizando permisos.")
        role.permissions = list(perms)
        db.flush()

        # 3. Crear usuarios
        for u in USERS:
            existing = db.scalar(select(User).where(User.username == u["username"]))
            if existing:
                print(f"Usuario '{u['username']}' ya existe — omitiendo.")
                continue
            user = User(
                username=u["username"],
                password_hash=hash_password(u["password"]),
                is_active=True,
                roles=[role],
            )
            db.add(user)
            print(f"Usuario '{u['username']}' creado.")

        db.commit()
        print("\nListo.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
