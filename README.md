# CRM de Suscripciones

CRM interno read-only para consultar datos de suscripciones, clientes y cobros. VirtualPOS Sandbox, Toku y Payku se extraen a staging local; el navegador nunca recibe credenciales ni llama a proveedores.

## Estado actual

- VirtualPOS Sandbox: sincronizacion read-only validada para clientes, planes, suscripciones, cargos y pagos.
- Toku: sincronizacion read-only validada para clientes, deudas, metodos de pago, suscripciones y transacciones.
- Payku: autenticacion y sincronizacion de clientes, planes y suscripciones validadas. La coleccion de transacciones requiere aumentar `PAYKU_TIMEOUT_SECONDS` antes de una ejecucion completa.
- Dashboard: muestra los datos de staging por canal. No es aun un dashboard consolidado: `BD_Central` y su ETL son trabajo futuro.

## Inicio local

1. Activa el entorno: `.\.venv\Scripts\Activate.ps1`.
2. Instala dependencias: `python -m pip install -r requirements.txt`.
3. Crea la configuracion local: `Copy-Item .env.example .env`.
4. Configura en `.env` solo las credenciales de los proveedores que vayas a sincronizar.
5. Inicia PostgreSQL: `docker compose up -d postgres`. Se expone en `localhost:5433`.
6. Aplica el esquema: `alembic upgrade head`.
7. Inicia la API: `uvicorn app.main:app --reload`.
8. En otra terminal, inicia el frontend: `cd frontend; npm install; npm run dev`.

Swagger queda disponible en `http://127.0.0.1:8000/docs` y el dashboard en `http://127.0.0.1:5173`.

## Sincronizacion manual

Con PostgreSQL iniciado y las migraciones aplicadas, ejecuta desde la raiz:

```powershell
.\.venv\Scripts\python.exe scripts\sync_virtualpos.py
.\.venv\Scripts\python.exe scripts\sync_toku.py
.\.venv\Scripts\python.exe scripts\sync_payku.py
```

Los sincronizadores configurados usan exclusivamente consultas `GET`. Cada ejecucion se registra en `sync_runs`; sus respuestas saneadas se guardan de forma idempotente en `source_records` mediante la clave `(source, resource_type, external_id)`.

## API local

- Recursos CRM canonicos de VirtualPOS: `/api/v1/clients`, `/plans`, `/subscriptions`, `/charges` y `/payments`.
- Ejecuciones: `/api/v1/sync-runs`.
- Resumen staging: `/api/v1/staging/summary`.
- Registros staging paginados: `/api/v1/staging/records?source={virtualpos|toku|payku}&resource_type={tipo}`.
- Mini dashboard por canal: `/api/v1/staging/dashboard/{virtualpos|toku|payku}`.
- Fichas VirtualPOS: `/api/v1/staging/virtualpos/clients/{uuid}`, `/plans/{id}`, `/subscriptions/{id}`, `/charges/{id}` y `/payments/{id}`.
- Fichas Toku y Payku: `/api/v1/staging/{toku|payku}/{resource}/{id}`.

Consulta `docs/architecture.md` para el flujo de datos y `docs/tasks.md` para el estado de las tareas.

Los clientes VirtualPOS disponen de una interfaz visual de edición desde la tabla y su ficha. El formulario no envía actualizaciones al proveedor mientras la integración Sandbox permanezca en modo solo lectura.

`/api/v1/staging/records` acepta `filter_field` y `query` con las columnas operativas mostradas en cada tabla de VirtualPOS, Toku y Payku. Cargos y transacciones de VirtualPOS se ordenan por fecha de cargo o pago descendente.

## Seguridad

- `.env` y `.venv` son locales e ignorados por Git. No incluyas secretos en archivos versionados, mensajes de error ni documentacion.
- Antes de persistir se eliminan los campos de tarjeta y seguridad conocidos: PAN, CVV/CVC y codigos de seguridad.
- No almacenes ni documentes numeros completos de tarjetas, CVV/CVC ni credenciales, incluso si son datos de prueba.
