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
| VP-14 | Iniciar frontend CRM | Completada | Dashboard y vistas de clientes/suscripciones consumen la API. |
| TK-01 | Sincronizar colecciones read-only de Toku a staging | Completada | Ejecuciones registradas por fuente y payloads disponibles en `source_records`. |
| PK-01 | Sincronizar colecciones read-only de Payku a staging | Bloqueada | Clientes, planes y suscripciones disponibles; transacciones exceden el timeout local de 30 segundos. |
| STG-01 | Exponer staging por canal y rediseñar dashboard temporal | Completada | Dashboard resume staging local y cada canal consulta únicamente sus registros almacenados. |
| VP-15 | Mejorar vistas staging de VirtualPOS | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| TK-02 | Mejorar vistas staging de Toku | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| PK-02 | Mejorar vistas staging de Payku | Completada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| STG-02 | Crear mini dashboards operativos por canal | Completada | Cada canal muestra métricas, estados y actividad mensual desde staging local. |
| VP-16 | Crear ficha de cliente VirtualPOS desde staging | Completada | UUID abre la ficha y lista todas las suscripciones VirtualPOS relacionadas por RUT. |
| VP-17 | Crear fichas de plan y suscripción VirtualPOS | Completada | Planes listan suscripciones por plan_id; suscripciones muestran método de pago saneado y cargos por contexto de sync. |
| STG-03 | Crear fichas completas para Toku y Payku | Completada | Fichas locales muestran payload completo y relaciones explícitas por proveedor. |
| VP-18 | Añadir filtros y orden en tablas VirtualPOS | Completada | Filtros por columnas operativas; cargos y transacciones ordenados por fecha descendente. |
| STG-04 | Añadir filtros para tablas Toku y Payku | Completada | Filtros por las columnas visibles y corrección de RUT de clientes Toku. |
| VP-19 | Crear edición visual de clientes VirtualPOS | Completada | Botones y formulario visual; guardado remoto pendiente de autorizar escritura. |
| VP-20 | Mejorar ficha de cliente VirtualPOS | Completada | Etiquetas visuales en español y navegación a fichas de subscripción. |
| VP-21 | Traducir tipo de documento VirtualPOS | Completada | La ficha muestra RUT para 1 y DNI para 2. |
| STG-05 | Traducir etiquetas visuales de fichas | Completada | Etiquetas en español y enlaces seguros para URLs de planes VirtualPOS. |
| VP-22 | Crear cancelación visual de subscripciones VirtualPOS | Completada | Botones y confirmación visual; DELETE remoto pendiente de autorizar escritura. |
| VP-23 | Mejorar ficha de subscripción VirtualPOS | Completada | Navegación al plan y presentación segura del método de pago. |
| VP-24 | Restringir cancelación visual de subscripciones | Completada | Cancelar Sub se muestra solo para estado ACTIVA. |
| VP-25 | Crear ficha y navegación de cargos VirtualPOS | Completada | IDs abren fichas de cargo; fechas ordenadas de más reciente a más antigua. |
| VP-26 | Restaurar navegación en tablas de cargos y pagos | Completada | ID de cargo y UUID de pago abren sus fichas locales. |
| VP-27 | Desglosar datos de transacción VirtualPOS | Completada | order y client se muestran como campos individuales en la ficha. |

## Estado local de integraciones

- Fecha: 2026-09-09.
- VirtualPOS: sincronización manual completada localmente.
- Toku: sincronización manual completada localmente con 20 registros procesados.
- Payku: autenticación read-only validada para clientes, planes y suscripciones tras incorporar la firma `Sign` requerida. La colección de transacciones excede el timeout local de 30 segundos; aumentar `PAYKU_TIMEOUT_SECONDS` antes de ejecutar la sincronización completa.

## Mantenimiento en curso

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| MT-01 | Actualizar rama local desde GitHub | Completada | `master` queda alineada con `origin/master` sin sobrescribir cambios locales. |
| DOC-01 | Actualizar documentación del proyecto | Completada | Tareas, operación, arquitectura y proveedores reflejan el estado actual sin datos de pago sensibles. |
| DOC-02 | Documentar API VirtualPOS | Completada | `docs/Documentacion API VirtualPOS.md` cubre rutas, contratos, autenticación, paginación y estrategia incremental. |
| OPS-01 | Corregir configuración de sincronización local | Completada | VirtualPOS confirmó una sincronización idempotente; Toku se sincronizó correctamente con 21 registros y una segunda ejecución idempotente de 0 registros usando `api.trytoku.com`. No se expusieron credenciales. |
| MT-02 | Corregir relaciones y métricas VirtualPOS desde BD local | Completada | Clientes relacionan suscripciones por RUT; cargos muestran suscripción; KPIs filtran estados operativos y el monto de suscripciones se materializa desde la BD local. |
| MT-03 | Desglosar gráficos mensuales por estado | Completada | Actividad, cargos, transacciones y activaciones muestran barras apiladas por estado. |
| TK-03 | Migrar vistas Toku a BD local | Completada | Menú, tablas, fichas y dashboard Toku consultan las entidades canónicas materializadas desde Toku_Local; sincronizar Toku rematerializa solo desde esa BD. |
| PK-03 | Migrar vistas Payku a BD local | Completada | Menú, tablas, fichas y dashboard Payku consultan las entidades canónicas materializadas desde Payku_Local; sincronizar Payku rematerializa solo desde esa BD. |
| TK-04 | Ajustar suscripciones activas Toku | Completada | El resumen operativo cuenta y suma solo suscripciones `ACTIVE` vinculadas a un método `chargeable`. |
| TK-05 | Ajustar deudas y transacciones Toku | Completada | El resumen filtra deudas `PAID` y transacciones `SUCCESS`, muestra sus montos y desglosa los gráficos por estado. |
| UI-01 | Unificar paleta de gráficos | Completada | Todos los canales usan colores semánticos consistentes para sus estados y series. |
| TK-06 | Mejorar ficha de método de pago Toku | Completada | La ficha agrupa información útil y omite tokens, BIN y metadatos técnicos. |
| TK-07 | Mejorar tabla de métodos de pago Toku | Completada | La tabla muestra cliente, tarjeta, banco y asociaciones como valores escalares, sin objetos ni RUT incorrecto. |
| UI-02 | Ajustar anchos y márgenes de vistas | Completada | El contenido usa todo el ancho disponible y las tablas conservan sus columnas sin recortarse. |
| UI-03 | Mejorar filtros y orden de tablas | Completada | Los filtros son claros y cada columna de datos permite ordenar ascendente o descendente. |
| UI-04 | Hacer visibles los controles de tabla | Completada | El orden es evidente y los campos de estado usan un selector de valores disponibles. |
| UI-05 | Ordenar registros completos desde la tabla | Completada | El orden usa campos seguros, incluidos anidados, y se aplica antes de paginar los registros. |
| ETL-01 | Consolidar BDlocales en entidades canónicas | Completada | VirtualPOS, Toku y Payku se materializan de forma idempotente desde sus BDlocales; los payloads saneados mantienen trazabilidad. |
| ETL-02 | Orquestar sync read-only y ETL en segundo plano | Completada | Las rutas `/api/v1/etl/run` y `/api/v1/etl/full-sync` registran estado y fase sin exponer credenciales. |
| DB-01 | Consolidar BDlocales en una sola base por tablas de canal | Completada | Los datos existentes se migran idempotentemente a las tablas prefijadas, sin nueva lectura completa de proveedores; CRM conserva filtros, orden y fichas. |
| PK-04 | Corregir métricas y gráficos de ciclo de vida Payku | Completada | Transacciones, activaciones y bajas se agrupan por estado; activación usa `start` y caída usa `cancel`/`delete`/`suspended` con `end`. |

## Plan de consolidacion 2026-09-13

- Se inventariaron las BDlocales: VirtualPOS tiene 260.179 registros, Payku 58.338 y Toku 36.404. Se eligio migrar estos datos existentes en vez de ejecutar una sincronizacion completa contra los proveedores.
- El plan operativo, los riesgos de identidad de las dos cuentas VirtualPOS y la validacion de datos sensibles estan en `docs/PLAN_CONSOLIDACION_BDLOCAL.md`.
- Se aplico la migracion `20260913_0020`: las tablas de canal usan `vp_*`, `tk_*` y `p_*`; VirtualPOS conserva la plataforma en su identidad unica.
- La importacion usa la clave remota de cada BDlocal, procesa lotes saneados y no rematerializa TCH durante la carga de proveedores.
- Se cargaron las 354.921 filas historicas de VirtualPOS, Toku y Payku en `crm`; las sincronizaciones read-only para datos del dia estan en ejecucion y se validan por canal.
- Se corrigió el dashboard Payku: las activaciones usan `start`; las caídas consideran `cancel`, `delete` y `suspended` con `end`. Los payloads actuales no contienen fecha de reactivación ni historial fechado de estados.
- Se rematerializaron las 58.338 filas Payku: las 5.699 suscripciones canónicas ya tienen inicio y 1.441 término. Como Payku no entrega monto recurrente en la suscripción, se usa la última transacción `success` asociada como monto operativo para KPIs y gráficos.
- Los KPIs de Payku cuentan solo suscripciones `active` y transacciones `success`, mostrando sus montos cuando el proveedor los entrega.

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

## Actualizacion documental 2026-09-09

- Se corrigio el estado de VP-14: el dashboard y las vistas CRM iniciales estan implementados.
- PK-01 queda bloqueada hasta completar la lectura de transacciones Payku; clientes, planes y suscripciones ya se validaron localmente.
- `README.md`, `docs/architecture.md`, `frontend/README.md` y la referencia de Payku describen el staging de VirtualPOS, Toku y Payku, sus limites actuales y la operacion local.
- Se retiraron ejemplos de numeros de tarjeta y CVV de la documentacion versionada.

## Actualizacion documental 2026-09-11

- Se incorporaron VP-18 a VP-27: fichas de cargo y pago VirtualPOS, filtros avanzados por campo, modales de edicion y cancelacion visual (escritura remota pendiente), mejoras de etiquetas y navegacion en fichas de los tres canales.
- Se agrego DOC-02: guia completa de la API VirtualPOS en `docs/Documentacion API VirtualPOS.md`.
- `Dashboard_referencia.py` se incluye como template Streamlit de referencia para futuros dashboards analiticos; no es codigo productivo.

## Hito 2: Operaciones de escritura

Cada tarea sigue el mismo patrón de tres capas:
1. **Backend** — Nueva ruta en `app/api/v1/routes/`; llama al endpoint externo con las credenciales del proveedor.
2. **Servicio** — Tras respuesta exitosa: actualiza `source_records` en bdlocal y re-materializa el registro canónico (patrón ya establecido en `app/services/crm_materialization.py`).
3. **Frontend** — Habilita el botón existente en `frontend/src/App.tsx` (ya presente pero `disabled`) y conecta el `onClick` al nuevo endpoint interno.

### WR-VP: Escritura VirtualPOS

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-VP-01 | Habilitar edición y creación real de clientes VirtualPOS | Completada | `PUT /v3/client/:uuid` y `POST /v3/client` se ejecutan desde modales internos con selector VP1/VP2; bdlocal actualizada; edición y creación operativas. |
| WR-VP-02 | Habilitar cancelación real de suscripciones VirtualPOS | Completada | `DELETE /v3/suscription/:id` ejecutado desde el modal de confirmación; estado en bdlocal cambia a CANCELADA. |
| WR-VP-03 | Habilitar cancelación real de cargos VirtualPOS | Completada | `DELETE /v3/charge/:id` ejecutado desde ficha y tabla; cargo actualizado en bdlocal. |
| WR-VP-04 | Habilitar cancelación real de pagos VirtualPOS | Pendiente | `DELETE /v3/payment/:uuid` ejecutado desde ficha y tabla; pago actualizado en bdlocal. |
| WR-VP-05 | Flujo especial: crear cargo en suscripción activa y reasignar | En curso | `POST /v3/charge` disponible desde ficha de suscripción activa; modal de monto/fecha operativo. El flujo de reasignación completo (cancelar pendientes + recrear) requiere integración frontend pendiente. |

### WR-TK: Escritura Toku

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-TK-01 | Habilitar edición real de clientes Toku | Completada | `PUT /customers/:id` ejecutado desde modal; bdlocal actualizada; botón "Guardar cambios" operativo. |
| WR-TK-02 | Habilitar edición de invoices Toku | Pendiente | `PUT /invoices/:id` ejecutado con monto y/o fecha límite; bdlocal actualizada. |
| WR-TK-03 | Habilitar cambio de estado de suscripciones Toku | Completada | `POST /subscriptions/:id/status` ejecutado desde modal; bdlocal actualizada con nuevo estado. |
| WR-TK-04 | Habilitar eliminación de clientes Toku | Completada | `DELETE /customers/:id` ejecutado desde fila y ficha; registro marcado en bdlocal. |
| WR-TK-05 | Habilitar eliminación de invoices Toku | Pendiente | `DELETE /invoices/:id` ejecutado desde fila y ficha; bdlocal actualizada. |
| WR-TK-06 | Habilitar eliminación de suscripciones Toku | Pendiente | `DELETE /subscriptions/:id` ejecutado desde fila y ficha; bdlocal actualizada. |

### WR-PK: Escritura Payku

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-PK-01 | Habilitar edición de clientes Payku | Completada | `PUT /api/suclient/:id` ejecutado desde modal; campos de nombre, email y teléfono actualizados en bdlocal. |
| WR-PK-02 | Habilitar eliminación de suscripciones Payku | Completada | `DELETE /api/sususcription/:id` ejecutado desde fila y ficha; bdlocal actualizada. |
| WR-PK-03 | Habilitar eliminación de clientes suscripción Payku | Completada | `DELETE /api/suclient/:id` ejecutado desde fila y ficha; bdlocal actualizada. |

### WR-INF: Infraestructura transversal de escritura

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-INF-01 | Crear capa de servicio de escritura por proveedor | Completada | Módulos `app/services/write_virtualpos.py`, `write_toku.py`, `write_payku.py` implementados con manejo de errores HTTP, rollback local si la plataforma rechaza y registro durable en `write_runs`. |
| WR-INF-02 | Añadir rutas de escritura a la API interna | Completada | Endpoints POST/PUT/DELETE internos disponibles para VirtualPOS, Toku y Payku, documentados en Swagger y protegidos por CSRF y permisos. |

## Actualización documental 2026-09-11 (hito escritura)

- Se añadió el Hito 2: Operaciones de escritura con 13 tareas de escritura por proveedor (WR-VP-01 a WR-VP-05, WR-TK-01 a WR-TK-06, WR-PK-01 a WR-PK-03) y 2 tareas de infraestructura transversal (WR-INF-01, WR-INF-02).
- Las plataformas soportan: VirtualPOS (PUT cliente, DELETE suscripción/cargo/pago), Toku (PUT y DELETE sobre cliente/invoice/suscripción), Payku (PUT y DELETE sobre cliente/suscripción).

## Actualización documental 2026-09-11 (consolidación y tablas)

- Se añadieron migraciones `20260911_0007` a `20260911_0010`: soporte para payloads canónicos, relaciones de cliente, ejecuciones ETL y métodos de pago Toku.
- El ETL consolida las tres BDlocales en las entidades canónicas; la sincronización completa mantiene operaciones contra proveedores exclusivamente en modo read-only.
- Las tablas aprovechan el ancho disponible, filtran por columnas operativas, ofrecen selector de estados y ordenan globalmente antes de paginar, incluidos campos anidados visibles de Toku.
- La escritura remota continúa pendiente de autorización e implementación de las tareas `WR-*`; los botones visuales no realizan llamadas de escritura.
- WR-VP-05 documenta el flujo especial de reasignación de monto/fecha en VirtualPOS: no existe PUT directo sobre suscripciones; el flujo equivalente es cancelar los cargos pendientes y recrearlos con los valores nuevos.
- Todos los botones de escritura del frontend ya existen visualmente (disabled); se habilitarán conforme se implementen los endpoints internos correspondientes.

## Inicio de escritura controlada 2026-09-12

- Se reemplazó la política global de solo lectura por escritura controlada: las sincronizaciones y ETL siguen usando exclusivamente `GET`.
- Cada proveedor requiere una bandera local explícita (`VIRTUALPOS_WRITES_ENABLED`, `TOKU_WRITES_ENABLED` o `PAYKU_WRITES_ENABLED`) y permanece denegado por defecto.
- Se iniciaron `WR-INF-01` y `WR-INF-02`. Las operaciones remotas se limitarán a los flujos PUT/DELETE documentados; no se implementarán creaciones de pago, autorizaciones, reintentos, enlaces de pago, wallets ni payouts sin una nueva tarea aprobada.
- Se inició `WR-VP-01`: el backend cuenta con el registro durable `write_runs`, el cliente PUT de VirtualPOS y la ruta interna protegida. El modal de cliente ya utiliza la ruta interna; falta validar la operación contra Sandbox con la bandera local habilitada.

## Hito 3: Identidad y permisos

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| AUTH-01 | Implementar autenticación, roles y permisos por módulo | Completada | Login con cookie HttpOnly y CSRF; usuarios con varios roles; backend protege rutas y React oculta canales/tablas no autorizados. |
| AUTH-02 | Administración de usuarios y roles | En curso | `admin` crea usuarios, asigna múltiples roles y administra roles sobre el catálogo fijo de permisos. |
| TCH-01 | Restaurar canal TCH y cargar reportes Excel | Completada | El menú respeta los permisos asignados, las tablas TCH están migradas y los reportes locales se cargan de forma idempotente. |
| TCH-02 | Añadir gráficos operativos al dashboard TCH | Completada | El resumen muestra series mensuales de cargos y altas, filtrables por año, cantidad y monto. |
| TCH-03 | Corregir histórico, fichas y navegación TCH | Completada | Fechas se reconstruyen desde reportes, cargos históricos son idempotentes, TCH abre su dashboard y sus objetos tienen ficha local. |
| TCH-04 | Añadir clientes TCH | Completada | El menú expone clientes TCH, la tabla permite buscar y paginar, y la ficha muestra mandatos asociados. |
| TCH-05 | Añadir contacto y equivalente TCH | Completada | Fichas de clientes muestran contacto y dirección; suscripciones muestran el equivalente en pesos del mandato. |

## Actualización 2026-09-12 (identidad)

- Se agregaron usuarios, roles, permisos y relaciones muchos-a-muchos mediante la migración `20260912_0012`.
- El administrador inicial se crea de forma explícita con `scripts/bootstrap_admin.py` y valores no versionados de `.env`.
- Las sesiones usan cookie HttpOnly, JWT con secreto de al menos 32 caracteres y token CSRF para operaciones mutables.
- Las rutas CRM, staging, ETL, sincronización y escritura requieren sesión. Staging comprueba permisos por canal y recurso antes de devolver datos.
- Se corrigió el lanzador `scripts/bootstrap_admin.py` para ejecutarse desde la raíz con `python scripts\bootstrap_admin.py`.
- El formulario de edición VirtualPOS presenta `gender_id` como selector con los valores observados en `VirtualPOS_Local`: Masculino y Femenino.
- La migración `20260912_0013` agrega `clients.private_note`: la nota se guarda únicamente en el CRM y no se envía a VirtualPOS.
- La edición de clientes VirtualPOS valida Estado, Tipo, Tipo de documento y correo; los RUT se validan con módulo 11 y se guardan normalizados sin puntos y con guion.
- Los errores de validación de la edición de clientes se muestran dentro del modal, junto al campo marcado; la tabla solo confirma el guardado exitoso.
- Los filtros de plataforma VirtualPOS usan la estética de los botones de acción. La tabla de clientes incluye `Nuevo cliente`, que abre el formulario de creación y usa `POST /v3/client` mediante la API interna.

## Actualización 2026-09-12 (TCH)

- Las tablas TCH ya contienen 28.982 clientes, 29.295 suscripciones y 255.914 transacciones cargadas desde los reportes Excel locales.
- Se añadió la migración `20260912_0015`: crea los permisos del canal TCH y los asigna al rol `admin` existente.
- El menú TCH ofrece resumen, suscripciones y transacciones; el resumen consulta correctamente la última carga ETL de TCH.
- El dashboard TCH muestra cargos mensuales aceptados/rechazados y altas mensuales de mandatos, con selector de año y alternancia entre cantidad y monto.
- La recarga histórica procesó 29 reportes desde enero de 2017 hasta agosto de 2026. Los cargos de `BK:CT` se desnormalizan y no se repiten entre ventanas mensuales; las hojas de cargos aportan el detalle de fecha y rechazo.
- La suscripción usa `Fecha Activación` como inicio y `Fecha Eliminado` o `Fecha Rechazo` como término. TCH abre su dashboard al pulsar el canal y sus tablas enlazan a fichas locales de suscripción y transacción.
- Se agregó Clientes TCH: `28.982` socios disponibles en tabla paginada por RUT/nombre y ficha local con suscripciones relacionadas. La migración `20260912_0018` asigna su permiso de lectura al rol administrador.
- La migración `20260912_0019` incorpora contacto de cliente y equivalente en pesos. El backfill local completó teléfono para 28.962 clientes, email para 25.372 y el equivalente para las 29.295 suscripciones TCH.

## Actualización 2026-09-14

- DB-01 marcada Completada: la migración `20260913_0020` consolidó las tablas de canal con prefijos `vp_*`, `tk_*` y `p_*`; las 354.921 filas históricas de los tres proveedores fueron importadas y validadas.
- WR-VP-01 marcada Completada: edición y creación de clientes VirtualPOS operativas desde modales internos con selector VP1/VP2.
- WR-VP-02 marcada Completada: cancelación real de suscripciones VirtualPOS operativa; `DELETE /v3/suscription/:id` ejecutado desde modal de confirmación.
- WR-VP-03 marcada Completada: cancelación real de cargos VirtualPOS operativa; `DELETE /v3/charge/:id` ejecutado desde ficha y tabla.
- WR-VP-05 actualizada a En curso: `POST /v3/charge` disponible desde ficha de suscripción activa; el flujo de reasignación completo (cancelar pendientes + recrear) permanece pendiente en el frontend.
- WR-TK-01 marcada Completada: edición de clientes Toku operativa mediante `PUT /customers/:id`.
- WR-TK-03 renombrada y marcada Completada: cambio de estado de suscripciones Toku operativo mediante `POST /subscriptions/:id/status`.
- WR-TK-04 marcada Completada: eliminación de clientes Toku operativa mediante `DELETE /customers/:id`.
- WR-PK-01, WR-PK-02 y WR-PK-03 marcadas Completadas: edición de clientes, eliminación de suscripciones y eliminación de clientes Payku operativas.
- WR-INF-01 y WR-INF-02 marcadas Completadas: servicios de escritura para los tres proveedores implementados con `write_runs`, manejo de errores HTTP y rollback local.
- Los formularios de creación de cliente y plan VirtualPOS incluyen selector de cuenta (VP1/VP2) con validación y comprobación de duplicados.
- Se añadió la ruta `POST /api/v1/writes/virtualpos/plans` para crear planes VirtualPOS desde la interfaz.
