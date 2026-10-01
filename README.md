# CRM de Suscripciones

CRM interno para consultar y operar datos de suscripciones, clientes y cobros. VirtualPOS Sandbox, Toku y Payku se extraen a staging local; el navegador nunca recibe credenciales ni llama directamente a proveedores.

## Estado actual

- VirtualPOS Sandbox: sincronizacion read-only validada. Escrituras habilitadas para crear y editar clientes, crear planes, crear suscripciones, cancelar suscripciones y cancelar cargos. Reintento de cargos disponible. Requiere `VIRTUALPOS_WRITES_ENABLED=true`.
- Toku: sincronizacion read-only validada. Escrituras habilitadas para editar y eliminar clientes, y cambiar el estado de suscripciones. Requiere `TOKU_WRITES_ENABLED=true`.
- Payku: autenticacion y sincronizacion de clientes, planes y suscripciones validadas. Escrituras habilitadas para editar y eliminar clientes, y eliminar suscripciones. La coleccion de transacciones requiere aumentar `PAYKU_TIMEOUT_SECONDS` antes de una ejecucion completa. Requiere `PAYKU_WRITES_ENABLED=true`.
- TCH: canal de débito bancario con 28.982 clientes, 29.295 suscripciones y 255.914 transacciones cargadas desde reportes Excel históricos (2017–2026). Solo lectura; sin sincronizacion contra proveedor externo.
- Dashboard: consulta entidades canónicas consolidadas en la base `crm`, materializadas desde `source_records` (staging) de cada canal. El origen y los payloads saneados se conservan para trazabilidad. Las vistas consolidadas de Clientes y Suscripciones incluyen filtros por campos y paginación.

## Inicio local

1. Activa el entorno: `.\.venv\Scripts\Activate.ps1`.
2. Instala dependencias bloqueadas: `python -m pip install -r requirements.lock`.
3. Crea la configuracion local: `Copy-Item .env.example .env`.
4. Configura en `.env` solo las credenciales de los proveedores que vayas a sincronizar.
   Para Toku, usa `TOKU_BASE_URL=https://api.trytoku.com`.
5. Inicia PostgreSQL: `docker compose up -d postgres`. Se expone en `localhost:5433`.
6. Aplica el esquema: `alembic upgrade head`.
7. Configura `AUTH_JWT_SECRET` con al menos 32 caracteres aleatorios, más `INITIAL_ADMIN_USERNAME` e `INITIAL_ADMIN_PASSWORD`.
8. Crea el administrador inicial una sola vez: `python scripts\bootstrap_admin.py`.
9. Inicia la API: `uvicorn app.main:app --reload`.
10. En otra terminal, inicia el frontend: `cd frontend; npm install; npm run dev`.

Swagger queda disponible en `http://127.0.0.1:8000/docs` y el dashboard en `http://127.0.0.1:5173`.

## Sincronizacion manual

Con PostgreSQL iniciado y las migraciones aplicadas, ejecuta desde la raiz:

```powershell
.\.venv\Scripts\python.exe scripts\sync_virtualpos.py
.\.venv\Scripts\python.exe scripts\sync_toku.py
.\.venv\Scripts\python.exe scripts\sync_payku.py
```

Para reanudar una cuenta específica de VirtualPOS: `.\.venv\Scripts\python.exe scripts\sync_virtualpos.py virtualpos1` o `virtualpos2`.

Ejecuta cada comando por separado. El prefijo `>>` es el indicador de continuación de PowerShell, no forma parte de un comando.

Los sincronizadores configurados usan exclusivamente consultas `GET`. Cada ejecucion se registra en `sync_runs`; sus respuestas saneadas se guardan de forma idempotente en `source_records` mediante la clave `(source, resource_type, external_id)`.

La interfaz también permite ejecutar un ETL local o una sincronización completa read-only. El ETL local rematerializa `source_records` existentes en las entidades canónicas. La sincronización completa consulta los proveedores, actualiza `source_records` y consolida en las entidades canónicas; todo dentro de la base `crm`, sin bases locales por canal.

Las operaciones de escritura solo se exponen mediante rutas internas implementadas y se deniegan por defecto. Para habilitar un proveedor localmente, configura su bandera correspondiente en `.env`: `VIRTUALPOS_WRITES_ENABLED=true`, `TOKU_WRITES_ENABLED=true` o `PAYKU_WRITES_ENABLED=true`. La habilitación no autoriza operaciones fuera de las tareas `WR-*`, no entrega credenciales al navegador y no afecta las sincronizaciones read-only.

## API local

- Recursos CRM canonicos de VirtualPOS: `/api/v1/clients`, `/plans`, `/subscriptions`, `/charges` y `/payments`.
- Ejecuciones: `/api/v1/sync-runs`.
- Resumen staging: `/api/v1/staging/summary`.
- Registros staging paginados: `/api/v1/staging/records?source={virtualpos|toku|payku}&resource_type={tipo}`.
- Mini dashboard por canal: `/api/v1/staging/dashboard/{virtualpos|toku|payku}`.
- Dashboard general consolidado: `/api/v1/staging/dashboard/general`.
- Clientes consolidados: `/api/v1/staging/dashboard/general/clients`. Admite `filter_field={all|rut|name|last_name|platform|email|phone}`, `query`, `offset` y `limit`.
- Suscripciones consolidadas: `/api/v1/staging/dashboard/general/subscriptions`. Admite `filter_field={all|id|rut|client|platform|status}`, `query`, `offset` y `limit`. Excluye `SUSCRIPCION_FALLIDA` de VirtualPOS, `RECHAZADA` de TCH y `register` de Payku.
- Fichas VirtualPOS: `/api/v1/staging/virtualpos/clients/{uuid}`, `/plans/{id}`, `/subscriptions/{id}`, `/charges/{id}` y `/payments/{id}`.
- Fichas Toku y Payku: `/api/v1/staging/{toku|payku}/{resource}/{id}`.
- ETL local: `POST /api/v1/etl/run`; sincronización completa read-only: `POST /api/v1/etl/full-sync`; estado: `/api/v1/etl/runs/{run_id}`.
- TCH: `/api/v1/tch/summary`, `/api/v1/tch/clientes`, `/api/v1/tch/suscripciones`, `/api/v1/tch/transacciones` y sus fichas por ID.
- Escrituras VirtualPOS: `PUT /api/v1/writes/virtualpos/clients/{uuid}`, `POST /api/v1/writes/virtualpos/clients`, `POST /api/v1/writes/virtualpos/plans`, `POST /api/v1/writes/virtualpos/subscriptions`, `DELETE /api/v1/writes/virtualpos/subscriptions/{id}`, `DELETE /api/v1/writes/virtualpos/charges/{id}`, `POST /api/v1/writes/virtualpos/charges/{id}/retry`, `POST /api/v1/writes/virtualpos/subscriptions/{id}/charges`. Requieren `VIRTUALPOS_WRITES_ENABLED=true`.
- Escrituras Toku: `PUT /api/v1/writes/toku/customers/{id}`, `DELETE /api/v1/writes/toku/customers/{id}`, `POST /api/v1/writes/toku/subscriptions/{id}/status`. Requieren `TOKU_WRITES_ENABLED=true`.
- Escrituras Payku: `PUT /api/v1/writes/payku/clients/{id}`, `DELETE /api/v1/writes/payku/clients/{id}`, `DELETE /api/v1/writes/payku/subscriptions/{id}`. Requieren `PAYKU_WRITES_ENABLED=true`.
- Reportes operativos HTML: `GET /api/v1/reports/{general|virtualpos|toku|payku|tch}?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`. Requieren el permiso de dashboard correspondiente.
- Reintento de cargos VirtualPOS: la interfaz permite filtrar cargos rechazados y reintentarlos en lote. Las rutas internas requieren `virtualpos.charges.retry`, CSRF y `VIRTUALPOS_WRITES_ENABLED=true`.
- Recuperador de Socios VirtualPOS: reúne suscripciones canceladas exportables, cargos rechazados recuperables y rechazos asociados a tarjeta/cuenta. Los ciclos de reintento se cierran al cuarto día desde el envío según la siguiente sincronización disponible. Los links de cambio de tarjeta se muestran solo al solicitante y no se guardan.
- API Recuperador: `GET /api/v1/recovery/cancelled`, `GET /api/v1/recovery/cancelled/export`, `GET /api/v1/recovery/rejected?bucket=retry|card`, `GET /api/v1/recovery/card-expirations`, `POST /api/v1/recovery/retries` y `POST /api/v1/recovery/card-change-links/{subscription_id}`.

Consulta `docs/architecture.md` para el flujo de datos y `docs/tasks.md` para el estado de las tareas.

Los clientes VirtualPOS disponen de una interfaz de edición desde la tabla y su ficha. El formulario usa la ruta interna correspondiente cuando `WR-VP-01` está habilitada mediante su bandera local.

## Acceso y permisos

Todas las rutas bajo `/api/v1`, excepto `/api/v1/auth/login`, requieren una sesión autenticada. La sesión se mantiene en una cookie `HttpOnly`; las operaciones que modifican estado requieren además el token CSRF entregado por `/api/v1/auth/me`.

`admin` se inicializa mediante el script local y puede crear usuarios desde Administración. Un usuario puede recibir varios roles. Los roles combinan permisos fijos por canal, dashboard, recurso y operación; el backend aplica esos permisos antes de entregar datos, ejecutar sincronizaciones o llamar a un proveedor.

Una vez creado el administrador, elimina `INITIAL_ADMIN_PASSWORD` de `.env`. Nunca versionas `AUTH_JWT_SECRET` ni contraseñas.

`/api/v1/staging/records` acepta `filter_field` y `query` con las columnas operativas mostradas en cada tabla de VirtualPOS, Toku y Payku. También admite `sort_field` y `sort_direction=asc|desc`; los campos permitidos incluyen valores anidados visibles, y el orden se aplica antes de paginar.

## Seguridad

- `.env` y `.venv` son locales e ignorados por Git. No incluyas secretos en archivos versionados, mensajes de error ni documentacion.
- Antes de persistir se eliminan los campos de tarjeta y seguridad conocidos: PAN, CVV/CVC y codigos de seguridad.
- No almacenes ni documentes numeros completos de tarjetas, CVV/CVC ni credenciales, incluso si son datos de prueba.
