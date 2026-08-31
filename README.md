# CRM de Suscripciones

CRM interno para centralizar clientes, suscripciones y pagos recurrentes. El primer hito integra VirtualPOS Sandbox en modo de solo lectura.

## Inicio local

1. Activa el entorno virtual: `.\.venv\Scripts\Activate.ps1`
2. Instala las dependencias: `python -m pip install -r requirements.txt`
3. Crea tu configuración local: `Copy-Item .env.example .env`
4. Configura las credenciales Sandbox de VirtualPOS en `.env`.
5. Inicia PostgreSQL: `docker compose up -d postgres` (se expone localmente en el puerto `5433`).
6. Aplica las migraciones: `alembic upgrade head`
7. Inicia la API: `uvicorn app.main:app --reload`

La documentación interactiva estará en `http://127.0.0.1:8000/docs`.

## Seguridad

`.env` y `.venv` son locales y están ignorados por Git. No almacenes claves API, secretos, números completos de tarjeta ni CVV en el repositorio o la base de datos.
