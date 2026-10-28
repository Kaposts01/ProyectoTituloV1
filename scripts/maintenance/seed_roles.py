"""Siembra permisos y roles por defecto (soporte, ejecutivo). Idempotente; solo agrega permisos faltantes.

Uso: PYTHONPATH=. .venv/Scripts/python.exe scripts/maintenance/seed_roles.py
Usa la base del ambiente activo (APP_ENV / DATABASE_URL). Imprime solo nombres de rol y conteos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.rbac import seed_default_roles


def main() -> None:
    db = SessionLocal()
    try:
        result = seed_default_roles(db)
        db.commit()
    finally:
        db.close()
    print(f"Ambiente: {settings.env_mode}")
    for name, count in result.items():
        print(f"Rol {name}: {count} permisos")


if __name__ == "__main__":
    main()
