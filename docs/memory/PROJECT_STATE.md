# Estado del Proyecto

Fecha de actualizacion: 2026-10-21.

## Estado actual

El repositorio contiene un CRM operativo con FastAPI, PostgreSQL, React/Vite, autenticacion, permisos, staging y trazabilidad por canal. VirtualPOS, Toku y Payku se sincronizan desde APIs; TCH se carga desde reportes Excel. La vision objetivo es un CRM para fundaciones que centralice socios, donantes y suscripciones de multiples fuentes.

## Completado

- DASH-02 (2026-10-20): dashboard general incorpora KPI mensuales y graficos de ingresos por canal, acumulado/meta/proyeccion, base y movimientos; meta de analisis opcional sin persistencia, tablas accesibles y cobertura explicita. Evita doble conteo TCH y datos futuros/monedas no verificadas. 304 pruebas Python, 4 TypeScript, Ruff y build pasan; revisado en navegador y conciliado control TCH. Advertencias previas conservadas. [Evidencia](../quality/dashboard-kpis-2026-10-20.md).

- DATA-01 (2026-10-20): atributos Core compartidos se conservan por cliente y fuente; migracion 0032 aplicada a crm local con respaldo. VirtualPOS no elige primer cliente ante RUT compartido y prioriza ID externo explicito. 296 pruebas pasan, Ruff y Alembic check pasan. No hay backfill ni reasignacion de asociaciones existentes. Ver [informe](../quality/data-integrity-2026-10-20.md).

- REL-01 (2026-10-20, cambios locales): reparados imports de scripts Toku/VirtualPOS y despacho de rutas Core all/detect-matches. Scheduler y full-sync ya no registran completed cuando falla un canal o la consolidacion; preservan conteos y canales exitosos. SSE diferencia errores intermedios de terminales y la UI espera el resultado final. 283 pruebas pasan en base aislada, Ruff y build frontend pasan. Persisten limites de Toku, identidad, concurrencia entre procesos y avisos frontend; no se certifican proveedores reales ni prueba visual.

- Skills Codex por stack creadas y evaluadas 2026-10-20: nueve paquetes de repositorio en `.agents/skills/`, con instrucciones, metadatos UI y referencias. Cubren backend/API, PostgreSQL/ORM, React/TypeScript, dashboards, ETL, integraciones HTTPX, scheduler/SSE, calidad y entorno/CI. Pasan 37 pruebas estructurales; 27 revisiones offline cumplen los criterios cualitativos y 12 selecciones basadas solo en metadatos coinciden con el alcance esperado. Las nueve aparecen en el catalogo activo; no se certifican ejecucion funcional del CRM, activacion nativa en sesion limpia ni mejora causal del modelo. Informe en `docs/quality/skills-evaluation-2026-10-20.md`. Las skills de gobierno en `.opencode/skills/` se conservan sin duplicacion.

- Entorno local verificado 2026-10-20: con autorizacion del usuario se preparo PostgreSQL 18 nativo aislado en `.local/postgres18/data` y `127.0.0.1:5433`, como alternativa local al Docker bloqueado por virtualizacion. La base nueva `crm` esta en Alembic `20261007_0028`, con administrador local. API en `127.0.0.1:8000` y Vite en `127.0.0.1:5173` responden correctamente. Secretos solo en `.env`. El entorno usa Python 3.14.7; `.python-version` conserva 3.14.5. Esta verificacion no certifica datos ni despliegues anteriores.
- TCH local verificado 2026-10-20: la proyeccion contiene 10.533 clientes, 10.547 suscripciones y 133.532 transacciones. Las fichas y estados de las suscripciones coinciden exactamente con la transformacion del reporte de septiembre 2026 proporcionado por el usuario. Los resumenes TCH y general responden correctamente. No se repitio la importacion ya realizada; esto no certifica cobertura historica completa ni comparacion campo a campo de todas las entidades.
- Carga API local verificada 2026-10-20: VirtualPOS cuenta 1 Sandbox sincronizo y consolido 25 clientes, 8 planes, 15 suscripciones, 1.403 cargos y 38 pagos. Toku materializo 30 clientes, 31 suscripciones y 35 facturas; `/organization/payments` respondio 404 y una corrida acotada completo los otros cinco recursos dejando la exclusion explicita en `sync_runs`. No se certifica cobertura de pagos Toku ni carga completa al Core financiero. Payku y VP2 permanecen fuera de esta carga; escrituras de proveedores deshabilitadas.

- Staging saneado e idempotente para canales API.
- Tablas y vistas operativas por canal, dashboards y reportes existentes.
- Autenticacion, permisos y registro de sincronizaciones y escrituras autorizadas.
- Administracion de usuarios y roles: usuarios con multiples roles se pueden crear, editar, desactivar y restablecer su contrasena; los roles y sus permisos se administran con permisos y CSRF.
- El ultimo usuario activo con rol `admin` no puede ser desactivado ni perder ese rol desde la administracion.
- El Recuperador VirtualPOS resuelve clientes de cargos rechazados mediante la relacion trazable cargo-suscripcion-cliente y usa el nombre saneado del payload de suscripcion solo cuando no existe cliente materializado. Muestra cargos rechazados y el historial completo de solicitudes de reintento, incluidos rechazos inmediatos, con sus resultados conciliados. Los motivos ausentes se exponen como no informados por VirtualPOS y cada envio confirma exitos y fallos.
- Vault documental de Obsidian y documentacion conceptual inicial.
- La estructura versionada separa scripts operativos, mantenimiento y diagnostico; la documentacion historica y las colecciones Postman tienen ubicaciones explicitas; los insumos locales se excluyen bajo `data/local/` y `.local/`.
- Skill local `project-memory` disponible para gestionar memoria persistente y ADRs compactos; su descubrimiento fue confirmado en una sesion reiniciada de OpenCode.
- Skill local `data-modeling` disponible para disenar y revisar el modelo centralizado; su descubrimiento, ruta y frontmatter fueron confirmados en una nueva sesion de OpenCode.
- Skill local `provider-integration` disponible para estandarizar connectors, Raw/STG, contratos y seguridad de proveedores; su descubrimiento fue confirmado en OpenCode.
- Definiciones locales de los subagentes `obsidian-vault` y `adr-governance` disponibles para mantener el vault y gobernar ADRs sin redefinir las fuentes de verdad del proyecto.
- La configuracion y skills de OpenCode son parte versionable del proyecto; los ajustes especificos de Claude permanecen locales y no definen reglas del proyecto.
- OpenCode mantiene la integracion compartida de Context7; Claude puede usar una configuracion local complementaria bajo las reglas de `AGENTS.md`.
- El vault de Obsidian se abre desde la raiz del repositorio para incluir `docs/` y `knowledge/`; `.obsidian/` conserva solo preferencias locales.
- El frontend usa el proxy de Vite hacia la API local en `127.0.0.1:8000`; el healthcheck de PostgreSQL usa las variables de Compose.
- Python 3.14.5 y sus dependencias quedan bloqueados en `.python-version` y `requirements.lock`; existe CI para backend y frontend.
- El resumen operativo de VirtualPOS prioriza recursos, indicadores, estados y tendencias. Su estado de sincronizacion proviene del ultimo `SyncRun` de sus dos cuentas y no presenta una consolidacion pendiente como hecho.
- Los dashboards de frontend usan caché en memoria con TTL de cinco minutos y deduplicación de solicitudes; la navegación reutiliza resultados válidos y las sincronizaciones invalidan la caché. TCH normaliza sus colecciones de resumen antes del render para tolerar series ausentes; el diferimiento de gráficos mensuales queda pendiente de una extracción segura de vistas.
- La SPA usa rutas navegables para la operación consolidada, canales, administración, perfil y fichas de VirtualPOS, Toku y Payku. Las fichas de proveedor usan identificadores externos; las fichas que hoy dependen de RUT conservan navegación interna hasta disponer de identificadores no personales. La URL se sincroniza con la vista, historial y permisos visibles sin cambiar contratos API ni controles de FastAPI.
- Los listados consolidado y de proveedores conservan su estado operativo seguro en query parameters: paginación, campo seleccionado, estado, orden y cuenta VirtualPOS. Los términos de búsqueda no se incluyen para evitar exponer atributos personales en URL.
- Los listados VirtualPOS permiten filtros simultáneos con AND por columna, coincidencia parcial para texto, rangos explícitos de monto y fecha, y orden tipado. Las tablas relacionadas en fichas permiten la misma exploración sobre los registros cargados.
- Las fichas de suscripción TCH usan `numero_ficha` de DUES en la ruta. Es un identificador único de la proyección TCH y no expone atributos personales.
- Las tablas y fichas VirtualPOS enriquecen planes, clientes, suscripciones, cargos y transacciones desde relaciones trazables por cuenta e identificador externo. Las transacciones se vinculan al cliente por RUT y cuenta; los datos locales actuales no permiten asignarlas individualmente a cargos o suscripciones.
- Los cuatro ETL Core (TCH, Toku, Payku, VirtualPOS) materializan tablas de proveedor hacia entidades Layer 3 (`core_clients`, `core_subscriptions`, `core_charges`, `core_payments`, `core_client_attributes`). Son idempotentes y usables como endpoints REST (`POST /etl/core/{provider}` y `POST /etl/core/all`) o directamente como servicios Python. TCH materializa 1.47M pagos; Toku usa stubs `status='deleted_at_source'` para 112 suscripciones eliminadas en origen; Payku vincula directamente transacciones a suscripciones; VirtualPOS usa índice de RUT para vincular pagos con ambigüedad controlada.

## En progreso

- Tareas operativas registradas en [tasks.md](../tasks.md), incluidas Payku, Toku y un flujo de VirtualPOS.
- Core ETL completo y en `master` (migraciones 0027–0033 aplicadas). Migraciones 0032 (`source_status` en `core_charges`) y 0033 (`last_payment_status` en `core_subscriptions`) versionadas y activas.
- ETL fixes aplicados (2026-10-20): `core_vp_etl` mapea `source_status` desde `VpCharge.status`; `core_toku_etl` deriva `last_payment_status` desde la última `TokuInvoice` por `due_date`; `alembic/env.py` registra los 3 modelos webhook stg (check limpio).
- Los dashboards operativos de VirtualPOS, Toku, Payku y TCH tienen paridad de KPIs, distribuciones, altas/bajas, series de suscripciones activas, churn y alertas usando solamente los campos verificables de cada fuente. Toku usa transacciones reales para su comparación con suscripciones; Payku mantiene su límite de cobertura histórica; TCH se basa en su proyección ETL.
- Payku reconoce el identificador histórico `transaction` cuando su payload no trae `id`. La reconstrucción local `scripts/maintenance/backfill_payku_transactions.py` materializa transacciones ya preservadas en `source_records` hacia `p_transactions`; luego el ETL normal las proyecta a `payments`, restaurando los años y la actividad mensual verificables del dashboard.
- La auditoria de webhooks confirma que Toku documenta firma HMAC e identificador de entrega; falta implementar su receptor idempotente con una URL HTTPS temporal. VirtualPOS y Payku exponen callbacks, pero su autenticidad permanece `TBD`, por lo que no se implementan receptores hasta verificarla.

## Pendiente

- Definir contrato de liquidaciones, taxonomia comun y gobierno de datos personales.
- Migrar lecturas del frontend hacia el Core y deprecar gradualmente las proyecciones por canal sin romper contratos vigentes.
- Evaluar analitica predictiva en una fase posterior.

## Bloqueos

- Payku no permite recuperar de forma confiable cierto historial de transacciones.
- VirtualPOS puede tener cargos historicos incompletos para algunas suscripciones.

## Decisiones aceptadas

- **Status: Accepted** PostgreSQL es la fuente central de verdad.
- **Status: Accepted** Cada proveedor tiene staging independiente y trazable.
- **Status: Accepted** Ningun proveedor escribe directamente en tablas Core.
- **Status: Accepted** Credenciales y API keys no se almacenan en Git.
- **Status: Accepted** Las integraciones deben poder reprocesarse.
- **Status: Accepted** La identidad centralizada usa CLIENTE con identificador interno, identidades externas trazables, matching conservador y merge reversible ([ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md)).

## Decisiones TBD

- **Status: TBD** Esquema fisico, umbrales de matching y gobierno de atributos personales para la identidad centralizada.
- **Status: TBD** Contrato de liquidaciones y reglas financieras transversales.
- **Status: TBD** Gobierno de atributos personales, retencion y rectificacion.
- **Status: TBD** Taxonomia comun de estados, montos, monedas y periodicidad.

## Actualizacion 2026-10-21 (sesion iterativa)

- **RISK-VP-02 (267fd47)**: `create_subscription` comprueba `VpSubscription` con status ACTIVA/SUSCRIBIENDO antes de llamar al proveedor. HTTP 409 si hay duplicado.
- **RISK-VP-01 (df76bc5)**: `retry_charge` obtiene `payment.order.uuid`, consulta `/v3/payment/{uuid}/attempts` y clasifica el motivo. CAMBIO_TARJETA y DIFERIR lanzan `RetryBlockedError` (HTTP 409) sin llamar al proveedor. Añade `get_payment_attempts()` al cliente VP.
- **RISK-TK-01 (f2f7ab2)**: `delete_subscription` anula invoices impagas (`unpaid`, `partially_paid`) antes del DELETE. Las `in_progress` se omiten con warning. Añade `list_subscription_invoices()` al TokuClient.
- **ETL-03 (1ecbf3a)**: `CoreCharge.subscription_id` es ahora nullable. Migración 0034 aplicada. El ETL VP ya no descarta cargos sin suscripción padre; los inserta con `subscription_id=NULL`.
- **WH-02/WH-03**: receptores webhook Toku (HMAC-SHA256, 11 tests) y Payku (token query, 10 tests) implementados y registrados en `main.py`.
- **ETL-04 (41bbdbe)**: `core_tch_etl` ahora deriva `last_payment_status` desde la última `TchTransaccion` por `numero_ficha`, análogo a Toku.
- **VP-28 (f14d51e)**: `_enrich_charges_with_rejections()` en `core_vp_etl` usa `VpPayment.charge_external_id` para poblar `CoreCharge.latest_rejection_*` desde el payload rechazado más reciente.
- **fix Payku (a3791c3)**: `channel_consolidation` usa `payload.get("end")` como fallback para `canceled_at` cuando no hay status-log; corrige test pre-existente fallido.
- **test VP (8bb5704)**: whitelist de operaciones aprobadas del cliente VP actualizada con `get_payment_attempts`.
- Suite completa: 229 tests pasan (2 tests de staging_api lentos incluidos).
- **CORE-04 (5ffc81e)**: API de revisión `ClientMatchCandidate` (ADR-001): endpoints GET lista/detalle, POST review (confirmed/rejected). Permisos `core.identity.read/review`. Sin merge automático.

## Actualizacion 2026-10-21 (tercera sesion — hallazgos /review)

- **RISK-VP-02 upgrade**: se agregó índice único parcial `uq_vp_sub_active_plan_client` en `vp_subscriptions(platform, plan_external_id, client_social_id) WHERE status IN ('ACTIVA', 'SUSCRIBIENDO')` (migración 0036). `create_subscription` captura `IntegrityError` y retorna `DuplicateSubscriptionError` (HTTP 409). Cubre la condición de carrera entre el SELECT de antiduplicado y la llamada al proveedor.
- **tests `_classify_rejection`**: 52 tests unitarios en `tests/test_classify_rejection.py` cubren todos los code sets (`_CARD_CODES`, `_MERCHANT_CODES`, `_RETRY_CODES`, `_RETRY_ONCE_CODES`), keywords y escalación por `prior_retries`.
- **design fix `AutomaticReport`**: `AlertRow` reemplaza `borderLeft: 4px solid` por `background: rgba(...)` tint, eliminando la violación de DESIGN.md L177 (sin sombras de borde lateral en cards).
- **N+1 fix `core_vp_etl`**: `_enrich_charges_with_rejections` reemplaza el `db.get()` en loop por un SELECT batch con `IN` sobre los IDs de `CoreCharge` necesarios.
- Suite: 247 tests pasan.

## Actualizacion 2026-10-21 (segunda sesion iterativa)

- **OPS-08 (f3e3f92)**: `_records_from_response({})` retorna `[]` en lugar de ValueError; VP trata dict vacío como página vacía y termina paginación limpiamente. 2 tests nuevos.
- **VP-13 (bcf1d47)**: scheduler completo — job cron 02:00 ya registrado; nuevo job `retry_failed_channels` (04:00) reintenta canales fallidos del último EtlRun. `channels_failed ARRAY(String)` añadido a EtlRun (migración 0035). `sync_all_channels` puebla el campo.
- **FE-01 (8d490e8)**: refactor parcial App.tsx (7120→6730 líneas): `api.ts` (funciones HTTP + csrfToken/setCsrfToken), `navigation.ts` (providerGroups, resourcePermission), `components/Sidebar.tsx`, `hooks.ts` (useDebouncedValue) extraídos. TypeScript y build OK.
- **DEV-04 (8cab09c)**: CI en verde — ruff I001+BLE001 en 4 tests corregidos; test de envelope VP actualizado (OPS-08); `ProviderSection` exportada desde routes.ts; frontend build+lint pasan. Suite: 235 tests pasan.

## Deuda tecnica conocida (actualizada 2026-10-20)

- Auditoria 2026-10-20 (equipo): `CoreCharge.subscription_id` NOT NULL bloquea cargos sin suscripcion padre identificada — riesgo de perdida silenciosa durante ETL (CORE-02 a revisar). `ClientMatchCandidate` acumula candidatos sin flujo de resolucion/merge operativo (CORE-04 pendiente). 22 workflows de proveedor parcialmente implementados con riesgos en produccion documentados en `docs/integrations/*/REVIEW.md`. Toku `started_at` usa `anchor` (proximo cobro) por ausencia de fecha real de inicio en la API.
- Receptor webhook Toku (WH-01): firma HMAC documentada pero sin endpoint ni tabla `stg_toku_webhook_events` activa — altas de socios Toku no tienen confirmacion automatica de inscripcion de medio de pago.
- BLQ-TK-01: Toku ENROLLMENT bloqueado hasta que soporte configure `flow_name`; alternativa Customer Portal no apta para produccion.

## Deuda tecnica conocida

- Correcciones locales sobre master 4604258 (2026-10-20): 268 pruebas pasan en PostgreSQL aislado; Ruff y alembic check pasan. Corregidos imports de metadata webhooks, fixture transaccional y prueba Payku con evidencia de transiciones. CI incluye alembic check. Base operativa respaldada y actualizada a 0031; login, dashboard y logout responden 200. Persisten 11 advertencias frontend, bundle grande y deprecacion Starlette/httpx. Ver [informe](../quality/update-validation-2026-10-20.md).

- CI parcialmente saneado en `feature/core-centralizado`: `ruff check app tests alembic scripts` pasa limpio; `pytest` tiene 3 fallos pre-existentes no relacionados con el Core ETL (2 en Toku sync mock, 1 en Payku consolidación histórica).
- `ruff.toml` establece el conjunto de reglas activo del proyecto; E501 excluido explícitamente (líneas largas en migraciones históricas por convención).
- Documentos historicos de arquitectura y ETL son antecedentes y pueden no reflejar la arquitectura vigente.
- Auditoria 2026-10-01: Payku no certifica cobertura historica de transacciones y TCH requiere ampliar su cobertura ETL mas alla de la suite focalizada inicial. Estos limites deben considerarse al usar sus metricas como evidencia completa.
- El frontend concentra estado, carga de datos, dashboards y exploradores en `frontend/src/App.tsx`. La resolución de rutas se extrajo a `frontend/src/routes.ts` y las alertas operativas a `frontend/src/features/dashboard/OperationalAlerts.tsx`; la modularización restante debe preservar permisos y contratos API por canal.
- Auditoria 2026-10-04: VirtualPOS conserva los cargos embebidos en suscripciones. Las transacciones locales conservan RUT de cliente, pero no un identificador verificable de cargo o suscripción; se muestran por cliente y cuenta sin asignarlas individualmente. Payku sincroniza transacciones embebidas, sin certificar cobertura historica. El ETL TCH sanea Raw y su modo `full` es atomico; su suite focalizada inicial esta disponible.
- VirtualPOS materializa solo los `source_records` que cambiaron durante la sincronizacion. Antes releia y rematerializaba todo el historial de la plataforma, lo que degradaba las sincronizaciones y bloqueaba sus pruebas contra bases con datos reales.
- DB-02 y DB-03 confirmadas: la instancia efectiva es PostgreSQL 17 en `localhost:5433/crm`, persiste en `crm_projectotitulo_postgres_data` y esta en Alembic `20261001_0023` (`head`). La migracion reconcilio imports, metadata e indices; `alembic check` no detecta operaciones pendientes y las estadisticas TCH se actualizaron.

## Convencion terminologica

En SynkmetriX se utilizara el termino modelo centralizado en lugar de modelo canonico.

## Entrega sprint-5 (2026-10-29)

Integracion sobre master 4f06970 en rama independiente `sprint-5/estabilizacion-dashboard`, conservando la estabilizacion original. Conflictos resueltos; atributos pasan a revision nueva 20261029_0037 por colision de las dos 0032. 374 pruebas Python, 4 frontend, Ruff, build y metadata pasan en base aislada. Instalacion desde cero/CI backend bloqueados por error historico `op.Column` en 0035. Base operativa no modificada; su antigua revision local requiere reconciliacion antes de migrar. [Evidencia](../quality/sprint-5-delivery-2026-10-29.md).
