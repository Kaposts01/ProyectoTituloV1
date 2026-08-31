# Tareas del proyecto

Este archivo es la fuente de estado del proyecto. Debe actualizarse al iniciar, bloquear, completar o modificar una tarea.

## Hito 1: VirtualPOS Sandbox (solo lectura)

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-01 | Inicializar Git, entorno Python y configuración segura | Completada | `.venv`, `.gitignore`, `.env.example` y `requirements.txt` disponibles; `.env` no se versiona. |
| VP-02 | Crear API FastAPI y persistencia PostgreSQL | Completada | API saludable, modelos y migración inicial definidos. |
| VP-03 | Implementar autenticación y cliente VirtualPOS | Completada | Firma HS256 generada localmente y peticiones solo de lectura. |
| VP-04 | Persistir staging idempotente y ejecuciones de sincronización | Completada | Repetir una sincronización no duplica registros externos. |
| VP-05 | Normalizar clientes, suscripciones y pagos | Completada | Las vistas canónicas preservan la referencia al origen. |
| VP-06 | Exponer consulta y estado de sincronización | Completada | Endpoints documentados y cubiertos por pruebas. |
| VP-07 | Validar contra Sandbox y documentar resultados | Completada | Ejecución real registrada sin exponer secretos. |

## Decisiones vigentes

- Backend: FastAPI y Python.
- Base de datos: PostgreSQL.
- Fuente inicial: VirtualPOS Sandbox.
- Operación contra proveedores: solo lectura durante el MVP.
- Secretos: exclusivamente en `.env` o en el gestor de secretos del entorno de despliegue.

## Verificación local

- Fecha: 2026-08-30.
- Entorno: Python 3.14 en `.venv` y PostgreSQL 17 mediante Docker Compose en `localhost:5433`.
- Resultado: pruebas unitarias y lint correctos; migración `20260830_0004` aplicada.
- El lanzador `python scripts\sync_virtualpos.py` fue verificado localmente tras corregir la resolución de imports.
- VP-07 fue validada mediante sincronizaciones Sandbox read-only; las credenciales permanecen exclusivamente en `.env`.

## Auditoría de secretos

- Fecha: 2026-08-30.
- Alcance: commit `c7e0f94`.
- Resultado: no hay archivos `.env` versionados ni patrones de claves AWS, tokens GitHub/Slack o claves privadas.
- `.env` y `.venv` permanecen ignorados por Git.
- `postman/` no forma parte del commit porque es un repositorio Git anidado sin historial.

## Configuración de OpenCode

- Fecha: 2026-08-30.
- Se añadió la skill local `.opencode/skills/prompt-optimizer/SKILL.md` y la regla permanente correspondiente en `AGENTS.md`.
- Se configuró el servidor MCP remoto Context7 en `.opencode/opencode.json` para documentación actualizada de librerías y APIs externas.
- La configuración se aplica tras reiniciar OpenCode.

## Próximas tareas priorizadas

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-08 | Inspeccionar y documentar los payloads reales de Sandbox | Completada | Campos, identificadores y paginación observados en Sandbox y documentados. |
| VP-09 | Completar paginación y sincronización incremental | Completada | Paginación y upsert condicional validados por dos sincronizaciones consecutivas. |
| VP-10 | Normalizar modelo canónico | Completada | Clientes, planes, suscripciones, cargos y pagos se materializan desde staging. |
| VP-11 | Crear API de consulta del CRM | Completada | Endpoints paginados para clientes, suscripciones, pagos y detalle. |
| VP-12 | Añadir pruebas de integración del sincronizador | Completada | Respuestas simuladas cubren éxito, paginación, duplicados y errores. |
| VP-13 | Programar sincronizaciones y alertas | Pendiente | Ejecución periódica con reintentos y registro de fallos. |
| VP-14 | Iniciar frontend CRM | En curso | Dashboard y vistas de clientes/suscripciones consumen la API. |
| TK-01 | Sincronizar colecciones read-only de Toku a staging | Completada | Ejecuciones registradas por fuente y payloads disponibles en `source_records`. |
| PK-01 | Sincronizar colecciones read-only de Payku a staging | Completada | Ejecuciones registradas por fuente y payloads disponibles en `source_records`. |
| STG-01 | Exponer staging por canal y rediseñar dashboard temporal | Completada | Dashboard resume staging local y cada canal consulta únicamente sus registros almacenados. |
| VP-15 | Mejorar vistas staging de VirtualPOS | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| TK-02 | Mejorar vistas staging de Toku | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| PK-02 | Mejorar vistas staging de Payku | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| STG-02 | Crear mini dashboards operativos por canal | Completada | Cada canal muestra métricas, estados y actividad mensual desde staging local. |

## Estado local de integraciones

- Fecha: 2026-08-31.
- VirtualPOS: sincronización manual completada localmente.
- Toku: sincronización manual completada localmente con 20 registros procesados.
- Payku: autenticación read-only validada para clientes, planes y suscripciones tras incorporar la firma `Sign` requerida. La colección de transacciones excede el timeout local de 30 segundos; aumentar `PAYKU_TIMEOUT_SECONDS` antes de ejecutar la sincronización completa.

## Avance 2026-08-30

- Se aplicaron las migraciones `20260830_0002` y `20260830_0003`, que crean las entidades canónicas y preservan el contexto de la suscripción al sincronizar cargos.
- Sandbox entrega `25` clientes, `8` planes, `16` suscripciones, `452` cargos y `35` pagos. Los payloads reales, envelopes e identificadores están documentados en `docs/virtualpos-sandbox.md` sin valores sensibles.
- El sincronizador pagina suscripciones, reconoce los envelopes reales del proveedor y evita reescribir payloads sin cambios; una segunda ejecución procesó `0` registros.
- Swagger se organiza como Postman: Cliente, Plan, Suscription, Charge y Payment. Se añadieron consultas read-only en `/api/v1/clients`, `/subscriptions`, `/charges` y `/payments`, con detalle por UUID, paginación y filtros por fuente/estado.
- Los campos de tarjeta y seguridad se eliminan antes de staging; la comprobación local sobre los 536 registros confirmó que no permanecen almacenados.
- VP-12 usa transacciones externas con `SAVEPOINT` en PostgreSQL: las pruebas simulan dos páginas, cargos, pagos, duplicados y errores sin dejar datos de prueba ni invocar VirtualPOS.
- Se aplicó la migración `20260830_0004`; los 8 planes disponibles en staging se normalizaron y se exponen en `/api/v1/plans`.
- Se inició `frontend/` con React, TypeScript y Vite. El dashboard muestra las metricas CRM, la ultima sincronizacion y los clientes recientes mediante los endpoints locales.
- El dashboard fue validado localmente en `http://127.0.0.1:5173`. La operacion manual esta documentada en `README.md` y `frontend/README.md`.
- Se retiraron las rutas proxy y metodos de escritura de VirtualPOS. La API publica conserva exclusivamente consultas CRM `GET`; las pruebas impiden reintroducir un proxy del proveedor.
- VP-14 incorpora detalles de cliente y suscripcion. El detalle de suscripcion devuelve el plan y cargos confirmados por identificadores externos, con paginacion de cargos.
- VP-14 incorpora el explorador de registros para clientes, planes, suscripciones, cargos y pagos; cada registro abre su detalle CRM. El detalle de cliente incluye los campos canonicos y tarjetas resumidas sin datos de tarjeta completos.
- Validación: `python -m pytest`, `ruff check app tests alembic scripts`, migración en `head` y sincronización Sandbox correcta.
- Payku y Toku permanecen como integraciones futuras: sus módulos se conservan, pero no registran rutas públicas ni requieren credenciales para iniciar el CRM. VirtualPOS conserva solo el cliente de lectura usado por la sincronización.
- VP-14 ajusta el explorador de registros por recurso: clientes muestran correo y telefono; planes reflejan el booleano de actividad; suscripciones, cargos y pagos incluyen sus fechas operativas.
- VP-14 incorpora navegacion lateral: VirtualPOS enlaza las vistas CRM existentes y Toku, Payku, TCH y Configuracion reservan sus secciones con una vista local "En construccion", sin activar proveedores.
- Toku y Payku exponen exclusivamente sus colecciones GET del menu lateral; el frontend renderiza las columnas que devuelve cada proveedor sin mezclarlas con el modelo CRM. TCH y Configuracion siguen reservados para trabajo futuro.
