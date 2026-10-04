# Tareas del proyecto

Este archivo es la fuente de estado del proyecto. Debe actualizarse al iniciar, bloquear, completar o modificar una tarea.

## Hito 1: VirtualPOS Sandbox (solo lectura)

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-01 | Inicializar Git, entorno Python y configuración segura | Completada | `.venv`, `.gitignore`, `.env.example` y `requirements.txt` disponibles; `.env` no se versiona. |
| VP-02 | Crear API FastAPI y persistencia PostgreSQL | Completada | API saludable, modelos y migración inicial definidos. |
| VP-03 | Implementar autenticación y cliente VirtualPOS | Completada | Firma HS256 generada localmente y peticiones solo de lectura. |
| VP-04 | Persistir staging idempotente y ejecuciones de sincronización | Completada | Repetir una sincronización no duplica registros externos. |
| VP-05 | Normalizar clientes, suscripciones y pagos | Completada | Las vistas centralizadas preservan la referencia al origen. |
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
| VP-10 | Normalizar modelo centralizado | Completada | Clientes, planes, suscripciones, cargos y pagos se materializan desde staging. |
| VP-11 | Crear API de consulta del CRM | Completada | Endpoints paginados para clientes, suscripciones, pagos y detalle. |
| VP-12 | Añadir pruebas de integración del sincronizador | Completada | Respuestas simuladas cubren éxito, paginación, duplicados y errores. |
| VP-13 | Programar sincronizaciones y alertas | Pendiente | Ejecución periódica con reintentos y registro de fallos. |
| VP-14 | Iniciar frontend CRM | Completada | Dashboard y vistas de clientes/suscripciones consumen la API. |
| TK-01 | Sincronizar colecciones read-only de Toku a staging | Completada | Ejecuciones registradas por fuente y payloads disponibles en `source_records`. |
| PK-01 | Sincronizar colecciones read-only de Payku a staging | Bloqueada | Payku devuelve transacciones recientes sin filtros, pero `date_init`/`date_end` devuelven cero incluso para un rango que contiene datos. El histórico requiere soporte o una exportación del proveedor. |
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
| STR-01 | Reorganizar estructura del repositorio | Completada | Artefactos locales quedan fuera de la raiz y excluidos de Git; scripts, documentacion vigente/historica y referencias quedan organizados sin romper comandos ni enlaces. |
| MT-01 | Actualizar rama local desde GitHub | Completada | `master` queda alineada con `origin/master` sin sobrescribir cambios locales. |
| OPS-07 | Levantar servicios y verificar base consolidada | En curso | PostgreSQL, migraciones, API y frontend operativos; tablas por canal verificadas en la base `crm`. |
| OPS-08 | Ejecutar sincronización manual multicanal | Bloqueada | Toku finalizó y consolidó 36.426 registros. VirtualPOS falló al recibir una respuesta no JSON al consultar cargos; Payku encontró IDs de transacción duplicados dentro de un lote `ON CONFLICT`. Requiere robustecer ambas rutas antes de reintentar. |
| DOC-03 | Estructurar documentación como vault de Obsidian | Completada | Índice navegable, arquitectura, producto, datos, integraciones, decisiones, memoria y sesiones creados sin modificar código ni configuraciones. |
| DOC-04 | Inicializar memoria persistente y modelo conceptual | Completada | Estado, decisiones, riesgos y modelo conceptual documentados sin modificar componentes técnicos. |
| DOC-05 | Normalizar terminología del modelo centralizado | Completada | La documentación activa usa "modelo centralizado" sin renombrar identificadores técnicos de compatibilidad. |
| DOC-06 | Consolidar instrucciones operativas de agentes | Completada | `AGENTS.md` define contexto, prioridades, arquitectura, memoria, Context7, validación y seguridad sin modificar componentes técnicos. |
| DOC-07 | Crear skill local project-memory | Completada | Skill Markdown descubierta tras reiniciar OpenCode; gestiona memoria, ADRs, contradicciones y crecimiento documental. |
| DOC-08 | Crear skill local data-modeling | Completada | Skill Markdown para diseñar y revisar el modelo centralizado sin acoplar Core a proveedores; descubrimiento, ruta y frontmatter validados en una nueva sesión de OpenCode. |
| DOC-09 | Definir identidad centralizada de socios | Completada | ADR-001 acepta UUID interno, identidades externas trazables, matching conservador, revision manual y merges reversibles sin implementar esquema tecnico. |
| DOC-10 | Crear skill local provider-integration | Completada | Skill Markdown para estandarizar connectors, Raw/STG, contratos, seguridad y operacion de proveedores; descubrimiento confirmado en OpenCode. |
| DEV-01 | Asegurar y reproducir configuracion de IA | Completada | `cookies.txt` queda ignorado; configuracion y skills de OpenCode quedan versionables; `AGENTS.md` es la unica jerarquia de instrucciones compartida. |
| DEV-02 | Consolidar herramientas de IA y vault Obsidian | Completada | OpenCode mantiene Context7 compartido; Claude conserva ajustes locales; el vault se abre desde la raiz y `.obsidian/` queda local. |
| DEV-03 | Corregir consistencia del entorno local | Completada | Vite redirige `/api` a FastAPI en `127.0.0.1:8000`; el healthcheck de PostgreSQL usa `POSTGRES_USER` y `POSTGRES_DB` de Compose. |
| DEV-04 | Establecer dependencias bloqueadas y CI | En curso | `.python-version`, `requirements.lock` y CI de backend/frontend creados; la base debe corregir 7 fallos de pytest y 74 hallazgos de Ruff para quedar en verde. |
| DEV-05 | Completar agentes documentales de OpenCode | Completada | Las definiciones locales `obsidian-vault` y `adr-governance` se validan con el cargador de OpenCode; el vault distingue navegacion de fuente tecnica y refleja que ADR-001 no esta implementado tecnicamente. |
| CORE-PLAN-01 | Planificar implementacion del Core centralizado | Pendiente | Alcance tecnico, entidades, migraciones, trazabilidad, pruebas y actualizaciones documentales aprobados antes de escribir codigo. |
| REP-01 | Generar reportes operativos por rango | Completada | VirtualPOS usa el diseño de referencia con snapshot histórico al cierre del rango, cobros y gráficos del período, alertas y tabla de activas; TCH usa su permiso de dashboard sin error 500. |
| DOC-01 | Actualizar documentación del proyecto | Completada | Tareas, operación, arquitectura y proveedores reflejan el estado actual sin datos de pago sensibles. |
| DOC-02 | Documentar API VirtualPOS | Completada | `docs/history/integrations/virtualpos-appscript-research.md` conserva la investigación histórica de rutas, contratos, autenticación, paginación y estrategia incremental. |
| OPS-01 | Corregir configuración de sincronización local | Completada | VirtualPOS confirmó una sincronización idempotente; Toku se sincronizó correctamente con 21 registros y una segunda ejecución idempotente de 0 registros usando `api.trytoku.com`. No se expusieron credenciales. |
| OPS-02 | Robustecer sincronización read-only de Toku | Completada | Reintenta hasta dos `ReadTimeout` de solicitudes GET y configura 120 segundos por intento; prueba automatizada validada. |
| OPS-03 | Robustecer sincronización read-only de Payku | Completada | Reintenta hasta dos `ReadTimeout` de solicitudes GET y configura 120 segundos por intento; prueba automatizada validada. |
| OPS-04 | Completar paginación de VirtualPOS | Completada | Clientes, pagos, suscripciones y cargos recorren todas las páginas con `page` y `limit`; prueba automatizada validada. |
| OPS-05 | Mostrar progreso y robustecer sync histórica | Completada | Los tres scripts muestran progreso por recurso; VirtualPOS reintenta lecturas y usa 120 segundos por intento sin omitir el historial. |
| OPS-06 | Respetar límite de transacciones Toku | Completada | Pausa un segundo entre páginas y reintenta respuestas temporales 429/503. |
| OPS-05 | Mostrar avance de sincronizaciones manuales | Completada | Scripts de VirtualPOS, Toku y Payku actualizan recurso y avance; usan porcentaje con totales y páginas/registros sin ellos. |
| MT-02 | Corregir relaciones y métricas VirtualPOS desde BD local | Completada | Clientes relacionan suscripciones por RUT; cargos muestran suscripción; KPIs filtran estados operativos y el monto de suscripciones se materializa desde la BD local. |
| MT-03 | Desglosar gráficos mensuales por estado | Completada | Actividad, cargos, transacciones y activaciones muestran barras apiladas por estado. |
| TK-03 | Migrar vistas Toku a BD local | Completada | Menú, tablas, fichas y dashboard Toku consultan las entidades centralizadas materializadas desde Toku_Local; sincronizar Toku rematerializa solo desde esa BD. |
| PK-03 | Migrar vistas Payku a BD local | Completada | Menú, tablas, fichas y dashboard Payku consultan las entidades centralizadas materializadas desde Payku_Local; sincronizar Payku rematerializa solo desde esa BD. |
| TK-04 | Ajustar suscripciones activas Toku | Completada | El resumen operativo muestra "Subscripciones activas" y MRR/ARPU solo desde suscripciones `ACTIVE` vinculadas a un método `chargeable`; los métodos cuentan solo estado `chargeable`. |
| TK-05 | Ajustar deudas y transacciones Toku | Completada | El resumen muestra "Deudas pagadas" (`PAID`) y "Transacciones pagadas" (`SUCCESS`) del año seleccionado, con sus montos. |
| UI-01 | Unificar paleta de gráficos | Completada | Todos los canales usan colores semánticos consistentes para sus estados y series. |
| TK-06 | Mejorar ficha de método de pago Toku | Completada | La ficha agrupa información útil y omite tokens, BIN y metadatos técnicos. |
| TK-07 | Mejorar tabla de métodos de pago Toku | Completada | La tabla muestra cliente, tarjeta, banco y asociaciones como valores escalares, sin objetos ni RUT incorrecto. |
| TK-08 | Corregir relaciones de ficha de cliente Toku | Completada | Los extractores y la consolidación preservan el customer ID aunque Toku lo entregue como texto; la ficha relaciona suscripciones y métodos por ID o RUT normalizado, deudas por suscripción y transacciones por método de pago cuando no hay cliente directo. |
| TK-09 | Corregir cobros y ficha de suscripción Toku | Completada | Estado secundario y último cobro usan la última transacción `SUCCESS` de `payment_intents[].id_subscription`; la ficha vincula métodos, deudas y transacciones por el ID de suscripción. |
| TK-10 | Filtrar y ordenar estado secundario Toku | En curso | El código permite filtrar y ordenar globalmente por estado secundario antes de paginar; la instancia API activa en `:8000` conserva un worker anterior y requiere recarga. |
| TK-11 | Mejorar registros relacionados de suscripciones Toku | Completada | Cliente muestra RUT y estado; métodos de pago muestran estado; deudas y transacciones muestran estado y fecha en sus fichas relacionadas. |
| UI-02 | Ajustar anchos y márgenes de vistas | Completada | El contenido usa todo el ancho disponible y las tablas conservan sus columnas sin recortarse. |
| UI-03 | Mejorar filtros y orden de tablas | Completada | Los filtros son claros y cada columna de datos permite ordenar ascendente o descendente. |
| UI-04 | Hacer visibles los controles de tabla | Completada | El orden es evidente y los campos de estado usan un selector de valores disponibles. |
| UI-05 | Ordenar registros completos desde la tabla | Completada | El orden usa campos seguros, incluidos anidados, y se aplica antes de paginar los registros. |
| UI-06 | Crear dashboard general consolidado | Completada | Inicio muestra KPIs, transacciones y activaciones mensuales de VirtualPOS, Toku, Payku y TCH desde sus entidades centralizadas. |
| UI-07 | Añadir clientes al dashboard general | Completada | Tabla consolidada por RUT muestra origen, suscripciones activas y ficha con IDs, suscripciones, cargos y transacciones relacionadas. |
| UI-08 | Añadir suscripciones al dashboard general | Completada | El submenú muestra suscripciones consolidadas con cliente, RUT, plataforma, estado, fechas y monto; permite filtrar y paginar; excluye fallidas VirtualPOS, rechazadas TCH y `register` Payku. |
| UI-09 | Corregir filtros y carga progresiva de tablas | Completada | Los estados se obtienen de todos los registros del recurso y cada tabla permite cargar más resultados. |
| UI-10 | Mejorar leyendas y fichas del dashboard general | Completada | Los gráficos distinguen sus series por color y cada canal resume operación, staging y última sincronización en una ficha. |
| UI-11 | Mejorar clientes consolidados | Completada | La tabla muestra RUT, nombre, plataformas y suscripciones activas; permite buscar por RUT, nombre, apellido, plataforma, correo o teléfono. |
| ETL-01 | Consolidar BDlocales en entidades centralizadas | Completada | VirtualPOS, Toku y Payku se materializan de forma idempotente desde sus BDlocales; los payloads saneados mantienen trazabilidad. |
| ETL-02 | Orquestar sync read-only y ETL en segundo plano | Completada | Las rutas `/api/v1/etl/run` y `/api/v1/etl/full-sync` registran estado y fase sin exponer credenciales. |
| DB-01 | Consolidar BDlocales en una sola base por tablas de canal | Completada | Los datos existentes se migran idempotentemente a las tablas prefijadas, sin nueva lectura completa de proveedores; CRM conserva filtros, orden y fichas. |
| PK-04 | Corregir métricas y gráficos de ciclo de vida Payku | Completada | Transacciones, activaciones y bajas se agrupan por estado; activación usa `start` y caída usa `cancel`/`delete`/`suspended` con `end`. |
| PK-05 | Corregir rango histórico de transacciones Payku | En curso | Payku sincroniza transacciones embebidas sin filtros históricos confiables. El backfill local desde `source_records` reconstruye idempotentemente `p_transactions`; falta certificar cobertura, orden y paginación con el proveedor. |
| REC-01 | Crear Recuperador de Socios VirtualPOS | Completada | Módulo con Canceladas, Reintento de Cobros y Tarjetas Vencidas; acciones y trazabilidad protegidas por permisos. |

## Auditoria tecnica 2026-10-01

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| AUD-01 | Auditar pendientes, dashboards, sincronizaciones y persistencia | Completada | Se identificaron tareas activas, brechas de paridad entre canales, riesgos de sincronizacion y la topologia PostgreSQL efectiva; los hallazgos se registraron sin exponer secretos. |
| FE-01 | Modularizar frontend por funcionalidades | En curso | El bloque de alertas operativas se extrajo a `features/dashboard/OperationalAlerts.tsx` y se reutiliza en todos los canales; resta separar navegacion, carga de datos, dashboard y exploradores de `App.tsx`. Los contratos API y permisos vigentes se preservan y la build de frontend queda correcta. |
| UI-12 | Incorporar rutas navegables del CRM | Completada | Las vistas principales se abren mediante rutas SPA estables, soportan carga directa, recarga e historial sin modificar endpoints ni permisos existentes. |
| UI-13 | Incorporar rutas de fichas de proveedor | Completada | Las fichas de recursos de VirtualPOS, Toku y Payku usan identificadores externos en la URL, soportan carga directa e historial sin exponer atributos personales. |
| UI-14 | Conservar estado seguro de listados en URL | Completada | Los listados consolidado y de proveedores conservan paginación, selección de campo, estado, orden y cuenta VirtualPOS mediante query parameters sin incluir términos de búsqueda ni atributos personales. |
| UI-15 | Incorporar rutas de suscripciones TCH | Completada | La ficha de suscripción TCH usa `numero_ficha` de DUES, único en la proyección, con carga directa e historial sin exponer RUT. |
| UI-16 | Reordenar tablas y enlaces de VirtualPOS | Completada | Las cinco tablas de VirtualPOS priorizan campos operativos y abren las fichas desde los atributos solicitados, sin exponer identificadores técnicos como columna. |
| PERF-01 | Reducir esperas de navegacion en frontend | Completada | Los dashboards respetan caché local de cinco minutos sin revalidar en cada navegación; las solicitudes se deduplican, búsquedas y listados cancelan cargas obsoletas. La caché se invalida tras una sincronización. El diferimiento de gráficos mensuales queda pendiente de una extracción segura de vistas. |
| UI-09 | Reordenar resumen operativo VirtualPOS | Completada | El dashboard prioriza recursos, indicadores, estados y tendencias; elimina el mensaje de consolidacion pendiente, muestra el ultimo `SyncRun` real y evita duplicar graficos de activacion y caida para VirtualPOS. |
| DASH-01 | Dar paridad operativa a Toku, Payku y TCH | Completada | Cada canal presenta KPIs, distribuciones, altas/bajas, suscripciones activas acumuladas, churn mensual y alertas definidos desde datos fechados y estados de su fuente. Toku compara transacciones reales, no facturas; Payku conserva el límite de cobertura histórica documentado; TCH usa reportes ETL locales. |
| SYNC-01 | Corregir y verificar contratos de sincronizacion por canal | En curso | Payku alinea su lanzador con transacciones embebidas y VirtualPOS conserva cargos embebidos con conciliacion agregada; VirtualPOS rematerializa solo registros cambiados en cada run. Faltan revisar el contrato historico de Payku y completar cobertura TCH. |
| DB-02 | Verificar topologia y dependencia de PostgreSQL | Completada | La aplicacion usa PostgreSQL 17 en `localhost:5433/crm`, con volumen persistente y revision `20260923_0022` en `head`; el esquema real y los datos por canal fueron verificados sin exponer secretos. |
| DB-03 | Reconciliar metadata Alembic y estadisticas PostgreSQL | Completada | La migracion `20261001_0023` alinea indices y metadata; `alembic check` no detecta operaciones pendientes y `ANALYZE` actualizo las estadisticas de tablas TCH voluminosas. |
| OPS-09 | Evaluar entrega de progreso en tiempo real | Pendiente | Se decide y documenta si el SSE actual se mantiene o requiere evolucion a WebSocket/infraestructura compartida, con autenticacion, reconexion y persistencia de eventos evaluadas; no se confunde el transporte al navegador con la lectura de proveedores. |

## Plan de consolidacion 2026-09-13

- Se inventariaron las BDlocales: VirtualPOS tiene 260.179 registros, Payku 58.338 y Toku 36.404. Se eligio migrar estos datos existentes en vez de ejecutar una sincronizacion completa contra los proveedores.
- El plan operativo, los riesgos de identidad de las dos cuentas VirtualPOS y la validacion de datos sensibles estan en `docs/history/migrations/bdlocales-consolidation-closed.md`.
- Se aplico la migracion `20260913_0020`: las tablas de canal usan `vp_*`, `tk_*` y `p_*`; VirtualPOS conserva la plataforma en su identidad unica.
- La importacion usa la clave remota de cada BDlocal, procesa lotes saneados y no rematerializa TCH durante la carga de proveedores.
- Se cargaron las 354.921 filas historicas de VirtualPOS, Toku y Payku en `crm`; las sincronizaciones read-only para datos del dia estan en ejecucion y se validan por canal.
- Se corrigió el dashboard Payku: las activaciones usan `start`; las caídas consideran `cancel`, `delete` y `suspended` con `end`. Los payloads actuales no contienen fecha de reactivación ni historial fechado de estados.
- Se rematerializaron las 58.338 filas Payku: las 5.699 suscripciones centralizadas ya tienen inicio y 1.441 término. Como Payku no entrega monto recurrente en la suscripción, se usa la última transacción `success` asociada como monto operativo para KPIs y gráficos.
- Los KPIs de Payku cuentan solo suscripciones `active` y transacciones `success`, mostrando sus montos cuando el proveedor los entrega.
- La consolidación ahora persiste en `p_subscriptions.amount` el monto de la última transacción `success` asociada; 2.283 suscripciones y las 484 activas ya tienen monto materializado.

## Avance 2026-08-30

- Se aplicaron las migraciones `20260830_0002` y `20260830_0003`, que crean las entidades centralizadas y preservan el contexto de la suscripción al sincronizar cargos.
- Sandbox entrega `25` clientes, `8` planes, `16` suscripciones, `452` cargos y `35` pagos. Los payloads reales, envelopes e identificadores están documentados en `docs/history/integrations/virtualpos-sandbox-2026-08.md` sin valores sensibles.
- El sincronizador pagina suscripciones, reconoce los envelopes reales del proveedor y evita reescribir payloads sin cambios; una segunda ejecución procesó `0` registros.
- Swagger se organiza como Postman: Cliente, Plan, Suscription, Charge y Payment. Se añadieron consultas read-only en `/api/v1/clients`, `/subscriptions`, `/charges` y `/payments`, con detalle por UUID, paginación y filtros por fuente/estado.
- Los campos de tarjeta y seguridad se eliminan antes de staging; la comprobación local sobre los 536 registros confirmó que no permanecen almacenados.
- VP-12 usa transacciones externas con `SAVEPOINT` en PostgreSQL: las pruebas simulan dos páginas, cargos, pagos, duplicados y errores sin dejar datos de prueba ni invocar VirtualPOS.
- Se aplicó la migración `20260830_0004`; los 8 planes disponibles en staging se normalizaron y se exponen en `/api/v1/plans`.
- Se inició `frontend/` con React, TypeScript y Vite. El dashboard muestra las metricas CRM, la ultima sincronizacion y los clientes recientes mediante los endpoints locales.
- El dashboard fue validado localmente en `http://127.0.0.1:5173`. La operacion manual esta documentada en `README.md` y `frontend/README.md`.
- Se retiraron las rutas proxy y metodos de escritura de VirtualPOS. La API publica conserva exclusivamente consultas CRM `GET`; las pruebas impiden reintroducir un proxy del proveedor.
- VP-14 incorpora detalles de cliente y suscripcion. El detalle de suscripcion devuelve el plan y cargos confirmados por identificadores externos, con paginacion de cargos.
- VP-14 incorpora el explorador de registros para clientes, planes, suscripciones, cargos y pagos; cada registro abre su detalle CRM. El detalle de cliente incluye los campos centralizados y tarjetas resumidas sin datos de tarjeta completos.
- Validación: `python -m pytest`, `ruff check app tests alembic scripts`, migración en `head` y sincronización Sandbox correcta.

## Actualizacion documental 2026-09-09

- Se corrigio el estado de VP-14: el dashboard y las vistas CRM iniciales estan implementados.
- PK-01 queda bloqueada hasta completar la lectura de transacciones Payku; clientes, planes y suscripciones ya se validaron localmente.
- `README.md`, `docs/architecture/overview.md`, `frontend/README.md` y la referencia de Payku describen el staging de VirtualPOS, Toku y Payku, sus limites actuales y la operacion local.
- Se retiraron ejemplos de numeros de tarjeta y CVV de la documentacion versionada.

## Actualizacion documental 2026-09-11

- Se incorporaron VP-18 a VP-27: fichas de cargo y pago VirtualPOS, filtros avanzados por campo, modales de edicion y cancelacion visual (escritura remota pendiente), mejoras de etiquetas y navegacion en fichas de los tres canales.
- Se agrego DOC-02: guia completa de la API VirtualPOS, conservada como investigación histórica en `docs/history/integrations/virtualpos-appscript-research.md`.
- `examples/dashboard_referencia.py` se incluye como template Streamlit de referencia para futuros dashboards analiticos; no es codigo productivo.

## Hito 2: Operaciones de escritura

Cada tarea sigue el mismo patrón de tres capas:
1. **Backend** — Nueva ruta en `app/api/v1/routes/`; llama al endpoint externo con las credenciales del proveedor.
2. **Servicio** — Tras respuesta exitosa: actualiza `source_records` en bdlocal y re-materializa el registro centralizado (patrón ya establecido en `app/services/crm_materialization.py`).
3. **Frontend** — Habilita el botón existente en `frontend/src/App.tsx` (ya presente pero `disabled`) y conecta el `onClick` al nuevo endpoint interno.

### WR-VP: Escritura VirtualPOS

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-VP-01 | Habilitar edición y creación real de clientes VirtualPOS | Completada | `PUT /v3/client/:uuid` y `POST /v3/client` se ejecutan desde modales internos con selector VP1/VP2; bdlocal actualizada; edición y creación operativas. |
| WR-VP-02 | Habilitar cancelación real de suscripciones VirtualPOS | Completada | `DELETE /v3/suscription/:id` ejecutado desde el modal de confirmación; estado en bdlocal cambia a CANCELADA. |
| WR-VP-03 | Habilitar cancelación real de cargos VirtualPOS | Completada | `DELETE /v3/charge/:id` ejecutado desde ficha y tabla; cargo actualizado en bdlocal. |
| WR-VP-04 | Habilitar cancelación real de pagos VirtualPOS | Completada | `DELETE /v3/payment/:uuid` ejecutado desde la ruta interna `DELETE /api/v1/writes/virtualpos/payments/{id}`; pago actualizado en staging y entidad centralizada. |
| WR-VP-05 | Flujo especial: crear cargo en suscripción activa y reasignar | En curso | `POST /v3/charge` disponible desde ficha de suscripción activa; modal de monto/fecha operativo. El flujo de reasignación completo (cancelar pendientes + recrear) requiere integración frontend pendiente. |

### WR-TK: Escritura Toku

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| WR-TK-01 | Habilitar edición real de clientes Toku | Completada | `PUT /customers/:id` ejecutado desde modal; bdlocal actualizada; botón "Guardar cambios" operativo. |
| WR-TK-02 | Habilitar edición de invoices Toku | Completada | `PUT /invoices/:id` ejecutado desde la ruta interna `PUT /api/v1/writes/toku/invoices/{id}`; SourceRecord actualizado. |
| WR-TK-03 | Habilitar cambio de estado de suscripciones Toku | Completada | `POST /subscriptions/:id/status` ejecutado desde modal; bdlocal actualizada con nuevo estado. |
| WR-TK-04 | Habilitar eliminación de clientes Toku | Completada | `DELETE /customers/:id` ejecutado desde fila y ficha; registro marcado en bdlocal. |
| WR-TK-05 | Habilitar eliminación de invoices Toku | Completada | `DELETE /invoices/:id` ejecutado desde la ruta interna `DELETE /api/v1/writes/toku/invoices/{id}`; SourceRecord marcado como deleted. |
| WR-TK-06 | Habilitar eliminación de suscripciones Toku | Completada | `DELETE /subscriptions/:id` ejecutado desde la ruta interna `DELETE /api/v1/writes/toku/subscriptions/{id}`; suscripción marcada como deleted. |

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

- Se añadieron migraciones `20260911_0007` a `20260911_0010`: soporte para payloads centralizados, relaciones de cliente, ejecuciones ETL y métodos de pago Toku.
- El ETL consolida las tres BDlocales en las entidades centralizadas; la sincronización completa mantiene operaciones contra proveedores exclusivamente en modo read-only.
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
| TCH-06 | Conciliar cobros TCH con control mensual | Completada | Migración `20260916_0021` crea `tch_recaudacion_mensual`; el resumen y el dashboard general usan los controles mensuales oficiales para montos y cantidades; el detalle de mandatos y cargos queda en las tablas de trazabilidad. |
| TCH-07 | Importar reportes TCH desde administración | Completada | Solo el rol `admin` puede seleccionar un archivo `.xlsx`; la carga incremental queda registrada y no expone ni conserva el archivo temporal. |

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
- OPS-05 completada: los scripts manuales de VirtualPOS, Toku y Payku actualizan en consola el recurso y el avance por página; muestran porcentaje cuando el proveedor informa totales y páginas/registros procesados en caso contrario.

## Actualización 2026-09-15 (retiro del flujo de BDlocales)

- Se detectó que `cancel_subscription`, `cancel_charge`, `retry_charge`, `update_client`, `create_client`, `create_plan`, `create_charge` y `create_subscription` en `write_virtualpos.py` intentaban reconciliar contra las tres BDlocales por canal (`VirtualPOS_Local`, `Toku_Local`, `Payku_Local`) usando columnas (`platform`, `remote_id`, `raw_payload`) que el esquema real ya no tiene desde la consolidación DB-01. Esto hacía fallar toda escritura de VirtualPOS con `reconciliation_required`, aunque la operación remota hubiera sido exitosa.
- Se retiró por completo el flujo de bases locales, ya innecesario tras DB-01/ETL-01: se eliminaron `app/services/bdlocales_sync.py`, `bdlocales_import.py`, `etl_consolidation.py`, `etl_orchestration.py` (sin importadores en la app viva) y los scripts `scripts/import_bdlocales.py`/`inspect_bdlocales.py`.
- Las 8 funciones de escritura de VirtualPOS ahora reconcilian solo `source_records` (staging) y la entidad centralizada correspondiente tras el `GET` de confirmación al proveedor, sin resincronizar el canal completo.
- Se quitaron `virtualpos_db_url`, `toku_db_url` y `payku_db_url` de `app/core/config.py` y las variables `VIRTUALPOS_DB_URL`/`TOKU_DB_URL`/`PAYKU_DB_URL` de `.env`/`.env.example`. `docs/history/migrations/bdlocales-consolidation-closed.md` queda marcado como completado y cerrado.
- `tests/test_virtualpos_writes.py` se actualizó para verificar la reconciliación contra `SourceRecord` en vez de mockear las funciones locales retiradas.

## Operación local 2026-09-16

- PostgreSQL quedó saludable en `localhost:5433`, las migraciones se aplicaron hasta `head` y API FastAPI (`:8000/docs`) y frontend Vite (`:5173`) responden correctamente.

## Actualización 2026-09-17 (dashboard general y TCH)

### UX móvil y despliegue

- Se convirtió el sidebar en un drawer deslizable con botón burger (`☰`) en móvil: `position: fixed; transform: translateX(-100%)` → `.open { transform: translateX(0) }`. El overlay cierra el menú al tocar fuera.
- El frontend se compila (`npm run build`) y se sirve desde FastAPI en `/` vía `StaticFiles`, eliminando los 595 módulos cargados por Vite dev server que saturaban el túnel Cloudflare. El acceso remoto funciona correctamente a través de `trycloudflare.com`.
- Se corrigió el grid de KPI en móvil: `Staging.css` sobreescribía la regla de `App.css`; se agregó la regla `@media (max-width: 800px)` directamente en `Staging.css`.

### Canal TCH — mejoras de KPIs y montos

- `monto_suscripcion` ahora usa `equivalente_pesos` (valor CLP) en lugar de `monto` (siempre nulo en los reportes Excel). Corregido en backend y frontend.
- Se añadieron tarjetas KPI al resumen TCH: **MRR** ($71.478.107), **ARPU** ($7.973), **Churn mensual promedio** (1.8%), **LTV estimado** ($442.944). El churn usa promedio de bajas/mes ÷ subs vigentes en lugar del ratio histórico acumulado (antes 211.3%, incorrecto).
- Las tarjetas principales del resumen TCH (Vigentes, Eliminadas, Total, Transacciones) ahora muestran sus montos CLP secundarios y responden al toggle Cantidad/Monto.
- Las fichas de métricas en todos los canales responden al toggle Cantidad/Monto: en modo Monto, el valor monetario pasa a ser el número principal.
- TCH-06 marcada Completada: se añadió la migración `20260916_0021` con la tabla `tch_recaudacion_mensual`; el resumen TCH usa los controles mensuales oficiales para montos y cantidades de transacciones.

### Dashboard general — consolidación y nuevos gráficos

- Se eliminó el segundo encabezado duplicado ("DASHBOARD GENERAL / Indicadores consolidados"); los controles Cantidad/Monto/Año se integraron en el `hero-panel` del título principal.
- Las tarjetas "Suscripciones vigentes" y "Transacciones" del general ahora muestran su monto CLP: $142.693.178 en subs activas (todos los canales) y $6.553.083.993 en transacciones.
- Se agregó el endpoint `subscriptions.amount` al dashboard general: calcula la suma de `CSub.amount` por canal (VIGENTE/activa) más `TchSuscripcion.equivalente_pesos` para TCH.
- **Bajas mensuales por canal**: nuevo gráfico de panel ancho que muestra `CSub.canceled_at` (VirtualPOS, Toku, Payku) y `TchSuscripcion.fecha_eliminacion` (TCH) agrupadas por canal.
- **Deudas mensuales por canal**: gráfico que consolida `CCharge.charge_date` (online) con el total de intentos TCH (ACEPTADA + RECHAZADA), con filtro **Todas / Pagada / Rechazada**.
- **Transacciones por canal**: gráfico que consolida `CPayment` (online) con `TchRecaudacionMensual` agrupados por canal, con el mismo filtro de estado.
- Ambos gráficos de Deudas y Transacciones incorporan `charge_status` en cada entrada; el helper `applyChargeFilter` pre-agrega las entradas antes de pasarlas al componente de barras.

### Escrituras completadas (WR-VP-04, WR-TK-02, WR-TK-05, WR-TK-06)

- **WR-VP-04** Completada: `DELETE /v3/payment/:uuid` implementado en `VirtualPOSClient`; servicio `cancel_payment` con registro `WriteRun` y ruta `DELETE /api/v1/writes/virtualpos/payments/{id}`.
- **WR-TK-02** Completada: `PUT /invoices/:id` implementado en `TokuClient`; servicio `update_invoice` actualiza el `SourceRecord` correspondiente.
- **WR-TK-05** Completada: `DELETE /invoices/:id` implementado; servicio `delete_invoice` marca el `SourceRecord` como deleted.
- **WR-TK-06** Completada: `DELETE /subscriptions/{id}` implementado; servicio `delete_subscription` marca la suscripción centralizada como deleted.

## Actualización 2026-09-21 (operación consolidada)

- Clientes consolidados muestra RUT, nombre completo, plataformas de origen y suscripciones activas. Permite buscar por RUT, nombre, apellido, plataforma, correo o teléfono y pagina los resultados.
- Suscripciones consolidadas está habilitada en el submenú general con ID, cliente, RUT, plataforma, estado, fechas y monto; permite filtrar y paginar. Excluye `SUSCRIPCION_FALLIDA` de VirtualPOS, `RECHAZADA` de TCH y `register` de Payku.
- Las rutas estáticas de dashboard se registran antes de la ficha dinámica de staging para que `/dashboard/general/clients` y `/dashboard/general/subscriptions` no se interpreten como recursos de proveedor.
- Se documentaron las rutas de consulta consolidada, reportes operativos y reintento por lote de cargos VirtualPOS en `README.md`.

## Mantenimiento 2026-09-21 (rutas directas de proveedores)

- Completada: se retiraron las rutas directas inactivas de Payku y Toku. La aplicación continúa operando mediante sincronización a staging y rutas internas protegidas; los clientes de integración, sincronizadores y escrituras no cambian.
- Verificado: migraciones en `head`, PostgreSQL saludable, frontend compilado y FastAPI respondió `200` en `/` y `/health`.

## Mantenimiento 2026-09-21 (artefactos locales)

- Completada: los logs locales de API, frontend y sincronizaciones se centralizaron en `logs/`, carpeta ignorada por Git.

## Mantenimiento 2026-09-21 (ejemplos)

- Completada: el template Streamlit no productivo se movio de la raiz a `examples/dashboard_referencia.py` y se documento su alcance.

## Mantenimiento 2026-09-25 (servicios locales)

- En curso: se detuvieron los dos procesos `cloudflared` que exponian el frontend local.
- Bloqueada: detener MariaDB, PostgreSQL local y las dos instancias de SQL Server requiere una consola elevada. El contenedor PostgreSQL del CRM en `localhost:5433` permanece saludable y no se modifico.
- Bloqueada: el listener local en `127.0.0.1:8002` pertenece a un proceso no visible desde la sesion actual; requiere privilegios elevados para identificarlo y detenerlo.

## Investigación 2026-09-25 (VirtualPOS: cargos y transacciones)

- Completada: el contrato oficial define `Charge.payment.order.uuid` como la relación verificable entre cobro recurrente y `Payment`. La lista global de `Payment` no documenta `charge_id`.
- Hallazgo: los extractores solo buscan `charge_id`/`charge_uuid` en el payload de `Payment`, por lo que `charge_external_id` está vacío en el 100% de los registros pese a que existe la relación inversa en los cargos.
- Datos locales: se verificaron 39.453 pagos `pagado` asociados exactamente a un cargo `pagado` por UUID (11.517 VP1 y 27.936 VP2). Quedan 5.618 pagos `pagado` sin cargo local coincidente; requieren completar la lectura de cargos y contraste con VirtualPOS antes de clasificarlos como pagos directos.
- Riesgo operativo: el último log local de sincronización de VirtualPOS terminó con una respuesta no JSON mientras procesaba cargos, por lo que no debe usarse para concluir que los cargos locales están completos.
- Patrón confirmado: 5.615 de los 5.618 pagos sin cargo local pertenecen a clientes con una suscripción no activa; 5.393 tienen exactamente una suscripción local, actualmente `cancelada`, y su pago ocurrió en o antes de su cancelación. De esos 5.393, 5.391 apuntan a una suscripción sin ningún cargo local.
- Recurrencia confirmada: 5.318 de 5.615 pagos usan `PAT`; entre los pagos de suscripción no ambigua con pago previo, 3.349 de 3.725 intervalos consecutivos duran 27 a 32 días. Son secuencias mensuales históricas, no un patrón de pagos puntuales.
- Validación de cancelación: no hay pagos sin cargo local posteriores a todas sus fechas de cancelación candidatas (0 VP1, 0 VP2). Tampoco hay cargos `pagado` enlazados a suscripciones `cancelada` cuya fecha de cargo o autorización sea posterior a `canceled_at` (0 de 119 casos). La evidencia disponible descarta que la cancelación esté dejando cobros posteriores.
- Exportación local: `scripts/maintenance/export_virtualpos_unlinked_payments.py` genera `reports/virtualpos_unlinked_payments.csv`, excluida de Git. Incluye UUID de pago, RUT, monto, medio, suscripciones candidatas, fechas de cancelación y una clasificación de evidencia; no incluye datos de tarjeta.
- Inventario de suscripciones sin historial: el mismo exportador genera `reports/virtualpos_subscriptions_without_charge_history.csv` con ID de suscripción, RUT, plataforma, estado, plan y fechas. Contiene 2.760 suscripciones: 798 VP1 y 1.962 VP2; 1.886 `CANCELADA`, 872 `SUSCRIPCION_FALLIDA` y 2 `SUSCRIBIENDO`.
- Prueba de recuperación read-only: cinco muestras representativas de suscripciones canceladas sin cargos locales (dos VP1 y tres VP2, entre registros tempranos, recientes y con mayor cantidad de pagos) devolvieron `E-047` en `GET /v3/suscription/{id}/charges`: el plan asociado ya no existe para el proveedor. No es posible recuperar esos cargos por la ruta disponible; se requiere exportación histórica o soporte de VirtualPOS para reconstruirlos.
- Cobertura por RUT y estado del lote sin cargos: al cruzar exclusivamente las 2.760 suscripciones sin `Charge` local por `plataforma + social_id` contra al menos un `Payment` `pagado`, 1.743 de 1.886 `CANCELADA` tienen pagos (92,4%); 319 de 872 `SUSCRIPCION_FALLIDA`; y ninguna de las 2 `SUSCRIBIENDO`. Este cruce prueba actividad de pago del cliente, pero no asigna un pago a una suscripción concreta cuando el RUT tiene varias.
- Ambigüedad por RUT del lote sin cargos: 819 de 2.760 suscripciones (29,7%) pertenecen a un RUT con más de una suscripción dentro de la misma plataforma. Solo 89 de 1.886 `CANCELADA` están en ese caso (4,7%); la mayor concentración corresponde a `SUSCRIPCION_FALLIDA` (730 de 872).
