import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.auth import Role, User
from app.services.rbac import seed_permissions


def main() -> None:
    if not settings.initial_admin_username or not settings.initial_admin_password:
        raise RuntimeError("INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD must be configured")

    db = SessionLocal()
    try:
        seed_permissions(db)
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is None:
            admin_role = Role(name="admin", description="Full system administration")
            db.add(admin_role)
            db.flush()
            seed_permissions(db)
        if db.scalar(select(User).where(User.username == settings.initial_admin_username)):
            print("Initial admin already exists")
            return
        db.add(
            User(
                username=settings.initial_admin_username,
                password_hash=hash_password(settings.initial_admin_password),
                roles=[admin_role],
            )
        )
        db.commit()
        print("Initial admin created")
    finally:
        db.close()


if __name__ == "__main__":
    main()
