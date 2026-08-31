# CRM de Suscripciones

CRM interno para centralizar clientes, suscripciones y pagos recurrentes. El primer hito integra VirtualPOS Sandbox en modo de solo lectura.

## Inicio local

1. Activa el entorno virtual: `.\.venv\Scripts\Activate.ps1`
2. Instala las dependencias: `python -m pip install -r requirements.txt`
3. Crea tu configuración local: `Copy-Item .env.example .env`
4. Configura en `.env` las credenciales de los proveedores que vayas a sincronizar.
5. Inicia PostgreSQL: `docker compose up -d postgres` (se expone localmente en el puerto `5433`).
6. Aplica las migraciones: `alembic upgrade head`
7. Inicia la API: `uvicorn app.main:app --reload`
8. En otra terminal, inicia el dashboard: `cd frontend; npm install; npm run dev`

La documentación interactiva estará en `http://127.0.0.1:8000/docs`.
El dashboard estará en `http://127.0.0.1:5173` y redirige las rutas `/api` hacia FastAPI local.

## Sincronizacion manual

Con PostgreSQL iniciado y las migraciones aplicadas, ejecuta desde la raiz:

```powershell
.\.venv\Scripts\python.exe scripts\sync_virtualpos.py
.\.venv\Scripts\python.exe scripts\sync_toku.py
.\.venv\Scripts\python.exe scripts\sync_payku.py
```

Todas las operaciones son de solo lectura. Cada ejecución queda en `/api/v1/sync-runs` y sus payloads saneados en `source_records`. El dashboard y los menús de proveedores consultan el staging local; la futura `BD_Central` será la fuente de los indicadores consolidados.

## Endpoints CRM

- `/api/v1/clients`
- `/api/v1/plans`
- `/api/v1/subscriptions`
- `/api/v1/subscriptions/{uuid}/detail`
- `/api/v1/charges`
- `/api/v1/payments`
- `/api/v1/sync-runs`
- `/api/v1/staging/summary`
- `/api/v1/staging/records?source={virtualpos|toku|payku}&resource_type={tipo}`
- `/api/v1/staging/dashboard/{virtualpos|toku|payku}`

Los recursos CRM son la capa canónica actual de VirtualPOS. Las pantallas por proveedor usan staging y no llaman al proveedor desde el navegador. Cada canal tiene un mini dashboard con métricas, estados, actividad mensual, selector Cantidad/Monto y filtro anual, calculados solo con los campos disponibles en su staging.

## Seguridad

`.env` y `.venv` son locales y están ignorados por Git. No almacenes claves API, secretos, números completos de tarjeta ni CVV en el repositorio o la base de datos.
