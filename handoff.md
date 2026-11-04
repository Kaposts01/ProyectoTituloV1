# Handoff: CRM SynkmetriX (sesiones del 26 al 29 de octubre de 2026, con el Sprint 5A)

Documento para quien retome el trabajo (persona o Claude). Léelo completo antes de tocar nada. No contiene secretos: las variables de entorno aparecen solo por nombre y las cifras de datos son agregadas (sin datos personales).

> **El plan y el estado de cada tarea viven en [`docs/tasks.md`](docs/tasks.md) (§3.7 para el Sprint 5A) y en [`docs/planning/auditoria-2026-10-29/PLAN.md`](docs/planning/auditoria-2026-10-29/PLAN.md)** (olas, decisiones D1 a D40, acciones del usuario). Este documento conserva lo que no cabe allí: las reglas de trabajo, cómo levantar y verificar el entorno, el estado real de cada ambiente, cómo funciona lo construido, los hallazgos, los incidentes, los errores cometidos y las preferencias del usuario. Actualizado el 2026-10-29 por la tarde (reescrito por completo; la versión anterior era de la mañana).

## Índice

1. Estado en una mirada
2. Reglas de trabajo (leer primero)
3. Cómo levantar, probar y verificar
4. Estado real de cada ambiente
5. Lo que se hizo, por sprint y por línea de trabajo
6. Cómo funciona la Opción A (cambios de cobro de VirtualPOS)
7. Toku: sandbox, guardas, reportes y señales
8. Sistemas nuevos del Sprint 5A (historial, glosas, exportación, webhooks, alertas, reportes PAT, TCH, bajas, Resumen)
9. Revisión visual con capturas, usuario temporal y la Bandeja de decisiones
10. Hallazgos sobre VirtualPOS (medidos)
11. Decisiones de negocio del usuario (vigentes)
12. Decisiones abiertas
13. Pendientes y roadmap
14. Incidentes y errores cometidos
15. Archivos y documentos clave
16. Archivos sin versionar que NO son nuestros
17. Datos de prueba que quedaron en los sandboxes
18. Cómo trabajar con el usuario
19. Primeros pasos recomendados para quien retome

## 1. Estado en una mirada

| Tema | Estado |
|---|---|
| Plan y estado detallado | [`docs/tasks.md`](docs/tasks.md) y el [PLAN del Sprint 5A](docs/planning/auditoria-2026-10-29/PLAN.md), con los 10 informes de la auditoría de esa carpeta |
| Rama | **`sprint-5/sync-confiable`**, creada desde `sprint-4/recuperador-vp` (159 commits por delante, todos locales). **No existe en el remoto: nada de este sprint se subió y no hay PR.** `sprint-4/recuperador-vp` está al día con `origin`. `master` local (`e66c939`) está 1 commit adelante de `origin/master` (`4f06970`). Estrategia acordada (D25): un solo PR de `sprint-5/sync-confiable` a `master`, con `/review` y revisión de seguridad antes, y confirmación del usuario en el momento de subir |
| Pruebas al cierre | Backend **2043 pasan y 2 se omiten** (`pytest -q`, base `crm_test`; las omitidas son la de rendimiento de Toku, `TOKU_PERF_TEST=1`, y la de rendimiento de VirtualPOS, `VP_PERF_TEST=1`). Frontend **1214 pasan** en 87 archivos (`npm test`). `npm run build` (incluye `tsc -b`) y `npm run lint` (exit 0, 18 advertencias preexistentes). `ruff` limpio. Hay guardianes de i18n, de identificadores y de ortografía en el frontend |
| Migraciones | Head del código **`20261029_0051`**. Aplicadas en **`crm_sandbox`** (por el orquestador, con aviso, el 2026-10-29). **`crm` sigue en `20261028_0041`: el usuario aplica `0042` a `0051` con respaldo previo** |
| Sprint 4 | Sigue formalmente en curso en `docs/tasks.md`: lo esencial está en código (sección 5), pero no se cerró con retrospectiva. Pendientes: BILL-09 a BILL-16, BILL-18 (espera DEC-30), BILL-21 y BILL-22, PK-05 |
| Sprint 5A (`docs/tasks.md` §3.7) | Hecho en código: glosas de rechazo (Toku, VirtualPOS, Payku formato), correcciones del ETL de TCH y recarga transaccional, sync rápido (lock, una consolidación, TCH condicional), historial de estados, exportación, usuario temporal para capturas, bajas multicanal (backend y pantalla), webhooks (cola y procesador, apagados), alertas por correo (apagadas), importadores de reportes PAT y de Toku, Resumen unificado, menú de un solo nivel, textos en español e identificadores en inglés |
| Bloqueado por el usuario | Aplicar migraciones en `crm`, respaldo, `seed_roles.py`, `TOKU_REPORT_HASH_PEPPER`, reportes nuevos de Toku (Deudas e Intentos), recarga de TCH, variables SMTP, ficha D40 (reporte con nombres), valores del catálogo (`payment_type_code`, `gateway`) |
| Bloqueado por terceros | Soporte de Payku (sandbox y preguntas Q-xx; la única lectura de producción de Payku dio timeout), respuesta de Toku sobre eventos reales (`subscription.deleted`) y códigos 1051, 2043 y 2044 |

## 2. Reglas de trabajo (leer primero)

1. **Nunca mostrar ni copiar valores del `.env`.** Leer solo nombres de variables. Para modificarlo, scripts que no impriman nada. Existe una guarda de arranque que compara credenciales de sandbox con las de producción.
2. **Un solo `.env`.** No existe `.env.sandbox` (solo `frontend/.env.sandbox`, sin secretos: puerto y proxy de Vite). Con `APP_ENV=sandbox` la app usa **solo** las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL`. **`APP_ENV=development`, que es el valor actual del `.env`, equivale a producción** (`is_production` es verdadero y las guardas de sandbox no corren). Un valor desconocido de `APP_ENV` falla al arrancar.
3. **`crm` NO es el sandbox.** `crm` es la base local con datos reales de producción; el sandbox es `crm_sandbox` y solo se activa con `APP_ENV=sandbox` en el proceso. **Fijar `APP_ENV` y cualquier `DATABASE_URL` ANTES de importar `settings`**: `alembic/env.py` y los scripts leen `settings.database_url` al importar. Todo script de depuración de un agente debe fijar la base `_test` antes de importar y fallar cerrado si no termina en `_test` (o `sandbox` donde se autorice).
4. **Regla de oro del usuario: en sandbox sin problema; en producción siempre con el usuario y con más cuidado.** Ante la duda sobre qué ambiente es, se trata como producción (Toku comparte host con producción; `APP_ENV=development` equivale a producción). Está aprobado en el [runbook](docs/operations/sandbox-testing-and-decisions.md) (DEC-27).
5. **Escrituras al proveedor solo en sandbox y solo con variables de proceso**, nunca dejando las banderas encendidas en `.env` (ver sección 7 para Toku). Producción: todas apagadas.
6. **Ningún agente ejecuta la CLI de Alembic contra ninguna base.** Las migraciones se prueban solo por pytest (`crm_test`). Aplicar migraciones a `crm` lo hace siempre el usuario; a `crm_sandbox` puede hacerlo el orquestador avisando (se hizo el 2026-10-29 con `0042` a `0051`, confirmando antes y sin mostrar secretos que `APP_ENV=sandbox` resolvía a `crm_sandbox`). `alembic/env.py` bloquea todo `downgrade` sobre bases que no terminen en `_test` ni contengan `sandbox` o `qa`, salvo `ALEMBIC_ALLOW_DOWNGRADE=1`.
7. **Una sola sesión de pytest a la vez.** Todas recrean `crm_test` al arrancar. Un agente de backend (con pytest) y uno de frontend (solo `npm`) pueden correr en paralelo; dos de backend, no.
8. **`git add` siempre por ruta, y `git add` + `git commit` en UNA sola llamada encadenada.** El índice de git es compartido entre agentes: dos agentes que commitean a la vez se llevan los archivos del otro (pasó con el paso 19 del frontend, ver sección 14). Verificar con `git show --stat HEAD` que el commit contiene solo lo propio. Nunca `git add .`. Nunca `git stash` con otros agentes activos. No hacer push ni abrir PR sin que el usuario lo pida y lo confirme en el momento. Los mensajes de commit se escriben en un archivo del scratchpad y se usan con `git commit -F`, terminan con la línea `Co-Authored-By` que indique la sesión y van en español.
9. **Verificar lo que reportan los agentes.** Releer los archivos, correr `ruff`, la suite y el build uno mismo. Varias veces el reporte fue optimista, incompleto o falso. **Las pruebas con respuestas simuladas no detectan cambios de contrato:** una regresión de errores pasó varias olas sin verse; la barrida real de pantallas contra el backend sandbox sí la encuentra (sección 9).
10. **No inferir el comportamiento del proveedor de su documentación.** Medirlo en el sandbox o con lecturas autorizadas (la documentación de VirtualPOS se equivocó en 6 puntos y la prueba de producción del 2026-10-29 corrigió otro: el listado de cobros por suscripción SÍ trae `rejected_object`).
11. **Datos personales:** ninguno en el repo, tests, logs, documentos, capturas subidas ni en el contexto de un agente. Los reportes de proveedores (carpetas `Downloads\CRM_reportes` y `docs\Reportes_*`) **no se abren por filas**: solo encabezados, con una función que nunca imprima otra cosa, y conteos. `docs/Reportes_*/` y `*.xlsx`/`*.xls` están en `.gitignore`. Las capturas que se suben fuera del equipo (la Bandeja vive en claude.ai) deben ser solo de cifras agregadas o recortes sin filas: el sandbox contiene nombres que parecen reales.
12. Scripts temporales, capturas y respaldos van fuera del repositorio (scratchpad de la sesión). No dejar copias de `.env` en el árbol. El estado de sesión de Playwright se borra al terminar.
13. **Tipado del frontend:** `npx tsc --noEmit` casi no comprueba nada. La verificación real es `npm run build` (`tsc -b`).
14. Al usuario siempre se le dan **alternativas con una recomendación**, y las preguntas y aprobaciones van como **fichas en la Bandeja de decisiones** (sección 9). Lo que toca producción, permisos, migraciones, borrado, credenciales, exposición a internet o negocio es siempre del usuario y se confirma además en el chat.
15. **Reglas de idioma (decisiones D32 a D38):** lo que ve el usuario va en **español**, incluidos los valores (`Paid` → «Pagado») mediante el catálogo `frontend/src/i18n/es.ts` y `label()`, con «Desconocido (valor)» ante un valor no mapeado; los **nombres de funciones, variables, constantes, tipos, componentes, hooks, módulos y archivos van en inglés**. Excepciones documentadas: la **base de datos conserva sus nombres** (los modelos usan atributos en inglés con `mapped_column("nombre_real")`, sin migración); las **claves JSON de la API se quedan en español** (el frontend las convierte en adaptadores: `summaryAdapter`, `tchAdapter`, `alertAdapter`…); los **comentarios y docstrings se quedan en español**; se conserva **`rut`**; los valores guardados o recibidos de proveedores (`VIGENTE`, `ACEPTADA`, estados de la Opción A en español) no se renombran y se encapsulan en constantes con nombre inglés. Los errores del backend son `{code, message}` (catálogo en `docs/data/error-codes.md`, 90 códigos) y el frontend los traduce por código. Los CSV generados por el backend llevan encabezados en español legible. Detalle: `docs/engineering/identifiers-backend.md` e `i18n-frontend.md`.
16. **Banderas apagadas por defecto:** todo lo que escribe en `crm` o llama a proveedores nace apagado (sección 8). Encender cada una es decisión del usuario, tras respaldo y, si corresponde, una primera corrida manual en sandbox.
17. **Sesiones separadas:** esta sesión es solo del **CRM Proyecto Título**. Lo de **vpbase** (base independiente de VirtualPOS y su Sheet) lo lleva otra sesión; aquí solo se mantiene como puente su Bandeja (otro artifact) cuando esa sesión lo pide: agregar fichas y exportar respuestas a `vpbase\bandeja\respuestas.json`. No mezclar nada de vpbase con el CRM.
18. **Límites de sesión de la API:** pueden cortar a los agentes largos a mitad de tarea. Por eso se commitea por tarea y solo en verde; al reanudar, revisar `git status` y `git diff` de lo que quedó sin commitear antes de seguir.

## 3. Cómo levantar, probar y verificar

| Pieza | Puerto | Comando (desde la raíz) |
|---|---|---|
| Backend producción | 8000 | `.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload` |
| Front producción | 5173 | `cd frontend; npm run dev` |
| Backend sandbox | 8001 | `scripts/run_sandbox_backend.ps1` (fija `APP_ENV=sandbox`; **sin recarga automática**) |
| Front sandbox | 5174 | `cd frontend; npm run dev:sandbox` (Vite sirve el código fuente actual) |

- **Los backends no se recargan solos.** Tras cambios de backend, comprobar `GET /openapi.json` (rutas nuevas) o reiniciar a mano. El backend de **producción local (8000) corre código anterior** (sin `/billing`, `/cancellations`, `/dashboard/general`, `/export`, etc.): reiniciarlo es decisión del usuario y **debe hacerse DESPUÉS de aplicar las migraciones en `crm`**, porque los jobs nuevos (bajas, webhooks) y varias rutas dependen de tablas que hoy no existen allí. El backend sandbox (8001) se reinició el 2026-10-29 con el código más reciente, desacoplado de la consola (registros en el scratchpad).
- Bases locales, mismo PostgreSQL (puerto 5433): `crm`, `crm_sandbox`, `crm_test` (se destruye y recrea en cada sesión de pytest).
- Backend: `$env:PYTHONPATH='.'; .venv\Scripts\pytest.exe -q --basetemp=<scratchpad>\pt`. Lint: `.venv\Scripts\ruff.exe check app tests alembic scripts`.
- Frontend (desde `frontend/`): `npm test`, `npm run build`, `npm run lint`. Para detectar intermitentes, correr los archivos tocados 20 veces seguidas.
- **Capturas con usuario temporal (D21):** `.venv\Scripts\python.exe scripts\sandbox\ephemeral_user.py session -- node scripts\visual\capture_sandbox.mjs autologin --capture [--only pantalla,...] [--viewports desktop] [--themes light,dark]`. Crea un usuario `PW-…` con contraseña aleatoria en `crm_sandbox` (rol `ejecutivo` por defecto; `--role admin --i-know` solo si la pantalla lo exige), inicia sesión con Playwright, captura y lo borra (también si falla). Se niega a correr si la base no es `crm_sandbox`. `ephemeral_user.py cleanup` borra cualquier `PW-*` que haya quedado. Las capturas y el índice (`index.json` con errores de consola, de página y HTTP por pantalla) quedan en el scratchpad.
- Suite de contrato contra el sandbox de VirtualPOS: ver `tests_contract/README.md`.
- Roles en el código: `admin`, `coordinador`, `jefatura`, `soporte` y `ejecutivo`. `soporte` y `ejecutivo` heredan los `.view`; `soporte` además reintenta cobros y cambia de ambiente. Permisos nuevos del Sprint 5A: `export.pii` (admin y jefatura), `virtualpos.reports.import` (admin), `toku.reports.import` (admin) y `subscriptions.cancellation.request|approve|view` (solicitar y aprobar: jefatura y admin; ver: soporte, ejecutivo, coordinador, jefatura, admin). Los tres permisos «fantasma» (`virtualpos.payments.cancel`, `toku.invoices.update`, `toku.invoices.delete`) **siguen sin sembrarse a propósito (D28)**.
- **Particularidades del entorno Windows/PowerShell:**
  - El validador de comandos bloquea patrones inocentes sin ejecutar nada: `Remove-Item` con rutas que empiezan por `C:`, regex con `\d`, `\.` o `/me$`, rutas entre comillas con espacios. Usar `[System.IO.File]::Delete($ruta)`, `-like`, y escribir scripts con la herramienta de archivos.
  - **Escapes de barras invertidas en heredocs de bash:** escribir JSON con rutas de Windows desde un heredoc sin comillas rompe los escapes. Usar la herramienta de archivos.
  - Git avisa de «LF will be replaced by CRLF»: es solo configuración.
  - Playwright lo resuelve `capture_sandbox.mjs` desde la carpeta `pw` del scratchpad de una sesión anterior; si desaparece hay que reinstalarlo fuera del repo (`scripts/visual/README.md`, `PLAYWRIGHT_NODE_DIR`).

## 4. Estado real de cada ambiente (al 2026-10-29, tarde)

| Ambiente | Estado |
|---|---|
| `crm` (producción local) | **En `20261028_0041`.** No se tocó en el Sprint 5A (solo lecturas de solo lectura). Las tablas de billing y de reportes de Toku existen y están vacías. Roles: `admin`, `coordinador`, `jefatura`, `soporte`; **falta `scripts/maintenance/seed_roles.py`** (crea `ejecutivo` y asigna permisos). 3 usuarios. `core_charges` reconstruido el 2026-10-28 y coincide con `vp_charges`. Último respaldo: 2026-10-07 (pre-core); `pg_dump` no está en el `PATH`. **VirtualPOS 2 y Payku fallaron de forma silenciosa del 27 al 28 de octubre** (claves de entorno tras el commit `25eafac`; corregido en código, ver sección 14; el usuario debe revisar su `.env` y reiniciar) |
| `crm_sandbox` | **En `20261029_0051` (head).** Roles `admin`, `ejecutivo`, `soporte`, 1 usuario admin, datos de VirtualPOS sandbox (cuenta 1) y **datos sintéticos `DEMO-`** de la Opción A. Atención: su lista de clientes de VirtualPOS muestra RUT y nombres que **parecen reales** (de pruebas hechas con datos verdaderos); no subir capturas con filas. Sin solicitudes de baja de demostración todavía |
| `crm_test` | Solo para pytest |
| Procesos | Vite 5173 y 5174 y backend 8000 son del usuario. Backend sandbox 8001: reiniciado por el orquestador con el código más reciente; el scheduler está apagado por defecto en sandbox. **Los túneles de Cloudflare están detenidos** (D8: túnel nombrado solo con confirmación del usuario en el momento) |
| Skill y agentes personales | `C:\Users\Usuario\.claude\`: skill `sandbox-orchestrator`, agentes `sandbox-tester` y `decision-maker`; no versionados |

## 5. Lo que se hizo, por sprint y por línea de trabajo

El detalle por tarea está en `docs/tasks.md` y en el PLAN del Sprint 5A.

### Sprints 0 a 4 (resumen)
- **Sprint 1** auditoría de datos y modelos por canal; **Sprint 2** `KpiCard`, `ChannelChart`, KPIs; **Sprint 3** gráficos y sidebar con salud de canal.
- **Transversal**: ambientes (`APP_ENV`), rol `soporte`, pruebas aisladas en `crm_test`, limpieza de `crm`, cliente de VirtualPOS endurecido, suite de contrato.
- **Sprint 4**: REC-03 (recuperador VP), `monto_vigente`, **Opción A** completa (sección 6) con revisión independiente y tres tandas de arreglos, guardas de escritura de Toku, importador de reportes de Toku (TK-17 y TK-18), guarda anti-`downgrade`, revisión visual con tres tandas (UI-22 a UI-27) y runbook de pruebas en sandbox.

### Sprint 5A: datos confiables, al día y gestionables (2026-10-29)
Origen: la auditoría de paridad contra los reportes descargados (10 informes en `docs/planning/auditoria-2026-10-29/`). Resultado medido: VirtualPOS y Payku (cuotas exitosas) ya cuadran en cantidad; faltaban glosas, vínculos y campos; **TCH no cuadraba (1,47 M contra ~1,0 M del control)**; Toku tenía el importador de reportes sin ejecutar y fechas de alta y baja erróneas.
- **Olas 0 a 1C (backend):** errores de configuración de sync tipados, run `partial`/`failed` y estado `degraded`/`failing` en `/sync-runs/health`; catálogos y proyección de rechazos de Toku (`core_charges.latest_rejection_*`), formato de motivo por canal, corrección de `rejected_object`; correcciones del ETL de TCH (período desde `Cuota Mes`, cuota entera, monto, estado, períodos futuros, hash de reportes, `codigo_respuesta`); lock atómico contra ejecuciones simultáneas, VirtualPOS consolida una vez por corrida, TCH solo tras una carga, ETL Core dentro del sync (apagado), instrumentación por fase, KPIs sin cobros futuros, `parity_check.py`.
- **Olas 2A a 2C:** historial de estados (`status_change_events`, migración `0042`), tabla `payment_rejection_details` y captura diaria de glosa de VirtualPOS (migración `0043`), exportación en streaming con auditoría y `export.pii` (migración `0044`), usuario temporal para capturas.
- **Olas 3A a 5C:** bajas seguras (autoría, `refresh_subscription`, baja de VirtualPOS con lock, Toku fail-closed y negada con facturas en cobro), importador de reportes PAT de VirtualPOS (migraciones `0045` y `0046`), clave estable de TCH y recarga transaccional con conciliación (`0047`, `0048`), endpoint del Resumen, cola y procesador de webhooks y reconciliación dirigida (`0049`), reportes de Toku con fechas reales y señales de recuperabilidad.
- **Olas 7A y 7B:** bajas multicanal (`0050`, `0051`) y alertas por correo.
- **Frontend:** tokens y paleta (menú azul marino, superficies azul-gris, series violeta/índigo), `KpiCard` v2, `ChannelChart` ampliado, `AppCore.tsx` de 3.666 a 700 líneas con 106 pruebas de caracterización, botón Exportar, menú de un solo nivel, Resumen unificado, pantalla Bajas, textos en español, identificadores en inglés y errores por código.
- **Decisiones:** D1 a D40 (PLAN §5.1). Las pendientes de respuesta están en la sección 12.

## 6. Cómo funciona la Opción A (cambios de cobro de VirtualPOS)

**Objetivo:** permitir cambiar el monto o el día de cobro de una suscripción VirtualPOS (más de 6.000 están en planes `MONTO_FIJO`, que no se pueden cambiar) creando y cancelando cobros individuales, con solicitud, aprobación, ejecución segura y auditoría. VirtualPOS sigue creando los cobros mensuales; el CRM solo interviene al aplicar un cambio aprobado.

**Módulos**
- `app/services/billing_plan.py`: cálculo **puro** del plan. Horizonte de 12 meses, ventana de 31 días, cobertura de mes, días 29 a 31 ajustados a fin de mes, `internal_code` determinista (`{sub}-{YYYYMM}-{monto}`; cambio de fecha con sufijo `-d{DD}`).
- `app/services/billing_apply.py`: `apply_change_request`. Transición atómica `aprobada` a `aplicando`, `pg_try_advisory_xact_lock` por suscripción en una **conexión dedicada**, plan recalculado contra el estado real, **crear todos los cobros nuevos antes de cancelar los antiguos, uno por uno por `charge_id`** (nunca el DELETE plural), compensación si falla a mitad, verificación final de «exactamente un pendiente por mes». `sweep_stuck_applying` deja en `requiere_conciliacion` las solicitudes atascadas.
- `app/services/billing_requests.py`: crear (con autoaprobación auditada), aprobar (doble aprobación implementada y apagada), rechazar y reabrir con comentario, retirar, expirar, y la política.
- `app/services/billing_renewal.py` y `app/scheduler/jobs/billing_jobs.py`: chequeo de solo lectura de renovación (03:00 America/Santiago), expiración (cada hora) y barredor (cada 15 min), con filas `sync_runs` de prefijo `billing_` que los KPIs de canal excluyen (`SyncRun.is_channel_source()`; ahora también excluye `cancellation_`).
- `app/api/v1/routes/billing_changes.py` (`/api/v1/billing`). Modelos en `app/models/billing.py`, migraciones 0037 y 0038; **los estados guardados siguen en español (D38) y el código los usa por constantes con nombre inglés** (`STATUS_*`, `EVENT_*`, `MANAGED_*`, `TASK_*`).
- Frontend `features/billing/`: bandeja en `/general/cambios-de-cobro` y política en el panel de administración.

**Cosas importantes que no son obvias**
- El DELETE plural está prohibido desde `apply` y bloqueado si la suscripción tiene marca de calendario modificado o cobros del CRM vivos.
- Los cobros puntuales se excluyen del calendario regular.
- **DEC-30 sigue abierta:** la tanda 1 acotó el reemplazo de un mes atrasado a su propio mes, lo que contradice la regla del usuario de fecharlo «mañana». Bloquea BILL-18.
- Nada de la Opción A se probó contra el proveedor real (todo con `FakeVP`). Pruebas de contrato P0 (BILL-11) y piloto (BILL-12) pendientes.

## 7. Toku: sandbox, guardas, reportes y señales

- **Toku no documenta un sandbox.** El del CRM usa la misma URL base que producción con otra llave. Lecturas aisladas (34 clientes, 37 suscripciones, 41 invoices, 0 transacciones, 0 medios de pago); las escrituras no están verificadas. El header de versión no cambia las respuestas. La API no entrega estado de suscripción ni de medio de pago.
- **Guardas duras de escritura** (`app/integrations/toku/write_guard.py`): `TOKU_SANDBOX_WRITES_ENABLED=true` más `TOKU_SANDBOX_ALLOW_WRITES_ARMED=1`, host exacto, lista blanca de endpoints, prefijo `TEST-`, `TOKU_SANDBOX_ALLOWED_IDS`, tope `TOKU_SANDBOX_MAX_WRITES`, bulk y batch bloqueados.
- **Baja de Toku (decisiones D12, D30):** por el flujo de bajas se usa PAUSED o `end_date` (nunca DELETE) y se **niega con facturas `in_progress`** (409 `INVOICE_IN_PROGRESS`). El DELETE directo de `/writes/toku/...` queda solo para el rol admin y **falla cerrado** también en producción (502 `INVOICE_LIST_FAILED`/`INVOICE_VOID_FAILED`, antes avisaba y borraba igual).
- **Importador de reportes del Backoffice:** `POST /api/v1/imports/toku-reports` (solo admin, CSRF, rechaza el mismo archivo por sha256, 503 sin pepper) y `scripts/maintenance/import_toku_reports.py` (dry-run por defecto). **Hoy las tablas `tk_report_*` tienen 0 filas:** falta `TOKU_REPORT_HASH_PEPPER`, reportes nuevos (Productos, Medios de pago, Intentos de pago, Inscripciones y **Deudas** nuevo) y aplicar migraciones. Procedimiento: `docs/data/toku-reports-load.md`.
- **Fechas reales y bajas:** `materialize_report_dates` corrige `suscription_date` (hoy guarda el próximo cobro), `started_at`/`ended_at` y crea las ~140 suscripciones eliminadas **solo en `core_subscriptions`** (no en `subscriptions`, para no mover MRR/ARPU antes de TK-13).
- **Señales de recuperabilidad** (TK-20, bandera `TOKU_REPORT_SIGNALS_ENABLED` apagada): racha por **cuotas** (tres intentos de una cuota cuentan 1), «en firme» a los 7 días (`TOKU_REPORT_FIRM_UNPAID_DAYS`, D39), tarjeta bloqueada (1019, 1051, 2043 o `permanent_failed`), vencida (1010, 2044, 2063); el reporte gana siempre sobre la API para estado y medio de pago (D39). REC-04 (que el recuperador las lea) está pendiente.
- **Glosa:** `tk_transactions.raw_payload` trae `response_code` y `original_response_message` (95,7 % de los FAILED); `toku_rejection_projection` los proyecta a `core_charges`. Los 1.267 FAILED sin dato dependen de cargar el reporte de Intentos. Los FAILED como `core_payments` (D4) están implementados detrás de `TOKU_MATERIALIZE_FAILED_PAYMENTS` (apagada).
- **Webhooks:** Toku es el único canal con webhooks completos (48 eventos, firma `Toku-Signature`, reintentos); la cancelación llega como `subscription.deleted`. Ver sección 8.

## 8. Sistemas nuevos del Sprint 5A

Cada uno tiene su documento; esta tabla es el mapa. **Todas las banderas nacen apagadas salvo indicación.**

| Sistema | Qué hace | Documento | Bandera / acción del usuario |
|---|---|---|---|
| Historial de estados | `status_change_events` (inmutable) registra cambios de estado, monto y glosa en `_upsert_centralized`; baseline para cargas masivas; `GET /api/v1/changes/daily` | `docs/data/status-history.md` | Migración `0042`; `STATUS_EVENTS_ENABLED`/`STATUS_EVENTS_BASELINE` (ver `.env.example`); `scripts/maintenance/consolidate_baseline.py` solo para cargar un canal vacío |
| Glosas de rechazo | `payment_rejection_details` (`capture_source`: `api_charges`, `api_payment`, `report_pat`, `toku_projection`); captura diaria de VirtualPOS con una petición por suscripción (el cobro ya trae `rejected_object` y `payment.order.uuid`); catálogo de motivos | `docs/data/rejection-details.md` | Migración `0043`; `VP_REJECTION_CAPTURE_ENABLED` (tope 500 suscripciones por cuenta y noche; el histórico por API tomaría unos 8 días) |
| Importador de reportes PAT de VirtualPOS | Tablas `vp_report_*`, parser, importación idempotente, glosa e histórico de vínculos pago-cobro, ruta `POST /api/v1/imports/virtualpos-reports` y script (dry-run por defecto). El código de vendedor se guarda como HMAC (`VP_REPORT_HASH_PEPPER`); `vp_subscriptions.raw_payload.seller_id` ya lo guardaba **en claro desde antes** | `docs/data/vp-reports.md` | Migraciones `0045` y `0046`; dry-run con `--dir` y luego `--apply`; después ETL Core de VirtualPOS |
| Exportación CSV | Streaming, anti-inyección de fórmulas, auditoría en `write_runs` sin contenido, PII solo con `export.pii` (admin y jefatura), `GET /api/v1/export/{clientes,suscripciones,cobros,pagos}` y `/count`; botón en las listas | `docs/data/exports.md` | Migración `0044` (permiso); límite: algunos filtros de pantalla no se pueden expresar y el botón lo avisa |
| TCH | Clave estable (ficha, período, cuota) con el último estado y rechazo previo como atributo (D13); historial separado de cargos; recarga completa transaccional con conciliación contra el control (`--dry-run`, `--apply --confirm-database`, `--exclude-months`); campos del Excel antes no cargados; baja «en trámite» que se cierra al importar el Excel | `docs/data/tch-reload.md`, `docs/data/tch.md` | Migraciones `0047` y `0048`; **recarga del usuario con respaldo**; 2023 no cuadra (falta la cartera: reexportar o excluir los 12 meses) |
| Sync más rápido | Lock atómico (`run_lock.py`, `SYNC_RUN_STALE_HOURS`), VirtualPOS consolida una vez, TCH solo tras una carga (`SYNC_TCH_CONSOLIDATE_ONLY_AFTER_LOAD`, activa por defecto), ETL Core dentro del sync (`SYNC_CORE_ETL_ENABLED`, **apagada**, D26), métricas por fase en `source_records` (`sync.metrics`) | `docs/data/sync-idempotency.md` | El usuario enciende el ETL Core tras respaldo y una primera corrida manual por canal |
| Webhooks | Cola `webhook_events`, receptores que solo validan y encolan (firma Toku, tope de body, PII enmascarada), procesador con `FOR UPDATE SKIP LOCKED` y reintentos, reconciliación dirigida cada 3 h | `docs/data/webhooks.md` | Migración `0049`; `WEBHOOK_PROCESSOR_ENABLED` y `TARGETED_RECONCILE_ENABLED`; secretos y endpoint en Toku; **exponer solo `/api/v1/webhooks/*` con túnel nombrado previa confirmación del usuario (D8)** |
| Alertas por correo | Job cada 15 minutos: canal degradado o caído, ETL Core atrasado más de 24 h, webhooks fallidos, bajas o cobros atascados; un correo por condición con recordatorio cada 6 h y aviso de recuperado | `docs/data/alerts.md` | `ALERTS_ENABLED` y variables `ALERT_SMTP_*`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` en el `.env` (el destinatario nunca va en el repo) |
| Bajas multicanal | Solicitud con vista previa de la cascada, aprobación, aplicación con lock y pasos verificados; VirtualPOS reutiliza la baja segura, Toku PAUSED/`end_date`, Payku DELETE con confirmación irreversible, TCH «en trámite»; medios de pago como paso manual registrado; API `/api/v1/cancellations`; jobs de expiración y barrido; pantalla `/general/bajas`; botones directos solo para admin | `docs/designs/baja-cascada.md`, `docs/engineering/cancellations-ui.md` | Migraciones `0050` y `0051` y `seed_roles.py` (verificar que existan los roles `jefatura` y `coordinador`) |
| Resumen unificado | `GET /api/v1/dashboard/general` (KPIs de la jefatura y series de 12 meses) y pantalla `/central/resumen`; la vista anterior `/central/resumen-clasico` se retiró en UX-15 y redirige al Resumen | `docs/data/dashboard-general.md`, `docs/engineering/summary-view.md` | Churn unificado aprobado (D31: bajas del mes ÷ socios al inicio del mes); sin metas (D2) |
| Idioma | Catálogo `i18n/es.ts`, guardianes, adaptadores, errores por código | `docs/engineering/i18n-frontend.md`, `api-errors-ui.md`, `identifiers-backend.md` | Valores del catálogo pendientes (sección 12) |

## 9. Revisión visual, usuario temporal y Bandeja de decisiones

- **Capturas:** `scripts/visual/capture_sandbox.mjs` (modos `login`, `capture` y `autologin`). Unas 24 pantallas (dashboards, Socios, Suscripciones, Bajas, listas de TCH, recuperador, cambios de cobro, administración y el menú móvil). El 2026-10-29, tras reiniciar el backend sandbox con el código renombrado, una barrida de 24 entradas dio **cero errores de consola, de página y HTTP** (20 «ok»; los 4 diálogos de escritura fallaron porque el rol `ejecutivo` no ve esos botones: para probarlos hace falta un usuario admin temporal). Solo se recorrieron pantallas de lectura: **las acciones de escritura siguen probadas solo con simulaciones en el frontend**.
- **Una sola definición de rechazo** (`app/services/charge_stats.py`): universo de cobros con fecha hasta hoy en hora de Chile, sin cancelados, expirados ni anulados; tasa = rechazados / (pagados + rechazados); `None` («—») sin denominador. Ahora excluye también los cobros futuros en las alertas, `pending_payments`, `debts_monthly` y el recuperador.
- **Bandeja de decisiones** (artifact privado en claude.ai, colección `decisions`, leída y escrita con `ArtifactData`): fichas con opciones y recomendación; las críticas nunca se aprueban en lote y se confirman además en el chat; lo marcado no autoriza nada fuera de lo que dice la ficha. Cada decisión resuelta con un cambio visible lleva capturas (`evidence`, subidas como assets): **solo del sandbox, sin filas con nombres; recortar la barra si hace falta**. La Bandeja vpbase es otro artifact, de otra sesión.

## 10. Hallazgos sobre VirtualPOS (medidos)

| Afirmación de la documentación | Realidad |
|---|---|
| `POST /v3/charge` falla con E-113 en planes MONTO_FIJO | **Se acepta** |
| Los errores llegan con HTTP 400 | Llegan con **HTTP 200** y cuerpo `{"status":"NOK",...}` |
| `internal_code` evita duplicados (E-086) | **No**; sí aparece en listado y detalle de cargos |
| Filtros `charge_date_from/to` en `/charges` | **Se ignoran** |
| Cargo manual en un mes con automático pendiente | **Conviven ambos** (doble cobro si no se cancela el automático) |
| Los cargos automáticos traen `internal_code` | No; los manuales sí |

**Medido el 2026-10-29 con lecturas autorizadas (D5):** `GET /v3/payment/{uuid}` trae `rejected_object {code, message, doc_url}` en el nivel superior, hermano de `payment`; **`GET /v3/suscription/{id}/charges?status=rechazado` trae `rejected_object` por cobro y `payment.order.uuid`** (así se obtiene glosa y vínculo con una petición por suscripción); `/payment/{uuid}/attempts` responde 200 en producción (en sandbox da 403) y puede venir con intentos vacíos; `order.amount` es texto en los cobros y entero en el pago. El listado global de pagos no trae glosa. Los `pay:` huérfanos NO aparecen en la ventana 2025-02..2026-10 (las suscripciones canceladas sí tienen sus cobros `cid_`); queda sin fuente local el histórico anterior a 2025-02. El texto del código `-11` sigue al portal: «Excede límite de reintentos de rechazo» (D17).

Sin medir todavía: si el proveedor cobra ambos cargos del mismo mes, si los cancelados consumen `num_charges`, comportamiento tras `changecard`, reintentos de cargos manuales rechazados, rate limits en lotes grandes, y la glosa del adquirente (`-2xxx`) en `attempts`.

## 11. Decisiones de negocio del usuario (vigentes)

1. 6000+ suscripciones en planes `MONTO_FIJO`: no se cambian planes ni se pide de nuevo la tarjeta.
2. El «monto de la suscripción» es el último monto cobrado (`monto_vigente`).
3. VirtualPOS sigue creando los cobros mensuales; el CRM solo crea cobros al aplicar un cambio aprobado o una tarea puntual.
4. Cambio de monto: horizonte de 12 meses; orden seguro (crear todos primero).
5. El día de cobro es el del último cargo.
6. Rechazos: el CRM no crea cobros ni suspende nada; solo reintenta; la racha (3 o más) es una ayuda de solo lectura.
7. Ventana de 31 días: pendiente de DEC-30.
8. Aprobaciones de cambios de cobro: por ahora solo admin, con autoaprobación auditada.
9. «Recuperable» = racha de rechazos, tarjeta bloqueada o vencida. Todos los roles ven el recuperador; admin y jefatura exportan.
10. Reportes de Toku: carga por la interfaz, semanal, permiso propio.
11. Un solo universo de «rechazo» en los dashboards.
12. **Sprint 5A (PLAN §5.1):** menú azul marino y superficies azul-gris (D1, D27), paleta violeta/índigo (D19), churn como tarjeta y unificado (D20, D31), Etas, Donación individual y metas fuera por ahora, entregará las bases (D2); tabla única de rechazos (D3), FAILED de Toku como pagos centrales (D4), importador PAT para el histórico (D6), eventos en el código (D7), webhooks por túnel nombrado como puente hasta migrar a hosting (D8), SSE con respaldo de polling (D9), refresco caliente cada 3 h de 07:00 a 22:00 (D10), lock ya y worker separado como destino (D11), **bajas: jefatura solicita, admin o jefatura aprueban, ejecutivo solo lee, Toku con PAUSED/`end_date` (D12)**, clave de TCH por ficha, período y cuota (D13), donaciones de Payku fuera por ahora (D14), alertas por correo (D15), URL de VirtualPOS 2 igual a la de la cuenta 1 (D16), `-11` según el portal (D17), reportes fuera de git (D18), usuario temporal para capturas (D21), exportación con PII solo admin y jefatura y CSV con filtros (D22, D23), un solo PR (D25), ETL Core encendido solo tras respaldo y corrida manual (D26), permisos fantasma sin sembrar (D28), menú de un solo nivel (D29), baja de Toku negada con facturas en cobro (D30), reglas de Toku de 7 días y reporte gana (D39), reglas de idioma D32 a D38.

## 12. Decisiones abiertas

- **D40** (Bandeja SynkmetriX): `app/templates/reports/virtualpos.html` es un reporte generado el 3 de octubre con **1.408 nombres de clientes reales** incrustados; nadie lo usa; git lo ignora (`reports/`). Recomendado: moverlo fuera del proyecto. No lo borró ningún agente: es del usuario.
- **Valores del catálogo:** significado de `payment_type_code` de VirtualPOS (p. ej. `VN`) y de `gateway` de Toku (hoy se ven «Desconocido (valor)»); y qué hacer con `tipo_mandato`, `origen` y `razon_baja` de TCH (siguen en español del proveedor).
- **DEC-30** (ventana de 31 días, bloquea BILL-18), DEC-41 (escala de títulos), DEC-35 a DEC-40 de gráficos que sigan sin cerrarse, DEC-04 (resuelta para TCH por D13), DEC-08, DEC-11 y DEC-12 (hosting, RPO/RTO), DEC-26 (consultas al soporte de Toku).
- Pendientes de decisión técnica: eliminación de medios de pago en Toku (MGT-11), baja de TCH y responsable bancario (MGT-13), jobs de bajas ya registrados, `canal` como nombre de prop en `ExportButton`.

## 13. Pendientes y roadmap

**Acciones del usuario, en orden recomendado**
1. **Respaldo** de `crm` con `pg_dump` (no está en el `PATH`) y **aplicar las migraciones `0042` a `0051`**; correr `scripts/maintenance/seed_roles.py` y verificar que existan los roles `jefatura` y `coordinador`.
2. **Recién después, reiniciar los backends 8000 y 8001** (el 8001 ya está al día); revisar el `.env`: `VIRTUALPOS2_BASE_URL`, `PAYKU_API_KEY` y `PAYKU_SECRET_KEY` (hay alias a los tokens público y privado, y la URL de la cuenta 2 cae a la de la cuenta 1: confirmar que es el mismo host).
3. **`TOKU_REPORT_HASH_PEPPER`**, exportar los reportes nuevos de Toku (incluidos Deudas e Intentos) y cargarlos con el dry-run del script; luego `toku_report_lifecycle.py --signals`.
4. **Recarga de TCH** (procedimiento en `docs/data/tch-reload.md`): dry-run con `--exclude-months` de 2023, apply con `--confirm-database crm`, ETL Core de TCH y verificación con `scripts/diagnostics/parity_check.py --channel tch`. Reexportar la cartera 2023.
5. **Importador PAT de VirtualPOS** (dry-run y apply) y ETL Core de VirtualPOS; opcional `VP_REPORT_HASH_PEPPER`.
6. **ETL Core automático:** una corrida manual por canal con respaldo y revisión, y solo entonces `SYNC_CORE_ETL_ENABLED=true`.
7. **Alertas:** variables SMTP y `ALERT_EMAIL_TO`, luego `ALERTS_ENABLED=true`.
8. **Webhooks de Toku:** crear el endpoint con `POST /webhook_endpoints` (probar primero con la llave sandbox), `TOKU_WEBHOOK_SECRET`, exponer solo `/api/v1/webhooks/*` con túnel nombrado **previa confirmación en el chat**, y encender `WEBHOOK_PROCESSOR_ENABLED`; confirmar con soporte el evento real de baja.
9. Decidir D40, los valores del catálogo, y abrir el PR (D25) tras `/review` y la revisión de seguridad. La revisión de la rama del otro desarrollador (REV-01, D24) espera a que suba sus commits: `origin/sprint-5/estabilizacion-dashboard` apunta al mismo commit que `master` y no tiene cambios propios.

**Técnicos pendientes (por valor)**
- REC-04 (el recuperador general lee las señales de Toku) y su pantalla; UX-09 (vista unificada de Cobros), UX-10 y UX-11 (Socios sobre Core, identidad, ADR-001; hoy «Socios» sigue agrupado por RUT), retirar la vista clásica del Resumen (UX-15), metas y Plan 2030 (UX-14), histórico de MRR (UX-13).
- SYNC-O-02, 05, 06 y 09: lectura por ventanas de fecha (Toku, VirtualPOS y Payku) y refresco por niveles caliente, tibio y frío; tablas `sync_cursors` y `tch_file_loads`; worker separado del scheduler (SYNC-O-12); SSE hacia el navegador (RT-11 y RT-12).
- MGT-11 a MGT-14 y MGT-17: eliminar medios de pago, cambio de monto en Toku y Payku, exportación de TCH para tesorería, pruebas de contrato; `close_tch_cancellations_from_report` no se llama en la recarga completa.
- PK-PAR-05, 09 y 11: glosa de Payku por `GET /api/transaction/{id}` (la única lectura de producción dio timeout; falta una ventana más corta o un sandbox) y donaciones puntuales fuera por decisión.
- TK-13 (KPIs de Toku, MRR y ARPU), TK-PAR-07 y 09 (Clientes, Pagos, Liquidaciones), BILL-09 a BILL-16, BILL-18, BILL-21 y BILL-22, VAL-PK-01.
- Deuda: constantes para los valores de proveedor de TCH (~100 literales), ~40 variables locales en español en tests, el dominio `apiDetail` obsoleto de `es.ts`, `LoginScreen` y perfil que aún leen `detail` como texto (`auth.py` fuera de D35), `churn_definicion` del contrato dice «Propuesta pendiente…», pantalla Bajas sin captura de evidencia (faltan datos de demostración), el diálogo de «Solicitar baja» solo advierte ante un bloqueo de vista previa, los tests que dependen del orden de ejecución (`test_sync_core_etl` en ciertas combinaciones), `--accent-primary` sin definir en `Staging.css`, regenerar la colección Postman si usa `operationId` de `/tch/*`.

## 14. Incidentes y errores cometidos

### Incidentes (de las sesiones anteriores)
- **Alembic sobre `crm` (2026-10-28):** un agente corrió `downgrade` y `upgrade` sobre la base real. Corrección: guarda anti-`downgrade` y regla 6.
- **Túneles públicos de Cloudflare** abiertos del 26 al 29 de octubre (USR-12: considerar rotar el secreto JWT de producción).
- **Datos personales en el contexto de un agente** al explorar reportes de Toku.

### Incidentes del Sprint 5A (2026-10-29)
- **VirtualPOS 2 y Payku sin sincronizar del 27 al 28 de octubre, sin alerta:** el commit `25eafac` (un solo `.env`) dejó sin credenciales útiles a esos canales y el run quedaba «completed». Corregido en código y con alertas; el usuario debe revisar su `.env`.
- **Un script de depuración de un agente (Ola 2A) se conectó a `crm`** porque tomó el `.env`: solo SELECT y un INSERT que falló, todo con rollback; nada escrito. Regla 3.
- **Un agente usó `git stash`** con otro activo (cambios restaurados). Prohibido.
- **Datos personales vistos por agentes:** direcciones en texto libre al perfilar un CSV de VirtualPOS y una fila de un socio impresa una vez en consola al leer encabezados de TCH (nada se escribió en el repo ni en documentos). Dos agentes abrieron una vez los Excel de TCH solo para confirmar encabezados con lista blanca.
- **Captura con nombres reales:** la lista de Socios del sandbox mostraba RUT y nombres de apariencia real; no se subió, se recortó la barra y se borraron las capturas completas. Regla 11.
- **`app/templates/reports/virtualpos.html`** con 1.408 nombres de clientes en el árbol de trabajo (ignorado por git): ficha D40.
- **Cortes por límite de sesión de la API** (3 veces); se reanudó a los agentes sin pérdida porque se commitea por tarea.
- **Regresión de errores en pantalla:** al pasar 154 `detail` del backend a `{code, message}` (D35), el frontend dejó de mostrar el mensaje y los reintentos de CSRF dejaron de funcionar con `invalid_csrf_token`. Pasó inadvertido porque las pruebas usaban respuestas simuladas; corregido en la Ola 11A con 30 pruebas nuevas.
- **Commit del paso 19 del frontend dentro de un commit de backend** (`a514645`) por el índice compartido; no se reescribió la historia. Regla 8.
- **Commits intermedios en rojo en el renombrado del backend:** el pedido mezclaba «renombrar los tests en commits aparte» y «commitear solo en verde»; el estado final es verde pero esos commits no sirven para bisecar. Pedir un commit por módulo.
- **Un archivo de respuestas JSON con las rutas de Windows mal escapadas** (heredoc de bash) y un directorio vacío `C:\tmp` creado por un agente (se puede borrar a mano).

### Tabla de errores y correcciones
(Los errores 1 a 27 de las sesiones anteriores siguen vigentes: medir qué cuenta cada campo antes de reportar una cifra, tests nunca contra `crm`, una sola sesión de pytest, verificar rutas nuevas tras cambios de backend, probar `.gitignore` desde cero, `git add` por ruta, no tomar la documentación del proveedor como cierta, validar el cuerpo y no solo el código HTTP, un GET con efectos no se reintenta, contrastar cada decisión de diseño con las decisiones de negocio vigentes, `npm run build` y no `tsc --noEmit`, una prueba «en seco» no ejercita el flujo real, no reiniciar el backend sandbox en mitad de un ciclo de capturas, etc.)

| # | Error | Corrección | Para no repetirlo |
|---|---|---|---|
| 28 | La Opción A de cambios de cobro y otras piezas se verificaron solo con simulaciones | Barrida real de pantallas contra el backend sandbox | Complementar los mocks con una pasada real tras cada refactor de contrato |
| 29 | Supuse que el backend de TCH pasaba «solo origen=cargo» | El agente mantuvo ambos orígenes porque el detalle de cargos existe solo en ~30 meses | Revisar el efecto sobre la conciliación antes de pedir un filtro estricto |
| 30 | Dejé el ETL Core automático **encendido por defecto** al aprobar una tanda | Lo pasé a apagado por defecto con test | Todo lo que escribe en `crm` nace apagado |
| 31 | Pedí commits «aparte» y «solo en verde» a la vez | Documentado | Un commit por módulo, con su test |
| 32 | Confié en que un agente de frontend no pisaría el índice | Reglas 8 y 7 | `git add` y `git commit` encadenados, y verificar `git show --stat HEAD` |
| 33 | Subí una captura sin mirarla primero | Se detectaron nombres a tiempo y se recortó | Mirar siempre la captura antes de subirla |

## 15. Archivos y documentos clave

- Plan y estado: `docs/tasks.md` y `docs/planning/auditoria-2026-10-29/PLAN.md` (más los 12 informes de esa carpeta, incluidas las auditorías de idioma). Estado técnico: `docs/memory/PROJECT_STATE.md`. Reglas para agentes: `AGENTS.md` y `CLAUDE.md`. Diseño visual: `DESIGN.md` (menú de un solo nivel con Bajas, tokens azul-gris, series violeta/índigo).
- **Runbook de pruebas en sandbox:** `docs/operations/sandbox-testing-and-decisions.md`.
- **Opción A:** `docs/designs/facturacion-gestionada-escenarios.md`, `app/services/{billing_plan,billing_apply,billing_requests,billing_renewal,charge_stats}.py`, `app/api/v1/routes/billing_changes.py`, `app/models/billing.py`, `frontend/src/features/billing/`.
- **Sprint 5A:** `docs/data/{status-history,rejection-details,exports,vp-reports,webhooks,alerts,tch-reload,toku-reports-load,dashboard-general,error-codes}.md`, `docs/designs/baja-cascada.md`, `docs/engineering/{appcore-extraction,i18n-frontend,identifiers-backend,summary-view,cancellations-ui,api-errors-ui}.md`.
- Código nuevo clave: `app/services/{status_events,status_history,vp_rejection_capture,toku_rejection_codes,toku_rejection_projection,toku_failed_payments,rejection_format,exporter,export_queries,vp_report_parser,vp_report_import,subscription_refresh,cancellation_requests,cancellation_apply,dashboard_general,webhook_intake,webhook_processor,targeted_reconcile,alerts,toku_report_signals,toku_report_lifecycle,core_etl_mark,sync_metrics}.py`, `app/scheduler/run_lock.py`, `app/api/v1/routes/{changes,export,imports,cancellations,dashboard}.py`, `scripts/etl_tch.py` (recarga), `scripts/maintenance/{import_vp_reports,import_toku_reports,toku_report_lifecycle,consolidate_baseline,project_toku_rejections,materialize_toku_failed_payments}.py`, `scripts/diagnostics/parity_check.py`, `scripts/sandbox/ephemeral_user.py`.
- Frontend: `frontend/src/i18n/`, `features/{summary,cancellations,tch,shared}/`, `components/{KpiCard,ChannelChart,Sidebar}.tsx`.
- Datos y reportes fuente: `docs/Reportes_*/` y `C:\Users\Usuario\Downloads\CRM_reportes\` (ignorados por git, con datos personales).

## 16. Archivos sin versionar que NO son nuestros

- `docs/designs/reconciliacion-identidad-socios.md` (documento del usuario; destino en DEC-08).
- `Sin título.canvas`, `Sin título 1.canvas`, `graphify-out/`, `knowledge/00 - Home/2026-10-06.md`.
- `docs/dashboardeinspiracion.png` (la imagen de referencia del usuario; en realidad es un WebP con extensión .png).
- Ignorados por git pero presentes: `docs/Reportes_*/` (reportes con datos personales) y `app/templates/reports/virtualpos.html` (D40).

## 17. Datos de prueba que quedaron en los sandboxes

- **VirtualPOS (cuenta 1):** `CT-CO-AUTO`, `CT-DUP1` y las suscripciones de la suite de contrato (ver sección de pruebas en `tests_contract/README.md`).
- **`crm_sandbox`:** datos sintéticos `DEMO-SUB-001` a `025` de la Opción A; clientes de VirtualPOS sandbox que parecen reales (no subir filas); migraciones `0042` a `0051` aplicadas, sin datos de bajas ni de eventos; usuarios `PW-*` solo durante una captura (se borran solos).
- **Toku (organización sandbox):** 34 clientes, 37 suscripciones y 41 invoices preexistentes; no se creó ni se borró nada.

## 18. Cómo trabajar con el usuario

- Escribe en **español** (con tildes). Es técnico y delega mucho, con control. Prefiere que el orquestador **divida el trabajo en tareas para subagentes**, los **verifique** (ruff, suites, build, lectura del código, barridas reales) y le resuma lo hecho con honestidad, admitiendo los errores.
- **Siempre alternativas con una recomendación**, y las preguntas y aprobaciones como **fichas en la Bandeja**. Responder «acepto la recomendada» no autoriza lo que el runbook reserva al usuario (producción, push o PR, borrado, credenciales, exposición a internet).
- **Sandbox sí, producción con cuidado.** Lo que puede afectar datos reales se avisa y se pide un «sí» explícito.
- Las decisiones de **negocio** son suyas; las de **mecánica** puede delegarlas con una recomendación. A veces elige distinto de la recomendada (D1, D4, D19, D33 y D34 lo fueron): se respeta tal cual.
- Idioma: visible en español, código en inglés, comentarios en español (reglas de la sección 2, punto 15).
- **Dos proyectos, dos sesiones:** esta es el CRM; vpbase va en la otra. Si la otra sesión pide algo de su Bandeja, se atiende de inmediato y sin mezclar.
- Mensajes de commit sin datos personales ni modelos, en archivos del scratchpad, con `git add` por ruta.

## 19. Primeros pasos recomendados para quien retome

1. Leer `docs/tasks.md` (§3.7 y §5) y este documento; `git status`, `git log --oneline -10` y confirmar la rama `sprint-5/sync-confiable` (sin remoto).
2. Verificar sin tocar nada: `GET /openapi.json` del backend sandbox (¿`/api/v1/cancellations`, `/dashboard/general`, `/export/{entity}`?), `alembic heads` leyendo los archivos (debe dar `20261029_0051`), `pytest -q` (2043 y 2 omitidas) y, en `frontend/`, `npm test` (1214), `npm run build` y `npm run lint`.
3. Preguntar al usuario por lo que lo bloquea (sección 13): respaldo y migraciones en `crm`, pepper de Toku y reportes, recarga de TCH, SMTP, D40 y los valores del catálogo.
4. Siguiente trabajo sin dependencias, en este orden: **REC-04** (backend, y luego su pantalla), **UX-09** (Cobros unificado), **SYNC-O-02/05/06/09** (ventanas y niveles). Cada tarea: delegar a un agente con prompt completo, exigir el test en rojo primero, verificar uno mismo con la suite, el build y, si hay interfaz, una barrida real en el sandbox con el usuario temporal.
5. Antes de cualquier prueba con escritura real, releer el [runbook](docs/operations/sandbox-testing-and-decisions.md) y la sección 2.
