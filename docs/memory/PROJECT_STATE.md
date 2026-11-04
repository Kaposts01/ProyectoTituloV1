# Estado del Proyecto

Fecha de actualizacion: 2026-10-28.

> El plan, los sprints, el backlog y el estado de cada tarea viven en [docs/tasks.md](../tasks.md), la fuente única. Este archivo describe el estado técnico y las decisiones del sistema.

## Estado actual

El repositorio contiene un CRM operativo con FastAPI, PostgreSQL, React/Vite, autenticacion, permisos, staging y trazabilidad por canal. VirtualPOS, Toku y Payku se sincronizan desde APIs; TCH se carga desde reportes Excel. La vision objetivo es un CRM para fundaciones que centralice socios, donantes y suscripciones de multiples fuentes.

## Completado

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

- Plan y tareas en curso: ver [tasks.md](../tasks.md) (Sprint 4: recuperador VP y facturación gestionada, Opción A).
- Core ETL completo y en `master` (migraciones 0027–0033 aplicadas). Migraciones 0032 (`source_status` en `core_charges`) y 0033 (`last_payment_status` en `core_subscriptions`) versionadas y activas.
- ETL fixes aplicados (2026-10-20): `core_vp_etl` mapea `source_status` desde `VpCharge.status`; `core_toku_etl` deriva `last_payment_status` desde la última `TokuInvoice` por `due_date`; `alembic/env.py` registra los 3 modelos webhook stg (check limpio).
- Los dashboards operativos de VirtualPOS, Toku, Payku y TCH tienen paridad de KPIs, distribuciones, altas/bajas, series de suscripciones activas, churn y alertas usando solamente los campos verificables de cada fuente. Toku usa transacciones reales para su comparación con suscripciones; Payku mantiene su límite de cobertura histórica; TCH se basa en su proyección ETL.
- Payku reconoce el identificador histórico `transaction` cuando su payload no trae `id`. La reconstrucción local `scripts/maintenance/backfill_payku_transactions.py` materializa transacciones ya preservadas en `source_records` hacia `p_transactions`; luego el ETL normal las proyecta a `payments`, restaurando los años y la actividad mensual verificables del dashboard.
- Webhooks: el receptor de Toku (HMAC-SHA256, idempotente, WH-02) y el de Payku (token en query, WH-03) están implementados y guardan los eventos en tablas `stg_*_webhook_events`; falta configurar los webhooks en Toku y procesar los eventos (TK-12). VirtualPOS expone callbacks cuya autenticidad permanece `TBD`, por lo que no se implementa receptor hasta verificarla.

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

## Actualizacion 2026-10-25 (cierre Sprint 1 / Sprint 2 en progreso)

- **Legacy desactivado**: `crm_materialization.py` queda desactivado, no borrado. `virtualpos_sync.py` consolida mediante `consolidate_to_centralized`; `POST /etl/run` devuelve HTTP 410. Pendiente decidir el borrado definitivo tras verificar que no afecta. En `virtualpos_sync.py` la consolidación sigue condicionada a `if materialize_ids`.
- **SYNC-GAP-01 resuelto**: `platform` de VirtualPOS solo puede ser `virtualpos1` o `virtualpos2`. `_VP_PLATFORMS` en `app/services/channel_store.py` lo define y `channel_consolidation.py` lo valida; un valor desconocido se omite con warning.
- **source_record_id (SYNC-GAP-03, parcial)**: VirtualPOS, Toku y Payku lo rellenan mediante `_source_record_ids` / `_link_source_records`; la segunda pasada usa COALESCE y no borra vínculos. TCH sigue en NULL. El backfill `scripts/maintenance/backfill_source_record_ids.py` tiene dry-run por defecto y `--apply` escribe; aún no se ha ejecutado.
- **SYNC-GAP-05 documentado**: las tablas centralizadas son una copia derivada de los canales y se sobrescriben en cada corrida. No hay ruta de edición manual.
- **KPIs (Sprint 2, en progreso)**: componentes KpiCard, ChannelChart y ChannelKpiStrip en `frontend/src/components`; tipos y notas en `features/shared/kpis.ts`; vitest configurado. Backend agrega `kpis.rejected_charges` en los 4 canales. Payku calcula MRR desde la última transacción `success` (cifra sin cambio: 5.339.000). TCH agrega `kpis.recaudo_mensual`. Toku filtra chargeable en el churn.
- **Bloqueo externo**: BLQ-TK-01 (Toku `flow_name`) sigue sin sprint asignado. Bloquea alta de socios y cambio de tarjeta, no los KPIs.

## Actualizacion 2026-10-26 (Sprint 2 casi completo)

- **TK-10 completada**: filtro y orden global por estado secundario Toku antes de paginar; 6 tests con offset>0 en `tests/test_staging_api.py` (Toku y VirtualPOS). **SYNC-GAP-02** caracterizado (9 tests en `tests/test_etl_tch.py`; decisión de negocio pendiente). **SYNC-GAP-04** mitigado (49 tests en `tests/test_sync_gap04_payload_shapes.py`; log `_log_null_relations`). **FE-03** completada. **KPI-02..04** completadas; **KPI-01** pendiente de verificación contra VirtualPOS staging.
- **Sprint 3 (en progreso)**: CHART-01..04 completadas en código con ChannelChart (verificación de cifras y apariencia pendiente; "Crecimiento real mensual" y "Churn %" siguen con componentes antiguos). UI-20 y UI-21 completadas en código: sidebar corregida y `GET /api/v1/sync-runs/health` con puntos de salud; falta verificación visual en navegador y contraste.

## Actualizacion 2026-10-28 (Opcion A, Toku y estado de la rama)

- **Facturación gestionada (Opción A, BILL-01 a BILL-08)** en código: permisos `billing_changes.request/approve/view` y `billing_policy.manage` más rol `ejecutivo` de solo lectura (migración 0037); modelos de solicitudes de cambio de cobro con índice único parcial de una solicitud abierta por suscripción (migración 0038); cálculo puro del plan; aplicación con compensación, lock por suscripción y verificación final; API `/billing`; bandeja y política en `/general/cambios-de-cobro`; chequeo diario de renovación de solo lectura y expiración de solicitudes (jobs `billing_renewal_check` 03:00 y `billing_expire_requests` cada hora); pestaña Renovaciones. Aprueba solo `admin` (autoaprobación auditada); doble aprobación implementada y apagada. Diseño: `docs/designs/facturacion-gestionada-escenarios.md`.
- **Migraciones**: head `20261028_0038`. Las migraciones 0037 y 0038 aún **no están aplicadas** a las bases `crm` y `crm_sandbox`; hay que correr `alembic upgrade head` y `scripts/maintenance/seed_roles.py` en cada ambiente.
- **Roles** en el código: `admin`, `coordinador`, `jefatura`, `soporte` y `ejecutivo`. `soporte` y `ejecutivo` tienen `billing_changes.view`; falta crear usuarios por ambiente.
- **VirtualPOS**: `vp_current_amount` calcula «hoy» en hora de Chile (413a740).
- **Toku**: guardas duras de escritura fuera de producción (e6202a7). Mediciones del 2026-10-28 con solo lecturas: el sandbox es una organización aparte, con otras llaves y la misma URL base, sin transacciones ni medios de pago; la API no entrega `status` de cliente ni de suscripción, `remaining_collection_attempts` ni `external_id` de suscripción. Pendientes TK-12 a TK-15.
- **Pruebas** al cierre de la sesión: backend 844 y frontend 179 pasan; `ruff` limpio.
- **Rama**: `sprint-4/recuperador-vp` con 11 commits locales sin subir; no hay PR abierto.

## Actualizacion 2026-10-27 (suite de contrato VirtualPOS)

- **Suite de contrato** en `tests_contract/` (excluida por defecto de pytest; comando y guardas en [tests_contract/README.md](../../tests_contract/README.md)). Ejecutada contra el sandbox (cuenta 1): 29 afirmaciones, 12 discrepancias; informe `reports/contract/virtualpos/drift-20261027-122121.md` (no versionado).
- **Hallazgos principales**: los errores de negocio (E-059, E-078, E-079) llegan con HTTP 200 y `status: NOK`; `internal_code` no es idempotente (dos POST con el mismo código crearon dos cargos, sin E-086), por lo que el CRM debe deduplicar consultando los cargos antes de crear; los filtros `charge_date_from`/`charge_date_to` de cargos se ignoran; `limit=101` y `page=0` no dan error (comportamiento no documentado).
- V-1 resuelta: `charge_program[]` del listado de suscripciones trae el programa completo. V-2, V-3 y V-4 siguen pendientes (requieren tarjeta y cobro real).

## Actualizacion 2026-10-27 (V-5 en sandbox, WR-VP-05)

- **V-5 ejecutada en sandbox**: `POST /v3/charge` fue aceptado sobre una suscripcion activa de plan `MONTO_FIJO` (sin E-113). Esto contradice la inferencia de charges.md y de workflows/cambiar-monto.md (`MONTO_VARIABLE`). Detalle en `integrations/virtualpos/VALIDATION-PLAN.md`.
- Sin resolver: solo sandbox; no se probo con cargos automaticos futuros ya programados (posible cobro duplicado); no se decidio la continuidad de cobros mensuales si se cancelan todos los cargos futuros; no se probo el cobro real sobre la tarjeta.
- La bandera `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` puede activarse en sandbox; en produccion sigue apagada hasta una prueba controlada.

## Actualizacion 2026-10-26/27 (Sprint 4 activo: Recuperador VP)

- **REC-03 en código**: recuperador VirtualPOS con motivos desde `latest_rejection_*`, filtros antes de paginar y CSV trazable (auditado en `write_runs`). Falta verificación visual y descarga real del CSV.
- **Decisión `monto_vigente`**: monto de una suscripción VirtualPOS = último cobro pagado o procesando con fecha ≤ hoy; si no hay, monto de la suscripción y luego el del plan. Lo usan ETL, KPIs (MRR, ARPU, LTV) y recuperador. Impacto en base local: MRR 63.991.386 → 64.087.821 (+0,15%). No registrada aún como ADR.
- **Decisión planes fijos (WR-VP-05)**: `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` apagada por defecto. Cambiar monto mediante cancelación de cargos futuros y nuevo cargo quedó validado solo en sandbox (V-5, 2026-10-27: `POST /v3/charge` aceptado en plan MONTO_FIJO, sin E-113). Producción sigue sin validar: la bandera permanece apagada allí hasta una prueba controlada.
- **Ambientes (ENV-01, en curso)**: `APP_ENV` (`production`/`sandbox`/`qa`) selecciona las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL` del único `.env` (no existen `.env.sandbox` ni `.env.qa` en el backend); guarda de arranque contra URLs y credenciales de otro ambiente; canal sin URL de sandbox deshabilitado; escrituras apagadas por defecto. Toku usa el mismo host con otras llaves; Payku sin credenciales de sandbox.
- **PK-05 pendiente**: bloqueada por VAL-PK-01 (Q-06, Q-08, Q-11, Q-27, Q-29).

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

## Deuda tecnica conocida

La lista priorizada está en [Technical Debt](../../knowledge/08%20-%20Roadmap/Technical%20Debt.md) y el resumen en [tasks.md](../tasks.md#6-deuda-técnica). Hechos vigentes que complementan esa lista:

- 22 workflows de proveedor parcialmente implementados con riesgos de producción documentados en `docs/integrations/*/REVIEW.md`. Toku `started_at` usa `anchor` (próximo cobro) por ausencia de fecha real de inicio en la API.
- BLQ-TK-01: Toku ENROLLMENT bloqueado hasta que soporte configure `flow_name`; la alternativa Customer Portal no es apta para producción.
- `ClientMatchCandidate` acumula candidatos sin flujo operativo de resolución o merge (CORE-04 solo revisa).
- `ruff.toml` establece el conjunto de reglas activo; E501 excluido por las líneas largas de migraciones históricas.
- Documentos históricos de arquitectura y ETL son antecedentes y pueden no reflejar la arquitectura vigente.
- Auditoría 2026-10-01: Payku no certifica cobertura histórica de transacciones y TCH requiere ampliar su cobertura ETL más allá de la suite focalizada inicial; estos límites deben considerarse al usar sus métricas.
- Auditoría 2026-10-04: VirtualPOS conserva los cargos embebidos en suscripciones. Las transacciones locales conservan RUT de cliente pero no un identificador verificable de cargo o suscripción; se muestran por cliente y cuenta sin asignarlas individualmente. El ETL TCH sanea Raw y su modo `full` es atómico. VirtualPOS materializa solo los `source_records` que cambiaron durante la sincronización.
- El frontend ya no concentra su estado en `App.tsx` (FE-01 y FE-02 cerradas); queda deuda de pruebas de cobertura frontend.
- DB-02 y DB-03: la instancia efectiva es PostgreSQL 17 en `localhost:5433/crm`, con volumen persistente `crm_projectotitulo_postgres_data`; `alembic check` no detecta operaciones pendientes.

## Convencion terminologica

En SynkmetriX se utilizara el termino modelo centralizado en lugar de modelo canonico.
