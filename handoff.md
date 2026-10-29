# Handoff: CRM SynkmetriX (sesiones del 26 al 29 de octubre de 2026)

Documento para quien retome el trabajo (persona o Claude). Léelo completo antes de tocar nada. No contiene secretos: las variables de entorno aparecen solo por nombre y las cifras de datos son agregadas (sin datos personales).

> **El plan y el estado de cada tarea viven en [`docs/tasks.md`](docs/tasks.md), la fuente única de verdad.** Este documento conserva lo que no cabe allí: las reglas de trabajo, cómo levantar y verificar el entorno, el estado real de cada ambiente, cómo funciona lo construido, los hallazgos, los incidentes, los errores cometidos y las preferencias del usuario. Actualizado el 2026-10-29 (reescrito por completo; la versión anterior era del 28).

## Índice

1. Estado en una mirada
2. Reglas de trabajo (leer primero)
3. Cómo levantar, probar y verificar
4. Estado real de cada ambiente
5. Lo que se hizo, por sprint y por línea de trabajo
6. Cómo funciona la Opción A (cambios de cobro de VirtualPOS)
7. Toku: sandbox, guardas e importador de reportes
8. Revisión visual con capturas (Playwright) y ciclo de pruebas en sandbox
9. Hallazgos sobre VirtualPOS (medidos)
10. Decisiones de negocio del usuario (vigentes)
11. Decisiones abiertas
12. Pendientes y roadmap
13. Incidentes y errores cometidos
14. Archivos y documentos clave
15. Archivos sin versionar que NO son nuestros
16. Datos de prueba que quedaron en los sandboxes
17. Cómo trabajar con el usuario
18. Primeros pasos recomendados para quien retome

## 1. Estado en una mirada

| Tema | Estado |
|---|---|
| Plan y estado detallado | [`docs/tasks.md`](docs/tasks.md): tablero, sprints, backlog por área, bloqueos y decisiones (318 IDs únicos) |
| Rama | `sprint-4/recuperador-vp` (cada rama de sprint contiene a la anterior: `sprint-0/onboarding` a `sprint-4/recuperador-vp`). **Subida al remoto como respaldo el 2026-10-29, sin PR.** Abrir PR solo cuando el usuario lo pida. `master` local está 1 commit adelante de `origin/master` (plan de sprints antiguo) y no se subió |
| Pruebas al cierre | Backend 1185 pasan y 1 se omite (`pytest -q`, base `crm_test`; la omitida es la prueba de rendimiento, con `TOKU_PERF_TEST=1`). Frontend 409 pasan (`npm test`). `npm run build` (incluye `tsc -b`) y `npm run lint` sin errores (19 advertencias preexistentes). `ruff` limpio. Contrato VirtualPOS: 17 pruebas, excluidas por defecto |
| Migraciones | Head del código `20261028_0041`. Aplicadas en `crm_sandbox` (por el orquestador, con aviso) y en `crm` **por accidente** (ver incidente, sección 13) |
| Sprint 4 | En curso. Completos en código: REC-03, Opción A (BILL-01 a BILL-08), revisión independiente con sus tres tandas de arreglos (BILL-17, BILL-19, BILL-20), guardas de escritura de Toku, importador de reportes de Toku TK-17 y TK-18, revisión visual con tres tandas (UI-22 a UI-27). Falta, entre otros: BILL-09 a BILL-16, BILL-18 (espera DEC-30), BILL-21/22, TK-19 a TK-22, PK-05 |
| Sprints 5 y 6 | Planificados. Sprint 5 (recuperador general) espera TK-20; Sprint 6 (infraestructura) espera DEC-11 y DEC-12 |
| Sprint de gráficos VIZ | Registrado (VIZ-01 a VIZ-12, 39 a 55 h de IA según estimación); espera 7 decisiones del usuario (DEC-34 a DEC-40) |
| Bloqueado por terceros o por el usuario | Soporte de Payku (sandbox y preguntas Q-xx); respuesta de Toku sobre `flow_name`; tarjetas de rechazo para pruebas; DEC-30 (ventana de 31 días); definir `TOKU_REPORT_HASH_PEPPER` y exportar un reporte de Deudas de Toku nuevo para la carga real |

## 2. Reglas de trabajo (leer primero)

1. **Nunca mostrar ni copiar valores del `.env`.** Leer solo nombres de variables. Para modificarlo, scripts que no impriman nada. Existe una guarda de arranque que compara credenciales de sandbox con las de producción.
2. **Un solo `.env`.** No existe `.env.sandbox` (solo `frontend/.env.sandbox`, sin secretos: puerto y proxy de Vite). Con `APP_ENV=sandbox` la app usa **solo** las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL`. **`APP_ENV=development`, que es el valor actual del `.env`, equivale a producción** (`is_production` es verdadero y las guardas de sandbox no corren). Un valor desconocido de `APP_ENV` falla al arrancar.
3. **`crm` NO es el sandbox.** `crm` es la base local con datos reales de producción; el sandbox es `crm_sandbox` y solo se activa con `$env:APP_ENV='sandbox'` en el proceso. **Fijar `APP_ENV` y cualquier `DATABASE_URL` ANTES de importar `settings`**: `alembic/env.py` y los scripts leen `settings.database_url` al importar.
4. **Regla de oro del usuario: en sandbox sin problema; en producción siempre con el usuario y con más cuidado.** Ante la duda sobre qué ambiente es, se trata como producción (Toku comparte host con producción; `APP_ENV=development` equivale a producción). Está aprobado en el [runbook](docs/operations/sandbox-testing-and-decisions.md) (DEC-27).
5. **Escrituras al proveedor solo en sandbox y solo con variables de proceso**, nunca dejando las banderas encendidas en `.env`: VirtualPOS `VIRTUALPOS_SANDBOX_WRITES_ENABLED=true` y `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN=true`; Toku `TOKU_SANDBOX_WRITES_ENABLED=true` más `TOKU_SANDBOX_ALLOW_WRITES_ARMED=1` (ver sección 7). Producción: todas apagadas.
6. **Ningún agente ejecuta la CLI de Alembic contra ninguna base.** Las migraciones se prueban solo por pytest (`crm_test`). Aplicar migraciones a `crm` lo hace siempre el usuario; a `crm_sandbox` puede hacerlo el orquestador avisando. Además, `alembic/env.py` bloquea todo `downgrade` sobre bases que no terminen en `_test` ni contengan `sandbox` o `qa`, salvo `ALEMBIC_ALLOW_DOWNGRADE=1` en el proceso (`app/db/migration_guard.py`).
7. **Una sola sesión de pytest a la vez.** Todas recrean `crm_test` al arrancar; dos en paralelo producen fallos falsos.
8. **`git add` siempre por ruta.** Nunca `git add .`; hay archivos ajenos sin versionar (sección 15). No hacer push ni abrir PR sin que el usuario lo pida (el push de respaldo de la rama sin PR fue autorizado y registrado como DEC-32). Los mensajes de commit terminan con la línea `Co-Authored-By` que indique la sesión.
9. **Verificar lo que reportan los agentes.** Releer los archivos, correr `ruff`, la suite y el build uno mismo. Varias veces el reporte de un agente fue optimista, incompleto o directamente falso (p. ej. un revisor afirmó que un job no estaba registrado y sí lo estaba).
10. **No inferir el comportamiento del proveedor de su documentación.** Medirlo en el sandbox (la documentación de VirtualPOS se equivocó en 6 puntos; la de Toku no describe tarjetas de prueba).
11. **Datos personales:** ningún dato personal en el repo, en tests, logs, documentos ni en el contexto de un agente. Los reportes descargados de Toku (carpetas `Downloads\Reportes Toku` y `Downloads\CRM_reportes\Toku`) **no se abren** salvo para leer el encabezado y confirmar que la fila leída es de encabezados; el campo `ID Producto` contiene el RUT del socio. `*.xlsx` y `*.xls` están en `.gitignore`.
12. Scripts temporales, capturas y respaldos van fuera del repositorio (carpeta scratchpad de la sesión). No dejar copias de `.env` en el árbol. La cookie de sesión de Playwright (`state.json`) se borra al terminar.
13. **Tipado del frontend:** `npx tsc --noEmit` casi no comprueba nada (el `tsconfig` raíz solo tiene referencias). La verificación real es `npm run build` (`tsc -b`).
14. Al usuario siempre se le dan **alternativas con una recomendación** cuando se le pregunta algo (ver sección 17).

## 3. Cómo levantar, probar y verificar

| Pieza | Puerto | Comando (desde la raíz) |
|---|---|---|
| Backend producción | 8000 | `.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload` |
| Front producción | 5173 | `cd frontend; npm run dev` |
| Backend sandbox | 8001 | `scripts/run_sandbox_backend.ps1` (fija `APP_ENV=sandbox`; **sin recarga automática**) |
| Front sandbox | 5174 | `cd frontend; npm run dev:sandbox` (Vite sirve el código fuente actual) |

- **Los backends no se recargan solos.** El 8000 falló en silencio con `--reload` y el 8001 se lanza sin él. Tras cambios de backend, comprobar `GET /openapi.json` (¿están las rutas nuevas? p. ej. 13 rutas `/api/v1/billing`) o reiniciar a mano. **Reiniciar el backend sandbox invalida la sesión de Playwright** y obliga a iniciar sesión otra vez.
- Al cierre de esta sesión, el backend de **producción local (8000) corre código anterior** (sin las rutas `/billing`); reiniciarlo es decisión del usuario. El backend sandbox (8001) lo reinició el orquestador con el código nuevo, desacoplado de la consola; sus registros están en el scratchpad de la sesión.
- Bases locales, mismo PostgreSQL (puerto 5433): `crm`, `crm_sandbox`, `crm_test` (se destruye y recrea en cada sesión de pytest; no usar para nada más).
- Para correr algo contra el sandbox: `$env:APP_ENV='sandbox'` antes del comando.
- Selector de ambiente (panel Administración): usa `SANDBOX_APP_URL` y `PRODUCTION_APP_URL` (hoy apuntan a `localhost`).
- Backend: `$env:PYTHONPATH='.'; .venv\Scripts\pytest.exe -q`. **Si da `PermissionError` en `tmp_path`** (el directorio temporal por defecto de pytest tiene permisos raros en esta máquina), añadir `--basetemp=<carpeta del scratchpad>`. Lint: `.venv\Scripts\ruff.exe check app tests alembic`.
- Frontend (desde `frontend/`): `npm test`, `npm run build`, `npm run lint`. Para detectar tests intermitentes, correr los archivos tocados 20 veces seguidas.
- Suite de contrato contra el sandbox de VirtualPOS: ver `tests_contract/README.md` (exige `APP_ENV=sandbox`, `CONTRACT_TESTS=1`, `CONTRACT_WRITES=1`, banderas de sandbox y los ids `CONTRACT_VP_SUB_FIXED` / `CONTRACT_VP_SUB_VARIABLE`). Genera `reports/contract/virtualpos/drift-*.md` (ignorado por git).
- Roles en el código: `admin`, `coordinador`, `jefatura`, `soporte` y `ejecutivo` (solo lectura; `soporte` y `ejecutivo` heredan todos los permisos `.view`; `soporte` además puede reintentar cobros y cambiar de ambiente).
- **Particularidades del entorno Windows/PowerShell** (aprendidas a golpes):
  - El validador de comandos se confunde con ciertos patrones y los bloquea **sin ejecutar nada**: `Remove-Item` con rutas que empiezan por `C:`, expresiones regulares con `\d`, `\.` o `/me$` dentro del comando, y rutas entre comillas con espacios (`C:\Program Files`). Soluciones: usar `[System.IO.File]::Delete($ruta)` para borrar, `Join-Path $env:ProgramFiles ...`, `-like` en lugar de regex, y escribir scripts con la herramienta de archivos y ejecutarlos.
  - Los mensajes de commit largos se escriben en un archivo del scratchpad y se usan con `git commit -F`.
  - Git avisa de «LF will be replaced by CRLF»: es solo la configuración de saltos de línea.

## 4. Estado real de cada ambiente (al 2026-10-29)

| Ambiente | Estado |
|---|---|
| `crm` (producción local) | En `20261028_0041` **sin que el usuario lo decidiera** (incidente, sección 13). Las tablas de billing y de reportes de Toku existen y están vacías (la política tiene su fila por defecto). Roles: `admin`, `coordinador`, `jefatura`, `soporte`; **falta correr `scripts/maintenance/seed_roles.py`** (crea `ejecutivo` y asigna permisos de lectura; lo hace el usuario: USR-01/USR-10/USR-11). 3 usuarios. `core_charges` se reconstruyó con el ETL de Core (2.169 filas) y sus totales coinciden con `vp_charges`. El último respaldo es del 2026-10-07 (pre-core) y `pg_dump` no está en el `PATH` |
| `crm_sandbox` | En `20261028_0041`, con roles `admin`, `ejecutivo` y `soporte`, 1 usuario admin, datos de VirtualPOS sandbox (cuenta 1: unos 1.456 cargos de prueba y 13 suscripciones) y **datos sintéticos de demostración** de la Opción A con prefijo `DEMO-` (11 solicitudes de los 4 tipos y 10 estados, 30 eventos, 6 tareas de renovación, 24 cobros gestionados, 7 marcas de calendario, 2 auditorías de política). Los eventos y la auditoría son inmutables por trigger: esos datos solo se limpian con `TRUNCATE` manual de las tablas de billing en el sandbox |
| `crm_test` | Solo para pytest |
| Procesos | Vite 5173 y 5174 y backend 8000 son del usuario; el backend sandbox 8001 lo dejó corriendo el orquestador (sin recarga). **Los dos túneles públicos de Cloudflare se detuvieron el 2026-10-29** (llevaban abiertos desde el 26 de octubre a las 23:15; uno publicaba el frontend de producción local). `state.json` de Playwright borrado |
| Playwright | Paquete de **Node** (v1.64.1) instalado **fuera** del repo, en la carpeta `pw` del scratchpad de una sesión; si esa carpeta desaparece hay que reinstalarlo fuera del proyecto (ver `scripts/visual/README.md`, variable `PLAYWRIGHT_NODE_DIR`). El script cae a Google Chrome instalado porque el Chromium en caché (`chromium-1234`) no coincide con esa versión |
| Skill y agentes personales | En `C:\Users\Usuario\.claude\` (no versionados; solo aparecen como tipos con nombre en una sesión nueva): skill `sandbox-orchestrator` y agentes `sandbox-tester` (solo ejecuta escenarios catalogados) y `decision-maker` (solo lectura) |

## 5. Lo que se hizo, por sprint y por línea de trabajo

El detalle por tarea está en `docs/tasks.md`; aquí el resumen. Los commits de esta sesión van de `413a740` a `a96ea0c` (31 commits).

### Sprints 0 a 3 (sesiones anteriores)
- **Sprint 1** (auditoría de datos): modelos por canal en `docs/data/`, idempotencia en `docs/data/sync-idempotency.md`; SYNC-GAP-01/03/04 resueltos o mitigados; SYNC-GAP-02 (TCH, rechazo y pago posterior de la misma cuota) caracterizado con tests y **abierto como decisión de negocio (DEC-04)**; `crm_materialization.py` desactivado, no borrado (`POST /etl/run` devuelve 410); cada consolidación corre en SAVEPOINT; TK-10 cerrada (no depende de `flow_name`).
- **Sprint 2**: `KpiCard`, `ChannelChart`, `ChannelKpiStrip`; contrato de KPIs en `features/shared/kpis.ts`; `rejected_charges` en los 4 canales; MRR de Payku desde la última transacción exitosa.
- **Sprint 3**: `ChannelChart` ampliado; gráficos de los 4 canales (`features/dashboard/channelCharts.ts`); sidebar con salud de canal (`GET /api/v1/sync-runs/health`).
- **Transversal anterior**: ambientes (`APP_ENV`, guardas de URL y credenciales), rol `soporte`, pruebas aisladas en `crm_test`, limpieza de la base `crm` (549 usuarios y 310 roles de prueba), secreto JWT rotado, cliente de VirtualPOS endurecido (errores con HTTP 200, idempotencia por `internal_code`, `retry_charge` sin reintento ante timeout), suite de contrato (17 pruebas).

### Sprint 4: Recuperador VP y Opción A (esta sesión)
- **REC-03** (recuperador VP) y **`monto_vigente`** (último cobro pagado o procesando con fecha hasta hoy; fecha en **hora de Chile**, corregido en `413a740`).
- **Opción A completa en código** (BILL-01 a BILL-08): permisos y rol `ejecutivo`, modelos y migración 0038, cálculo puro del plan, aplicación con compensación y lock, API `/billing`, bandeja y política en el frontend, chequeo diario de renovación y pestaña Renovaciones. Ver sección 6.
- **Revisión de código independiente** (cuatro revisores, 5 frentes) y **tres tandas de arreglos**: tanda 1 (planificador y aplicación: puntuales fuera del calendario regular, día de cobro resuelto por solicitud, marca o día más frecuente, pendiente de hoy sin tocar, E-079 con verificación, listados incompletos fallan cerrado, barredor de solicitudes atascadas, guardianes del DELETE plural y del flujo viejo `reassign`), tanda 2 (API, política con aprobadores efectivos, reabrir con aprobador, errores persistidos sin texto libre, KPIs de sincronización sin las filas de facturación, jobs con fila `running`) y tanda 3 (frontend de aplicar con listas reales, CSRF obsoleto, paginación, hora de Chile, textos por código; endurecimiento de Toku).
- **Guarda contra `downgrade` accidental** de Alembic (OPS-10) y reglas para agentes.
- **Consolidación del plan** en un solo archivo (`docs/tasks.md`) y runbook de pruebas en sandbox aprobado.
- **Importador de reportes de Toku**: TK-17 (modelos y migraciones 0039 a 0041) y TK-18 (parser y carga como servicio). Ver sección 7.
- **Revisión visual del sandbox** con capturas y tres tandas de arreglos de interfaz (UI-22 a UI-27). Ver sección 8.

## 6. Cómo funciona la Opción A (cambios de cobro de VirtualPOS)

**Objetivo:** permitir cambiar el monto o el día de cobro de una suscripción VirtualPOS (más de 6.000 están en planes `MONTO_FIJO`, que no se pueden cambiar) creando y cancelando cobros individuales, con solicitud, aprobación, ejecución segura y auditoría. VirtualPOS sigue creando los cobros mensuales; el CRM solo interviene al aplicar un cambio aprobado.

**Módulos**
- `app/services/billing_plan.py`: cálculo **puro** del plan (sin red ni base): `build_amount_change_plan`, `build_date_change_plan`, `build_renewal_plan`, `build_one_off_plan`, `plan_to_preview_json`. Horizonte de 12 meses, ventana de 31 días, cobertura de mes, días 29 a 31 ajustados a fin de mes, `internal_code` determinista (`{sub}-{YYYYMM}-{monto}`; cambio de fecha con sufijo `-d{DD}`).
- `app/services/billing_apply.py`: `apply_change_request`. Transición atómica `aprobada` a `aplicando`, `pg_try_advisory_xact_lock` por suscripción en una **conexión dedicada** (queda «idle in transaction» durante la aplicación: revisar `SHOW idle_in_transaction_session_timeout` en la base real, BILL-22), plan recalculado contra el estado real del proveedor y detección de *drift*, **crear todos los cobros nuevos antes de cancelar los antiguos, uno por uno por `charge_id`** (nunca el DELETE plural), compensación si falla a mitad, verificación final de «exactamente un pendiente por mes», registro en `vp_managed_charges` y marca en `vp_calendar_marks`. `sweep_stuck_applying` deja en `requiere_conciliacion` las solicitudes atascadas en `aplicando`.
- `app/services/billing_requests.py`: crear (con autoaprobación auditada), aprobar (doble aprobación implementada y apagada), rechazar y reabrir con comentario obligatorio, retirar, expirar, y la política con sus reglas (siempre al menos un aprobador efectivo; con doble aprobación 2 o 3).
- `app/services/billing_renewal.py` y `app/scheduler/jobs/billing_jobs.py`: chequeo de **solo lectura** que abre tareas de renovación cuando a una suscripción con calendario modificado le quedan N días o menos (N de la política, borde inclusivo). Jobs: `billing_renewal_check` (03:00 America/Santiago, entre el sync de las 02:00 y el reintento de las 04:00), `billing_expire_requests` (cada hora, minuto 10) y `billing_sweep_applying` (cada 15 minutos). Dejan filas en `sync_runs` con prefijo `billing_`, que los KPIs de sincronización de canales excluyen (`SyncRun.is_channel_source()`); estado `partial` si hay errores parciales.
- `app/api/v1/routes/billing_changes.py` (`/api/v1/billing`): `changes/preview`, `changes` (POST y GET), `changes/{id}` y `/events`, `/approve`, `/reject`, `/withdraw`, `/reopen`, `/apply` (con `accept_drift`), `requesters`, `renewal-tasks`, `policy` (GET y PUT) y `policy/audit`. El actor sale siempre del token; los cuerpos rechazan campos extra; los errores llevan `detail={code,message}` sin eco de valores.
- Modelos (`app/models/billing.py`, migraciones 0037 y 0038): `billing_change_requests` (estados `pendiente`, `aprobada`, `aplicando`, `requiere_conciliacion`, `ejecutada`, `fallida`, `rechazada`, `retirada`, `expirada`, `no_ejecutable`; **índice único parcial: una sola solicitud abierta por suscripción** en `pendiente`, `aprobada`, `aplicando` y `requiere_conciliacion`), `billing_change_request_events` y `billing_policy_audit` (inmutables por trigger de base), `billing_policy` (fila única), `vp_managed_charges`, `vp_calendar_marks` y `billing_renewal_tasks`. `write_runs` recibió `requested_by_user_id` y `request_id`.
- Permisos (migración 0037, solo `admin`): `virtualpos.billing_changes.request`, `.approve`, `.view` y `virtualpos.billing_policy.manage`.
- Frontend `frontend/src/features/billing/`: bandeja en `/general/cambios-de-cobro` (la ruta vieja `/virtualpos/cambios-de-cobro` redirige), pestañas Pendientes, Historial y Renovaciones, detalle con la vista previa del plan, diálogos de aprobar, rechazar y reabrir, y la política de aprobadores como sub-pestaña «Aprobaciones» del panel de administración.

**Política por defecto:** aprueba el rol `admin`; autoaprobación activada y auditada; doble aprobación apagada (umbrales: más de 20 suscripciones o variación mayor al 50 %); renovación a los 60 días; expiración de solicitudes a los 7 días; horizonte de 12 meses; ventana de 31 días.

**Cosas importantes que no son obvias**
- El **DELETE plural** (`cancel_future_charges` sin `charge_ids`) cancelaría también cobros manuales y automáticos fuera del horizonte: está prohibido desde `apply` y bloqueado (409) si la suscripción tiene marca de calendario modificado o cobros del CRM vivos. El flujo viejo `reassign_subscription_amount` ahora respeta el lock, las marcas y las solicitudes abiertas.
- Los **cobros puntuales** (`one_off_charge`) se excluyen del calendario regular (no se cancelan, no cuentan para el horizonte de renovación ni para deducir el día).
- **Pendiente de decisión (DEC-30):** la tanda 1 acotó el reemplazo de un mes atrasado a su propio mes (los meses pasados van a revisión manual con `replacement_outside_month`), lo que **contradice la regla del usuario** de que el reemplazo se fecha «mañana». Opciones: A (recomendada) respetar la regla atribuyendo cada cobro a su mes de origen por el `internal_code`, B dejar lo actual, C híbrido. Bloquea la tanda 1b (BILL-18). Además, por decisión del usuario: mes con solo cobros cancelados va a revisión manual y mes sin ningún cobro se crea con aviso `month_without_charge` (también en BILL-18).
- No se ha probado nada de la Opción A contra el proveedor real: todo se probó con un `FakeVP`. Las pruebas de contrato P0 (CT-00, CT-CO-AUTO, CT-CO-DUP, CT-CO-NC3, CT-RZ-MC, CT-RZ-SWAP, CT-CANCEL, CT-STALE) son BILL-11 y algunas requieren tarjeta y esperar fechas de cobro. El **piloto en producción** (BILL-12) solo con el usuario presente.

## 7. Toku: sandbox, guardas e importador de reportes

### El «sandbox» de Toku
- **Toku no documenta un sandbox.** El del CRM usa la **misma URL base que producción** (`api.trytoku.com`) con otra llave `x-api-key`. Medido el 2026-10-28 con lecturas (llave sandbox, solo conteos): una organización aparte con **34 clientes, 37 suscripciones y 41 invoices** (todas `UNPAID` y vencidas), **0 transacciones y 0 medios de pago**, `/organization/payments` responde 404, y **0 IDs en común con producción**. Es decir, las lecturas están aisladas; **las escrituras siguen sin verificarse**.
- Por eso no hay datos para probar el recuperador de Toku en el sandbox (ni rechazos TE/PE/UE, ni tarjeta vencida, ni rachas). La documentación oficial no trae tarjetas de prueba; lo más cercano es el portal sandbox de PAC (RUT de prueba de la documentación y coordenadas «00 00 00» para forzar una inscripción fallida). Las seis consultas para el soporte de Toku están resumidas en DEC-26 y siguen a cargo del usuario.
- El header de versión (`x-api-version` y `x-toku-api-version`) **no** cambia las respuestas en el sandbox: hipótesis descartada. `recurring` y `recurring.status` existen solo si `is_recurring=true`; `remaining_collection_attempts`, `max_collection_attempts` y `expiration_date` pertenecen a la invoice y vienen nulos. La API **no** entrega estado de cliente ni de suscripción.
- La API de reportes existe: `GET /reports/{entity}/columns` respondió 200 con la llave sandbox para siete entidades (suscripción, medio de pago, intento de pago, inscripciones, invoice, cliente). `POST /reports/{entity}` **no se ha usado** (genera reportes y está bloqueado por las guardas).

### Guardas duras de escritura (fuera de producción)
`app/integrations/toku/write_guard.py`, invocado desde el cliente antes de la red. Para escribir en el sandbox hacen falta: `TOKU_SANDBOX_WRITES_ENABLED=true` **y** la variable de proceso `TOKU_SANDBOX_ALLOW_WRITES_ARMED=1`; host exacto `api.trytoku.com`; lista blanca de endpoints; prefijo `TEST-` en las claves de negocio; los IDs que genera Toku (`cus_`, `sub_`, `in_`, `pm_`) **nunca** empiezan por `TEST-`, así que para tocarlos hay que listarlos en `TOKU_SANDBOX_ALLOWED_IDS`; tope `TOKU_SANDBOX_MAX_WRITES` (25 por defecto, máximo 500, por proceso); bulk y batch bloqueados; en invoices `customer` es obligatorio y se rechazan otras claves de referencia. `delete_subscription` valida la suscripción y todos los cobros antes de anular ninguno (la anulación es irreversible) y falla cerrado si no puede listar. Las rutas `/writes/toku/*` responden 403 con solo el código; el detalle queda en `write_runs`. Al arrancar hay un **aviso** si `APP_ENV` es `development`, `dev` o `local` y `TOKU_WRITES_ENABLED` está encendido (sin cambiar el comportamiento). Producción no cambia.

### Importador de reportes descargados (TK-14 a TK-22)
- **Por qué:** la API REST no entrega estado de la suscripción, medio de pago ni motivo de rechazo; los reportes del Backoffice sí. Se cargan desde la interfaz (como TCH) una vez por semana (DEC-21).
- **Hecho:** TK-17 (tablas `tk_report_files`, `tk_report_response_codes`, `tk_report_products`, `tk_report_payment_methods`, `tk_report_attempts`, `tk_report_debts`, `tk_report_inscriptions` y `core_subscription_signals`; permiso `toku.reports.import` solo para `admin`; sin columnas personales ni `raw_payload`) y TK-18 (`app/services/toku_report_parser.py` y `toku_report_import.py`: detección del tipo por firma de columnas, encabezado desplazado, columna duplicada por posición, upsert idempotente con guarda de frescura por columna y eliminaciones que no se deshacen, resolución de producto a suscripción, una transacción por archivo, errores sin PII, 30.000 filas en unos 16 s).
- **Pendiente:** TK-19 (ruta de subida y panel en administración), TK-20 (ETL a core: señales de «activa», racha por cuotas, tarjeta bloqueada y vencida; riesgo alto), TK-21 (más pruebas), TK-22 (documentar columnas en `docs/data/toku.md`) y TK-13 (ajustar KPIs; cambia MRR y ARPU de Toku).
- **Secreto:** `TOKU_REPORT_HASH_PEPPER` (vacío = el importador se niega a cargar). Lo define el usuario en su `.env`, nunca se versiona, y cambiarlo invalida la correlación con hashes guardados. `ID Producto` (que contiene el RUT) se guarda solo como HMAC.
- **Definiciones acordadas (DEC-16 a DEC-25):** *recuperable* = racha de 3 o más cuotas impagas «en firme» (código 2070 o tras cierto número de días), o tarjeta bloqueada, o tarjeta vencida; la racha se mide por **cuotas**, no por intentos (72 suscripciones frente a 138); *suscripción activa* = no eliminada y medio de pago `chargeable`; tarjeta bloqueada = código 1019, 1051 o 2043, o medio `permanent_failed`; vencida = 1010, 2044 o 2063 (no hay fecha de expiración en ningún reporte); un medio con falla temporal sin racha no es recuperable; el reporte gana para estado y medio de pago, la API para montos y facturas.
- **Datos de los reportes (sin datos personales):** el del 2026-10-20 contiene al del 2026-08-09 (las filas mutan: cargar el más nuevo; cargar uno viejo sobre uno nuevo es un error y la guarda de frescura lo evita). Falta un reporte de **Deudas** actualizado (USR-09). La columna `Estado` del reporte de Productos es el estado del medio de pago, **no** el de la suscripción. `last_payment_intent_response_code` viene vacío en todos los medios; el código se obtiene del último intento fallido.

## 8. Revisión visual con capturas (Playwright) y ciclo de pruebas en sandbox

- **Herramientas:** `scripts/sandbox/seed_billing_demo.py` (siembra sintética e idempotente con prefijo `DEMO-`; fija `APP_ENV=sandbox` antes de importar y falla cerrado si la base no es sandbox) y `scripts/visual/capture_sandbox.mjs` (+ `README.md`): `login` abre una ventana visible para que **el usuario** inicie sesión (el script nunca ve la contraseña; permite solo el `POST /api/v1/auth/login`) y `capture` hace capturas de **solo lectura** (18 pantallas × escritorio 1440 y móvil 390 × tema claro y oscuro; solo `localhost:5174`; bloquea toda petición que escriba; los diálogos y el menú móvil se capturan como ventana). El estado de sesión y las capturas quedan en el scratchpad; las copias para el usuario están en `Downloads\CRM_capturas_sandbox\2026-10-29` (antes) y `\2026-10-29_despues` (después).
- **Resultado medido:** cero errores de consola, de página o de red en las 72 entradas; menú lateral de 220 px en 17 de 17 pantallas de escritorio (antes 172 a 220); capturas móviles de la bandeja en 390 px (Renovaciones medía 442); «pagos pendientes» de 1.425 (incluía 1.343 cancelados) a 82; alertas de 64 a grupos con tope de 5; contrastes del menú y de la pestaña activa de 1,2 a 2,5 : 1 subidos a más de 6 : 1 (con un test que vigila 4,5 : 1).
- **Una sola definición de «rechazo»** (`app/services/charge_stats.py`): universo de cargos con fecha de cobro hasta hoy en hora de Chile, sin cancelados, expirados ni anulados; tasa = rechazados / (pagados + rechazados); `None` (se muestra «—») si no hay denominador. La comparten las tarjetas y las alertas. El churn declara su ventana (`churn_window_label`: VirtualPOS promedia 3 meses; Toku y Payku usan el acumulado; unificarlo es DEC-37).
- **Pendientes de la revisión (UI-28 a UI-41):** los gráficos «Deudas mensuales» y «Transacciones efectivas» siguen clasificando como «rechazada» todo lo que no es pagado; el KPI `rejected_charges` cuenta transacciones en Toku y Payku y cargos en VirtualPOS y TCH; los reportes HTML tienen su propia lógica de rechazo; VirtualPOS en móvil desborda 7 px; la barra «Planes 8» vacía; textos y controles nativos del recuperador; el color de «Bajas» (DEC-36).
- **Ciclo de pruebas y decisiones** ([runbook](docs/operations/sandbox-testing-and-decisions.md), aprobado el 2026-10-28, DEC-27): el orquestador despliega, lanza al probador, luego al decisor, aplica lo permitido y resume al usuario. Clases de decisión: *automática* (arreglos con test, documentación, commits locales, lecturas en sandbox, elegir la opción recomendada si es reversible), *avisar* (diseño no trivial, escritura en escenarios ya catalogados) y *siempre con el usuario* (producción, push o PR, migraciones o seeds en bases reales, borrado, credenciales o datos personales, debilitar una guarda, permisos, decisiones de negocio). Ante la duda gana la clase más restrictiva. Los resúmenes al usuario llevan alternativas y recomendación.

## 9. Hallazgos sobre VirtualPOS (medidos en el sandbox el 2026-10-27)

La documentación oficial no se debe tomar como verdad. Medido:

| Afirmación de la documentación | Realidad |
|---|---|
| `POST /v3/charge` falla con E-113 en planes MONTO_FIJO | **Se acepta** |
| Los errores llegan con HTTP 400 | Llegan con **HTTP 200** y cuerpo `{"status":"NOK","code":400,"error":{"error_code":"E-0xx",...}}` |
| `internal_code` evita duplicados (E-086) | **No**: dos POST con el mismo código crean dos cargos. Sí aparece en el listado y detalle de cargos. Reutilizarlo tras cancelar se acepta |
| Filtros `charge_date_from/to` en `/charges` | **Se ignoran** |
| `limit=101` y `page=0` dan error | Se aceptan (comportamiento no documentado) |
| El listado de clientes trae `page/limit/total` | Trae un objeto `pagination` |
| El listado de suscripciones trae `charge_program[]` completo | **Confirmado** |
| `DELETE /v3/charges/{sub}` cancela los pendientes | Confirmado; sin pendientes responde E-079 (con HTTP 200) |
| Cargo manual en un mes con automático pendiente | **Conviven ambos** (sin E-087, sin límite mensual observable hasta 3). **Sin cancelar el automático hay doble cobro pendiente** |
| Cargo manual más allá de `num_charges` | Se acepta |
| Los cargos automáticos traen `internal_code` | No; los manuales sí (sirve para distinguirlos) |

Sin medir todavía: si el proveedor cobra ambos cargos del mismo mes en sus fechas, si los cargos cancelados consumen `num_charges`, el comportamiento tras `changecard`, reintentos automáticos de cargos manuales rechazados, rate limits en lotes grandes y qué devuelve un DELETE individual sobre un cobro que ya no está pendiente (E-059 o E-079): el código maneja ambos.

## 10. Decisiones de negocio del usuario (vigentes)

1. Hay 6000+ suscripciones en planes `MONTO_FIJO`; **no se pueden cambiar planes** ni pedirle la tarjeta de nuevo al socio.
2. El «monto de la suscripción» en el CRM es el último monto cobrado (`monto_vigente`).
3. **VirtualPOS sigue creando los cobros mensuales.** El CRM solo crea cobros al aplicar un cambio aprobado o por una tarea puntual.
4. Cambio de monto: horizonte de 12 meses; se cancelan los automáticos **solo dentro del horizonte**; orden seguro (crear todos primero).
5. El día de cobro es el del último cargo y se guarda como dato propio (`charge_day`).
6. Rechazos: el CRM no crea cobros ni suspende nada; solo reintenta. La «racha de rechazos» (3 o más) es una ayuda de solo lectura.
7. Ventana de 31 días: si el mes ya pasó hace 31 días o menos y no tiene cobro pagado, procesando ni rechazado, se crea el reemplazo con fecha de mañana; si es más antiguo, revisión manual (**implementación pendiente de DEC-30**).
8. Aprobaciones: por ahora solo **admin** aprueba, con autoaprobación activada y auditada; doble aprobación apagada; política editable en el panel de administración.
9. «Recuperable» (todos los canales) = socio con racha de rechazos, o tarjeta bloqueada, o tarjeta vencida. **Todos los roles ven todo en el recuperador; el panel de administración es solo `admin`.** Roles: admin y jefatura exportan; soporte reintenta cobros; ejecutivo solo ve.
10. Columna del CSV del recuperador: `cuenta`; el CSV con datos personales solo con permiso de exportar.
11. Reportes de Toku: carga por la interfaz, semanal, con aviso si el dato supera 7 días; permiso propio `toku.reports.import`.
12. Meses con solo cobros cancelados van a revisión manual; meses sin ningún cobro se crean con aviso (BILL-18).
13. Un solo universo de «rechazo» en los dashboards: cargos, sin cancelados ni meses futuros.

Detalle de escenarios de la Opción A: `docs/designs/facturacion-gestionada-escenarios.md` (175 escenarios vigentes, resultados medidos al principio).

## 11. Decisiones abiertas

Todas con su detalle y alternativas en `docs/tasks.md` §5 (familia DEC):
- **DEC-30:** ventana de 31 días y reemplazo de un mes atrasado (bloquea BILL-18).
- **DEC-41:** escala de títulos (A: 22 px en todo según `DESIGN.md`, lo que quedó; B: título destacado «hero»).
- **DEC-34 a DEC-40:** sprint de gráficos (librería —se recomienda mantener Recharts—, endpoints nuevos, colores de altas y bajas, definición de churn, metas, código sin uso, familia de IDs).
- DEC-04 (SYNC-GAP-02, TCH), DEC-05 a DEC-07 (rachas y espaciado), DEC-08 (destino de `reconciliacion-identidad-socios.md`), DEC-11 y DEC-12 (hosting, RPO/RTO y quién ejecuta validaciones), DEC-13 (`monto_vigente` como ADR), DEC-14 (drawer móvil), DEC-15 (continuidad de cobros en WR-VP-05), DEC-26 (seis consultas al soporte de Toku).

## 12. Pendientes y roadmap

**Roadmap por fases acordado (DEC-31):** 1) refrescar `tasks.md` y respaldar la rama (hecho); 2) importador de Toku TK-19 a TK-22 y TK-13; 3) BILL-09, BILL-10 y BILL-11 (pruebas de contrato en sandbox de VirtualPOS; necesita DEC-30 y tarjetas); 4) Sprint 5, recuperador general (`/general/recuperador` con pestañas VP, Toku, Payku y TCH, solo lectura; REC-04 espera TK-20, REC-05 espera el modelo de cargos de Payku PK-06); 5) sprint de gráficos VIZ; 6) piloto BILL-12 en producción, solo con supervisión; 7) Sprint 6 (infraestructura: ENV-01, BCK-01, OPS-09), que no se puede planificar sin DEC-11 y DEC-12.

**Acciones del usuario o de terceros (familia USR)**
- **USR-11 y USR-01/USR-10:** correr `scripts/maintenance/seed_roles.py` en `crm` (crea `ejecutivo`); revisar que `crm` en `0041` sea lo deseado; considerar un respaldo con `pg_dump` antes de futuras migraciones.
- **USR-12:** los túneles públicos de Cloudflare estuvieron abiertos dos días: considerar rotar el secreto JWT de producción y revisar accesos.
- **USR-02:** revisión visual humana (los agentes ya revisaron las capturas; la del usuario sigue pendiente), **USR-03:** KPI-01 y CHART-01 contra VirtualPOS staging.
- **USR-09:** exportar un reporte de Deudas de Toku nuevo y luego uno por semana; definir `TOKU_REPORT_HASH_PEPPER`; configurar los webhooks de Toku (TK-12: `TOKU_WEBHOOK_SECRET` está vacío y falta el secreto de sandbox).
- **USR-04, USR-05:** soporte de Payku, tarjetas de prueba de rechazo. **USR-07:** crear usuarios `soporte` y `ejecutivo` por ambiente. **BILL-22:** ejecutar `SHOW idle_in_transaction_session_timeout;` en la base real y reportar el valor.

**Técnicos, en orden sugerido** (todo con estado en `docs/tasks.md`): TK-19 (ruta y panel de carga), TK-20 (señales), TK-21, TK-22 y TK-13; BILL-09 (allowlist del piloto), BILL-10 (controles de consistencia), BILL-11 (contrato en sandbox), BILL-14 (lock por cargo en `retry_charge`), BILL-15, BILL-16, BILL-18 (tanda 1b), BILL-21 y BILL-22; UI-28 a UI-41 (empezando por los de datos: UI-28 a UI-30); PK-06 y `tests_contract/payku` (avanzan sin credenciales); Sprint 5; sprint VIZ. Deuda menor: `tests/test_health.py` depende del `.env`; borrar `crm_materialization.py` y su test cuando se confirme; TCH sin trazabilidad en `source_records`; el filtro `chargeable` de Toku también cambia las series históricas.

**Sprints que faltan**

| Sprint | Alcance | Esfuerzo | Necesita |
|---|---|---|---|
| 4 (resto) | BILL-09 a BILL-16, BILL-18, BILL-21/22, TK-19 a TK-22, PK-05 | Por re-estimar; TK-18 a TK-22 unas 22 a 30 h de IA según el diseño | Respuestas de Payku, DEC-30, tarjetas de prueba |
| 5 | Recuperador general (REC-04 a REC-06) | 24 a 32 h / 10 a 13 días | TK-20, PK-06 |
| VIZ | Gráficos por tipo de KPI (VIZ-01 a VIZ-12) | 39 a 55 h de IA (estimación; 8 a 12 h más con cohortes) | DEC-34 a DEC-40 |
| 6 | ENV-01, BCK-01, OPS-09, validaciones | 12 a 16 h / 8 a 10 días | Hosting, RPO/RTO, credenciales de sandbox de Toku y Payku, quién ejecuta las validaciones |

## 13. Incidentes y errores cometidos

### Incidentes de esta sesión
- **Alembic sobre `crm` (2026-10-28).** Un agente de la tarea TK-17 corrió `downgrade` y `upgrade` sobre la base real porque su script fijó `DATABASE_URL` en `os.environ` *después* de importar `settings` y `alembic/env.py` lee `settings.database_url` (el `.env` apunta a `crm` y `APP_ENV=development` equivale a producción). `crm` quedó en `0041` y faltaban 2.169 filas de `core_charges` (VP1 744, VP2 1.425), que se reconstruyeron ejecutando `run_vp_core_etl` sobre `crm` con autorización del usuario (totales de nuevo iguales a `vp_charges`; se recrearon 2.002 pagos y 15 suscripciones core). **La causa del faltante no está confirmada**: sospecha del `DELETE FROM core_charges WHERE subscription_id IS NULL` del `downgrade` de la migración 0034, pero las filas reconstruidas quedaron vinculadas. Se perdió además el contenido de `etl_runs.channels_failed` (estaba vacío). Corrección: guarda anti-`downgrade` y la regla 6 de la sección 2. Lección del orquestador: no pedir a un agente una operación cuya seguridad dependa de que fije bien la base.
- **Túneles públicos de Cloudflare** abiertos del 26 al 29 de octubre (uno publicaba el frontend de producción local, protegido solo por el login). Detenidos; no hay señal de acceso indebido pero no puede descartarse (USR-12).
- **Datos personales en el contexto de un agente:** al explorar los reportes de Toku, un agente imprimió filas de hojas que resultaron ser datos y no encabezados (nada se guardó en disco ni se reprodujo). Regla 11 de la sección 2.

### Tabla de errores y correcciones

| # | Error | Cómo se corrigió | Para no repetirlo |
|---|---|---|---|
| 1 | Informé «5.644 activos» en TCH; eran transacciones aceptadas, no clientes | Se rotuló «Transacciones aceptadas» y se añadió `accepted_transactions` | Verificar qué cuenta cada campo antes de reportar una cifra |
| 2 | Los tests escribían en la base `crm` (552 usuarios y cientos de roles basura) | Aislamiento en `crm_test`, guarda dura, limpieza con respaldo y verificación | Los tests jamás apuntan a una base con datos reales |
| 3 | Dos agentes corrían pytest a la vez sobre `crm_test`: fallos intermitentes que se atribuyeron a los tests | Se confirmó con corridas limpias | Una sola sesión de pytest; esperar a que termine el otro agente |
| 4 | El backend del 8000 tenía código viejo (`--reload` no recargó); el selector no aparecía | Reinicio y verificación por `/openapi.json` | Tras cambios de backend, comprobar rutas nuevas, no suponer |
| 5 | `.gitignore` con `.env.*` ignoraba `frontend/.env.sandbox` | Excepción explícita para ese archivo | Probar los comandos desde cero tras tocar `.gitignore` |
| 6 | `git add docs` agregó un documento ajeno sin versionar | Se reescribieron los dos commits locales (aún sin push) | `git add` por ruta; revisar `git status` antes de cada commit |
| 7 | Condición de carrera en el test de `EnvironmentBanner` (1 de 20 corridas) | `waitFor` sobre la clase del `<html>`; 30 corridas sin fallos | Probar los tests de front 20 o más veces antes de darlos por estables |
| 8 | Tests asíncronos con `@pytest.mark.asyncio`, sin `pytest-asyncio` | `asyncio.run` como el resto del proyecto | Revisar cómo prueban los tests existentes antes de escribir uno |
| 9 | La documentación del proveedor se aceptó como cierta (E-113, HTTP 400, `internal_code`, filtros) | Prueba V-5 y suite de contrato | Medir antes de decidir; marcar como «a verificar» lo inferido |
| 10 | El cliente trataba como éxito los errores con HTTP 200 | `VirtualPOSAPIError` central y revisión de cada llamador | Todo cliente de un proveedor debe validar el cuerpo, no solo el código HTTP |
| 11 | `retry_charge` (un GET que relanza el cobro) se reintentaba ante un timeout | `retry=False` para ese método, con test | Un GET con efectos no se reintenta |
| 12 | `scripts/sync_virtualpos.py` y `sync_toku.py` rotos desde `master` (función renombrada) | Corregidos | Ejecutar los scripts auxiliares al renombrar funciones |
| 13 | El primer sync del sandbox falló por suscripciones activas duplicadas que violaban un índice único | Reintento fila por fila en SAVEPOINT | Un dato malo no debe tumbar toda la sincronización |
| 14 | `AUTH_JWT_SECRET` era el marcador público de `.env.example` | Rotado por un valor aleatorio | Comprobar que ningún valor sensible de `.env` coincida con lo versionado |
| 15 | Mis comparadores de la suite de contrato daban falsos «drift» | Corregidos | Las pruebas de contrato también se prueban |
| 16 | Un agente eliminó el botón «Solo ETL» en vez de apuntarlo a full-sync | Se reportó la desviación | Revisar que la implementación respete la opción elegida |
| 17 | La Opción A se diseñó con un job que crea cobros para todos los socios; VirtualPOS crea los mensuales | Rediseño y catálogo reescrito | Confirmar el alcance con el usuario antes de diseñar una pieza grande |
| 18 | El validador de comandos de PowerShell bloquea patrones inocentes (ver sección 3) | Reescribir sin regex ni rutas con espacios; archivos de mensaje de commit | No depender de expresiones complejas en una sola línea |
| 19 | Apareció un `.env copy` sin versionar en la raíz | El usuario lo retiró | No dejar copias de `.env` en el árbol |
| 20 | Un agente ejecutó Alembic sobre la base real `crm` (ver incidente) | ETL de Core, guarda de `downgrade` y regla 6 | Ningún agente corre Alembic; fijar la base antes de importar `settings` |
| 21 | Recomendé acotar el reemplazo de un mes atrasado a su propio mes (tanda 1) sin notar que contradecía la regla del usuario de fecharlo «mañana»; el agente lo dijo y yo no lo detecté al aprobar | Se registró como DEC-30 abierta, con alternativas, y el commit lo anota | Contrastar cada decisión de diseño con las decisiones de negocio vigentes (sección 10) antes de recomendarla |
| 22 | El script de capturas instalaba la guarda de solo lectura también en el modo `login`, que cancelaba el `POST` del inicio de sesión («Failed to fetch») | Excepción mínima: solo `POST /api/v1/auth/login` y solo en el modo `login` | La prueba «en seco» de un agente (`--help`, falla sin sesión) no ejercita el flujo real: ejecutar de punta a punta |
| 23 | Las capturas de página completa componen mal los elementos `position: fixed` (diálogos, menú móvil) y el paso de «detalle fallida» buscaba la solicitud en la pestaña equivocada | `viewportOnly` para esas pantallas y pestaña Pendientes | No concluir un defecto de la app a partir de un artefacto de captura |
| 24 | Un revisor dio por «no registrada» una función que sí estaba registrada (solo había un comentario desactualizado) y otros afirmaron cifras sin verificarlas | Verificación manual de cada hallazgo grave antes de pedir arreglos | Regla 9 de la sección 2 |
| 25 | `npx tsc --noEmit` se tomó como verificación de tipos, pero el `tsconfig` raíz solo tiene referencias | `npm run build` (`tsc -b`) como verificación real | Regla 13 de la sección 2 |
| 26 | Pytest daba `PermissionError` en `tmp_path` (47 errores falsos) | `--basetemp` en el scratchpad | Sección 3 |
| 27 | Reiniciar el backend sandbox para ver código nuevo invalidó la sesión de Playwright (se había anunciado el riesgo) | Nuevo `login` del usuario | No reiniciar el backend sandbox en mitad de un ciclo de capturas |

## 14. Archivos y documentos clave

- Plan, sprints y estado (fuente única): `docs/tasks.md`. Estado técnico: `docs/memory/PROJECT_STATE.md`. `docs/memory/CURRENT_SPRINT.md`, `docs/product/roadmap.md` y `knowledge/08 - Roadmap/Roadmap.md` son punteros. Reglas para agentes: `AGENTS.md` y `CLAUDE.md`. Diseño visual: `DESIGN.md` (tipografía, tokens, tema oscuro, reglas de gráficos).
- **Runbook de pruebas en sandbox y decisiones:** `docs/operations/sandbox-testing-and-decisions.md` (catálogo de escenarios, clases de decisión, formato de informes, «Ciclo ejecutado»).
- **Opción A:** diseño y escenarios en `docs/designs/facturacion-gestionada-escenarios.md`; código en `app/services/{billing_plan,billing_apply,billing_requests,billing_renewal,charge_stats}.py`, `app/api/v1/routes/billing_changes.py`, `app/models/billing.py`, `app/scheduler/jobs/billing_jobs.py`, `app/db/migration_guard.py`; frontend en `frontend/src/features/billing/`.
- **Toku:** `app/integrations/toku/{client,write_guard}.py`, `app/services/{write_toku,toku_report_parser,toku_report_import,core_toku_etl}.py`, `app/models/toku_report.py`, `docs/integrations/toku/` (incluye la sección de guardas en `resources/authentication.md`).
- **VirtualPOS:** `docs/integrations/virtualpos/` (cada afirmación observada en sandbox lleva su `[CLAIM:VP-Cxx]`), `VALIDATION-PLAN.md`, `tests_contract/README.md`, `app/services/write_virtualpos.py`, `app/integrations/virtualpos/client.py`, `app/services/vp_current_amount.py`.
- **Revisión visual:** `scripts/visual/` y `scripts/sandbox/`.
- Datos: `docs/data/` (modelos por canal y `sync-idempotency.md`). Código crítico adicional: `app/services/channel_consolidation.py`, `app/api/v1/routes/{recovery,staging,tch,sync_runs,system,writes}.py`, `app/core/config.py` (ambientes y guardas), `tests/conftest.py` (aislamiento), `frontend/src/features/{recovery,dashboard,admin,shared}/`.
- Scripts de mantenimiento: `scripts/maintenance/` (`seed_roles.py`, backfills, comparaciones de MRR, limpieza de usuarios de prueba con borrado comentado).

## 15. Archivos sin versionar que NO son nuestros

- `docs/designs/reconciliacion-identidad-socios.md` (documento del usuario; destino en DEC-08).
- `Sin título.canvas`, `Sin título 1.canvas`, `graphify-out/`, `knowledge/00 - Home/2026-10-06.md`.

## 16. Datos de prueba que quedaron en los sandboxes

**VirtualPOS (cuenta 1)**
- `CT-CO-AUTO` (`c98d0682d8`): plan fijo «Plan Básico», ACTIVA, 12 automáticos pendientes intactos.
- `CT-DUP1` (`d2000dd026`): ACTIVA; noviembre de 2026 reemplazado por un cobro manual de $6.500 (el automático de ese mes está cancelado).
- Suscripciones previas usadas por la suite de contrato: una de plan fijo (`a7c5fd80d0`) y una de plan variable (`940cad2ddb`).
- Se crean con el formulario público del plan (enlaces en `vp_plans.raw_payload->>'suscription_url'` de `crm_sandbox`) y las tarjetas de `docs/integrations/virtualpos/resources/sandbox.md`, automatizado con Playwright instalado fuera del proyecto.

**Billing (`crm_sandbox`)**: datos sintéticos `DEMO-SUB-001` a `DEMO-SUB-025` (ver sección 4); no hay ningún dato de billing en `crm`.

**Toku (organización sandbox)**: 34 clientes, 37 suscripciones y 41 invoices preexistentes (≈17 invoices y 18 suscripciones con claves `TEST-` anteriores a nuestro trabajo); no creamos ni borramos nada allí.

## 17. Cómo trabajar con el usuario

- Escribe en **español** (con tildes). Es técnico y delega mucho: quiere avanzar rápido con agentes, pero con control.
- **Siempre que se le pregunte algo, dar alternativas (A, B, C) con una recomendación** y decir qué pasa con cada una. Suele responder «tus recomendaciones» o «acepto la recomendada», que significa tomar la opción A de cada pregunta pendiente. **No es una autorización para operaciones que el runbook reserva al usuario** (producción, push o PR sin pedirlo, borrado, credenciales).
- **Sandbox sí, producción con cuidado** (regla de oro, sección 2). Si una acción toca `crm` o puede afectar datos reales, avisar y pedir un «sí» explícito.
- Prefiere que el orquestador **divida el trabajo en tareas para subagentes**, **verifique** lo que reportan (ruff, suites, build, lectura del código y mediciones) y le resuma lo decidido. Valora que se admitan los errores con claridad.
- Las decisiones de **negocio** (ventana de 31 días, qué es «rechazo», quién aprueba) son suyas; las de **mecánica** (tandas, nombres, orden) puede delegarlas con una recomendación.
- Mensajes de commit sin datos personales ni modelos; archivos de mensaje en el scratchpad; `git add` por ruta.

## 18. Primeros pasos recomendados para quien retome

1. Leer `docs/tasks.md` (tablero, §3.2 Sprint 4, §5 decisiones) y este documento. `git status` y `git log --oneline -5`; la rama debería estar al día con `origin/sprint-4/recuperador-vp`.
2. Verificar el entorno sin tocar nada: `GET /openapi.json` de los backends (¿rutas `/billing`?), `alembic heads` (debe dar `20261028_0041`), y la suite (`pytest -q`, con `--basetemp` si hace falta) más `npm test` y `npm run build` en `frontend/`.
3. Preguntar al usuario por lo que lo bloquea: DEC-30, DEC-41 y las siete decisiones de gráficos; si ya corrió `seed_roles.py` en `crm`; si definió `TOKU_REPORT_HASH_PEPPER` y exportó el reporte de Deudas.
4. Siguiente trabajo sugerido sin dependencias: **TK-19** (ruta de subida y panel de carga de reportes de Toku), luego TK-20. Cada tarea: delegar a un agente con prompt completo, exigir test en rojo primero, verificar uno mismo y commitear por ruta.
5. Antes de cualquier prueba con escritura real, releer el [runbook](docs/operations/sandbox-testing-and-decisions.md) y la sección 2.
