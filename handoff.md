# Handoff: CRM SynkmetriX (estado al 2026-11-09, sprint S6)

Documento para quien retome el trabajo (persona o Claude). Léelo completo antes de tocar nada. No contiene secretos: las variables de entorno aparecen solo por nombre y las cifras de datos son agregadas (sin datos personales).

> **El plan y el estado de cada tarea viven en [`docs/tasks.md`](docs/tasks.md)** (tablero en §2, sprint activo S6 en §3.10, filas en §4 y las tareas de la auditoría del 2026-10-29 en §4.14). Este documento conserva lo que no cabe allí: reglas de trabajo, cómo levantar cada ambiente, el estado real de las bases, banderas, riesgos, incidentes y cómo trabajar con el usuario. Reescrito por completo el 2026-11-07 (DOC-13, ficha d162) y actualizado el 2026-11-09 con los PR #8 y #10; la versión anterior era del 2026-10-29 y describía una rama sin remoto y `crm` en `0041`.

## Índice

1. Estado en una mirada
2. Reglas de trabajo (leer primero)
3. Ambientes: cómo levantar cada uno y el túnel
4. Migraciones y estado de las bases
5. Banderas (todas apagadas por defecto)
6. Riesgos vigentes
7. Plan vigente (S6 a S8) y acciones del usuario
8. Incidentes y errores cometidos
9. Cómo funciona lo construido (mapa)
10. Hallazgos sobre los proveedores (medidos)
11. Decisiones de negocio vigentes
12. Archivos que no son nuestros y datos de prueba
13. Cómo trabajar con el usuario
14. Primeros pasos para retomar

## 1. Estado en una mirada

| Tema | Estado |
|---|---|
| Rama | **`master` al día en `65b21c9`** (local igual a `origin/master`). PR #6 (`sprint-5/sync-confiable`, sprints 4 y 5A y olas 1 a 7) integrado el 2026-11-04 (merge `fdf51bc`); PR #7 (test inestable de exportación) integrado el 2026-11-05. Abiertos sin integrar (2026-11-09): **PR #8** (`ops/bck-01a-respaldos`, BCK-01a, respaldos), **PR #9** (`docs/reconciliar-plan`, DOC-12 y DOC-13, este documento) y **PR #10** (`lote/l8-qa`, L8-QA y SEC-03). Las ramas `lote/*` y `sprint-*` ya están contenidas en `master` o son históricas |
| CI | **En verde** en `master` (corrida del merge del PR #7, 2026-11-05). La corrida del merge del PR #6 falló por el test inestable que arregló el PR #7. CI corre `ruff`, `pytest` contra PostgreSQL 17 con `alembic upgrade head`, `npm run lint`, `npm test` y `npm run build`; **no mide cobertura** (MET-01) |
| Pruebas | En `master`: backend 2.751 y frontend 1.381 en CI (cifras del plan revisado del 2026-11-05). Tras el PR #10: backend 2.759 (2 omitidas) y frontend 1.407 en su CI. No se volvieron a correr para escribir este documento |
| Migraciones | Head del código **`20261104_0071`**. `crm` (producción local) en **`0068`**: falta la `0071` (solo siembra el permiso de importar reportes de Payku). `crm_sandbox` en `0071` desde el 2026-11-04 (integración de L7-IMPORT; verificado por el orquestador) |
| Sprint activo | **S6** (2026-11-06 a 2026-11-13): plan fiel, producción segura y pedidos finales a terceros. Entrega a fines de noviembre (d153); congelamiento de código el 2026-11-21 (d158) |
| Producción | Local, un PC como servidor (d155). Backend 8000 y front 5173 sobre `crm`. Sin respaldo automatizado todavía (BCK-01a en PR #8); último respaldo manual: `crm_predeploy_D127_20261103_0039.dump` (2026-11-03, fuera del repositorio) |
| Bloqueado por el usuario | Ventana de despliegue (OPS-11): respaldo, `0071`, `seed_roles.py`, rotar el JWT, reinicio, recarga de TCH, backfill de Toku, SMTP. Además: pepper y reportes de Toku, usuarios por rol, mover el reporte con nombres (D40), enviar los pedidos a terceros |
| Bloqueado por terceros | 24 tareas: Payku (sandbox y preguntas Q-xx), Toku (eventos reales, webhooks, API de reportes) y VirtualPOS (tarjetas de prueba). Corte al cierre de S7 (d154) |

## 2. Reglas de trabajo (leer primero)

1. **Nunca mostrar ni copiar valores del `.env`.** Leer solo nombres de variables. Para modificarlo, scripts que no impriman nada. Existe una guarda de arranque que compara credenciales de sandbox con las de producción.
2. **Un solo `.env`.** No existe `.env.sandbox` en el backend (solo `frontend/.env.sandbox`, sin secretos: puerto y proxy de Vite). Con `APP_ENV=sandbox` la app usa **solo** las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL`. **`APP_ENV=development` equivale a producción** (`is_production` es verdadero y las guardas de sandbox no corren). Un valor desconocido de `APP_ENV` falla al arrancar. **Con el PR #10 (SEC-03), con `APP_ENV=sandbox` o `qa` es obligatoria `SANDBOX_AUTH_JWT_SECRET`** (al menos 32 caracteres y distinta de `AUTH_JWT_SECRET`): sin ella no arrancan el backend 8001, los scripts de sandbox, `tests_contract` ni el agente `sandbox-tester`. Al definirla se cierran las sesiones abiertas del sandbox.
3. **`crm` NO es el sandbox.** `crm` es la base local con datos reales de producción; el sandbox es `crm_sandbox` y solo se activa con `APP_ENV=sandbox` en el proceso. **Fijar `APP_ENV` y cualquier `DATABASE_URL` ANTES de importar `settings`**: `alembic/env.py` y los scripts leen `settings.database_url` al importar. Todo script de depuración debe fijar la base `_test` antes de importar y fallar cerrado si no termina en `_test` (o `sandbox` donde se autorice).
4. **Regla de oro del usuario: en sandbox sin problema; en producción siempre con el usuario y con más cuidado.** Ante la duda sobre qué ambiente es, se trata como producción (Toku comparte host con producción). Aprobado en el [runbook](docs/operations/sandbox-testing-and-decisions.md) (DEC-27). Las validaciones en sandbox las ejecuta el orquestador avisando (d104).
5. **Escrituras al proveedor solo en sandbox y solo con variables de proceso**, nunca dejando banderas encendidas en `.env`. Producción: todas apagadas.
6. **Ningún agente ejecuta la CLI de Alembic por su cuenta.** Las migraciones se prueban por pytest (`crm_test`). En `crm_sandbox` las aplica el orquestador avisando (DEC-28). En `crm` solo en una ventana de despliegue aprobada por el usuario en el chat, con respaldo previo verificado (así se hizo d127 el 2026-11-03). `alembic/env.py` bloquea todo `downgrade` sobre bases que no terminen en `_test` ni contengan `sandbox` o `qa`, salvo `ALEMBIC_ALLOW_DOWNGRADE=1`.
7. **Una sola sesión de pytest a la vez.** Todas recrean `crm_test` al arrancar. Un agente de backend y uno de frontend (solo `npm`) pueden correr en paralelo; dos de backend, no.
8. **`git add` siempre por ruta, y `git add` + `git commit` en una sola llamada encadenada.** El índice es compartido entre agentes. Verificar con `git show --stat HEAD`. Nunca `git add .`. Nunca `git stash` sin etiqueta con otros agentes activos. **Push y PR solo cuando el usuario lo pide o lo aprueba en una ficha.** Mensajes de commit en español, desde un archivo del scratchpad (`git commit -F`), terminados con la línea `Co-Authored-By` de la sesión.
9. **Verificar lo que reportan los agentes.** Releer los archivos, correr `ruff`, la suite y el build uno mismo. **Las pruebas con respuestas simuladas no detectan cambios de contrato:** complementar con una barrida real de pantallas contra el backend sandbox.
10. **Mirar la CI de `master`, no solo la suite local.** La CI estuvo en rojo del 20/10 al 04/11 sin que nadie lo notara (sección 8).
11. **No inferir el comportamiento del proveedor de su documentación.** Medirlo en el sandbox o con lecturas autorizadas (la de VirtualPOS se equivocó en 6 puntos).
12. **Datos personales:** ninguno en el repo, tests, logs, documentos, capturas subidas ni en el contexto de un agente. Los reportes de proveedores **no se abren por filas**: solo encabezados con una función que nunca imprima otra cosa, y conteos. Las capturas que salen del equipo (la Bandeja vive en claude.ai) solo del sandbox con datos `DEMO-`, sin filas con nombres; mirarlas antes de subirlas.
13. **Tipado del frontend:** `npx tsc --noEmit` casi no comprueba nada; la verificación real es `npm run build` (`tsc -b`).
14. Al usuario siempre **alternativas con una recomendación**, y las preguntas y aprobaciones como **fichas en la Bandeja de decisiones** (sección 13). Lo que toca producción, permisos, migraciones, borrado, credenciales, exposición a internet o negocio es del usuario y se confirma además en el chat.
15. **Reglas de idioma (D32 a D38):** lo visible va en español, incluidos los valores (catálogo `frontend/src/i18n/es.ts` y `label()`); los identificadores de código van en inglés; la base conserva sus nombres; las claves JSON de la API siguen en español; comentarios en español; errores del backend como `{code, message}` (catálogo en `docs/data/error-codes.md`). Detalle: `docs/engineering/identifiers-backend.md` e `i18n-frontend.md`.
16. **Banderas apagadas por defecto:** todo lo que escribe en `crm` o llama a proveedores nace apagado (sección 5). Encender una es decisión del usuario, tras respaldo y una primera corrida manual (D26), y de a una.
17. **Mantener el plan al día (d117):** al integrar cada ola o lote, actualizar las filas de `docs/tasks.md` y correr el chequeo de desfase (regla 8 de su §1.4). Las fichas de la Bandeja desde la d101 se escriben en minúscula (`d127`); `D1` a `D100` son las fichas anteriores; `DEC-xx` son las decisiones de `tasks.md` (§1.2).
18. **Sesiones separadas:** esta sesión es solo del **CRM Proyecto Título**. Lo de **vpbase** lo lleva otra sesión. No mezclar.
19. **Límites de sesión de la API** pueden cortar a los agentes: commitear por tarea y solo en verde; al reanudar, revisar `git status` y `git diff`.

## 3. Ambientes: cómo levantar cada uno y el túnel

| Pieza | Puerto | Base | Comando (desde la raíz) |
|---|---|---|---|
| PostgreSQL 17 | 5433 | `crm`, `crm_sandbox`, `crm_test` | `docker compose up -d` (servicio `postgres` de `compose.yaml`, volumen `postgres_data`) |
| Backend producción | 8000 | `crm` | `.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000` (con `--reload` si se está desarrollando) |
| Front producción | 5173 | — | `cd frontend; npm run dev` (proxy `/api` a `127.0.0.1:8000`) |
| Backend sandbox | 8001 | `crm_sandbox` | `scripts/run_sandbox_backend.ps1` (fija `APP_ENV=sandbox`; **sin recarga automática**; scheduler apagado por defecto con `SANDBOX_SCHEDULER_ENABLED=false`; con el PR #10 exige `SANDBOX_AUTH_JWT_SECRET` en el `.env`, regla 2) |
| Front sandbox | 5174 | — | `cd frontend; npm run dev:sandbox` |

- **Orden para levantar:** PostgreSQL, luego backend, luego front. Comprobar `GET /health` y, tras cambios de backend, `GET /openapi.json` (rutas nuevas). Los backends no recargan solos si se arrancan sin `--reload`.
- **Producción después de la ventana de S6:** el backend 8000 debe reiniciarse **después** de aplicar la `0071` y `seed_roles.py`, y después de rotar el JWT (todas las sesiones se cierran; avisar antes).
- **Instancia de PostgreSQL (verificado por el orquestador):** `crm`, `crm_sandbox` y `crm_test` viven en el contenedor Docker `crm_projectotitulo-postgres-1` (servicio `postgres` de `compose.yaml`, puerto 5433, volumen `postgres_data`). El servicio de Windows `postgresql-x64-18` es otra instalación, manual y sin uso: lo que dice la ficha d101 sobre él está superado. Respaldos y restauraciones van siempre contra el contenedor.
- **Túnel (solo sandbox, d101):** `cloudflared tunnel --url http://localhost:5174` (túnel rápido de trycloudflare, URL aleatoria, protegido solo por el login, datos sintéticos `DEMO-`). Se apaga al terminar: `Get-Process cloudflared` y `Stop-Process`. **Nunca hacia producción (d150)**: expone datos reales y el JWT aún no se rota. El túnel nombrado solo para `/api/v1/webhooks/*` (D8) nunca se creó; requiere cuenta y dominio de Cloudflare.
- **Pruebas:** backend `$env:PYTHONPATH='.'; .venv\Scripts\pytest.exe -q --basetemp=<scratchpad>\pt` (el `--basetemp` evita los `PermissionError` de `%TEMP%\pytest-of-Usuario`); lint `.venv\Scripts\ruff.exe check app tests alembic scripts`; frontend (en `frontend/`) `npm test`, `npm run build`, `npm run lint`. Alternativa equivalente si un lanzador falla: `.venv\Scripts\python.exe -m pytest ...` y `.venv\Scripts\python.exe -m ruff check ...`. Los lanzadores del venv (`pytest.exe`, `ruff.exe`, etc.) se regeneraron el 2026-11-10 tras mover el repositorio a `Downloads\Proyectos` (traían la ruta antigua). En un worktree sin `.env`, la suite de contrato toma la ruta del `.env` principal desde `CRM_DOTENV_PATH` (variable de proceso).
- **Capturas con usuario temporal (D21):** `.venv\Scripts\python.exe scripts\sandbox\ephemeral_user.py session -- node scripts\visual\capture_sandbox.mjs autologin --capture [...]`. Crea un usuario `PW-…` en `crm_sandbox`, captura y lo borra; se niega si la base no es `crm_sandbox`. Capturas e índice en el scratchpad. Playwright vive fuera del repo (`scripts/visual/README.md`, `PLAYWRIGHT_NODE_DIR`).
- **Recorrido «desde cero» (DOC-13, pendiente de verificar en limpio, meta menos de 30 minutos):** clonar; crear `.venv` con Python 3.14 e instalar `requirements.lock`; copiar `.env.example` a `.env` y completar solo lo necesario para `crm_test`; `docker compose up -d`; `pytest -q` (crea y migra `crm_test`); en `frontend/`, `npm ci` y `npm test`.
- **Particularidades de Windows/PowerShell:** el validador de comandos bloquea patrones inocentes (`Remove-Item` con rutas que empiezan por `C:`, ciertas regex); usar `[System.IO.File]::Delete($ruta)` y escribir scripts con la herramienta de archivos. Git avisa de «LF will be replaced by CRLF»: es configuración.
- Skill y agentes personales (no versionados) en `C:\Users\Usuario\.claude\`: skill `sandbox-orchestrator`, agentes `sandbox-tester` y `decision-maker`.

## 4. Migraciones y estado de las bases

| Base | Revisión | Notas |
|---|---|---|
| `crm` (producción local) | **`20261103_0068`** | Migrada de `0041` a `0068` el 2026-11-03 (d127) con `seed_roles.py` (soporte 36 permisos, ejecutivo 35) y respaldo previo verificado con `pg_restore --list`. Verificado entonces: un solo head, sin `core_charges` con el source antiguo «virtualpos», 0 de 9.028 `vp_subscriptions` con monto NULL. **Pendiente: `0071`** en la ventana de S6 (OPS-11). Las tablas de reportes de Toku siguen vacías hasta cargar pepper y reportes (TK-PAR-01). La recarga completa de TCH (d121) no se ha hecho |
| `crm_sandbox` | `20261104_0071` (desde el 2026-11-04, integración de L7-IMPORT; verificado por el orquestador) | Datos de VirtualPOS sandbox (cuenta 1) y sintéticos `DEMO-`. **Contiene datos personales reales** (QA-04, informe de QA del 2026-11-05: un cliente de VirtualPOS creado contra el sandbox con datos de una persona real y luego sincronizado; decisión del usuario pendiente en la ficha d163). Mientras tanto rige la regla 14 del [runbook](docs/operations/sandbox-testing-and-decisions.md) (PR #10): tratarla como base con datos personales y no subir capturas con filas |
| `crm_test` | Se recrea en cada sesión de pytest | Solo para pruebas |

- Cadena de migraciones desde la `0051`: `0052 → 0056 → 0057 → 0055 → 0053 → 0054 → 0062 → 0063 → 0059 → 0060 → 0061 → 0066 → 0064 → 0065 → 0068 → 0071`. Números fuera de orden y huecos (`0058`, `0067`, `0069`, `0070`): la cadena es lineal y válida; **no se renombran** (no se editan migraciones históricas).
- La `0061` (tipos en `vp_*`) bloquea esas tablas varios minutos: ya está aplicada en `crm`. La `0071` es liviana.

## 5. Banderas (todas apagadas por defecto)

Valores por defecto según `.env.example`. **El `.env` real no se leyó para escribir esto**: confirmar con el usuario antes de suponer que alguna sigue apagada en producción.

| Grupo | Banderas | Para encenderla |
|---|---|---|
| Escrituras a proveedores | `VIRTUALPOS_WRITES_ENABLED`, `TOKU_WRITES_ENABLED`, `PAYKU_WRITES_ENABLED` y sus `*_SANDBOX_WRITES_ENABLED`; Toku exige además `TOKU_SANDBOX_ALLOW_WRITES_ARMED=1` en el proceso; `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` (WR-VP-05) | Solo sandbox con variables de proceso; en producción, prueba controlada y decisión del usuario |
| Sync y consolidación | `SYNC_CORE_ETL_ENABLED` (D26), `SYNC_WINDOWED_READS_ENABLED`, `CONSOLIDATION_DIFFERENTIAL_ENABLED`, `SYNC_TIERS_ENABLED`, `SYNC_REMOVAL_DETECTION_ENABLED` | Respaldo, corrida manual por canal y revisión. d129 aprobó probar una semana en sandbox la consolidación diferencial, los niveles y las lecturas por ventana antes de encenderlas en producción; la sync caliente depende de DEC-03 (abierta) |
| Rechazos y señales | `VP_REJECTION_CAPTURE_ENABLED`, `TOKU_REPORT_SIGNALS_ENABLED`, `TOKU_MATERIALIZE_FAILED_PAYMENTS` | Tras cargar reportes y revisar conteos |
| Webhooks | `WEBHOOK_PROCESSOR_ENABLED`, `TARGETED_RECONCILE_ENABLED` | Requieren URL pública fija (túnel nombrado o hosting), hoy fuera de alcance |
| Alertas | `ALERTS_ENABLED`, `ALERT_BUSINESS_ENABLED`, `ALERT_REPORT_AGE_ENABLED`, `ALERT_WRITE_FAILED_ENABLED` (más `ALERT_SMTP_*`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`) | En la ventana de S6, con correo de prueba (d137 a d140); los destinatarios nunca van al repo |
| Controles de billing y paridad | `BILLING_CONSISTENCY_CHECK_ENABLED`, `BILLING_SWEEP_HEARTBEAT_ENABLED`, `VP_PARITY_CHECK_ENABLED` | Tras la primera corrida manual |
| Sandbox | `SANDBOX_SCHEDULER_ENABLED` | Solo si se necesita el scheduler en sandbox |

Peppers opcionales sin valor en `.env.example`: `TOKU_REPORT_HASH_PEPPER` (obligatorio para importar reportes de Toku) y `VP_REPORT_HASH_PEPPER`.

## 6. Riesgos vigentes

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | Pérdida de datos: `crm` vive en un volumen Docker de un solo PC, sin respaldo automático | BCK-01a (PR #8) con copia cifrada en disco externo y nube (d156) y simulacro en `crm_restore_test`; primer respaldo antes de cualquier otro paso de la ventana |
| 2 | La memoria y la defensa compiten con correcciones | DOC-14 continua desde S6; congelamiento el 2026-11-21 (d158) |
| 3 | Datos personales expuestos (reportes, la plantilla de D40 con 1.408 nombres, capturas, demo, contexto de agentes); Ley 21.719 vigente desde el 2026-12-01 | SEC-01; mover el archivo de D40; demo en vivo sobre producción **solo con el modo que enmascara datos (SEC-02, d161)** |
| 4 | JWT de producción posiblemente expuesto por los túneles del 26 al 29 de octubre (USR-12) | Rotarlo en la ventana de la `0071` (d157); nunca túnel a producción (d150). El secreto compartido entre producción y sandbox queda resuelto con SEC-03 en el PR #10 (`SANDBOX_AUTH_JWT_SECRET`), al integrarlo |
| 5 | Terceros que no responden dejan 24 tareas abiertas | TER-01 con fecha en S6 y corte al cierre de S7 (d154) |
| 6 | Documentación desfasada | Chequeo de desfase al integrar cada ola (d117) |
| 7 | Demo en vivo que falla | Guion, ensayos y video de respaldo (DOC-15) |
| 8 | Encender banderas sin respaldo | De a una, tras respaldo y corrida manual (D26); en la ventana de S6 solo alertas |
| 9 | Deuda técnica (numeración de migraciones, ~100 literales de TCH, tests dependientes del orden, `apiDetail`) | Solo lo que afecte la demo o la medición; el resto se declara en la memoria |

## 7. Plan vigente (S6 a S8) y acciones del usuario

Detalle y definición de hecho en `docs/tasks.md` §3.9 a §3.12.

- **S6 (2026-11-06 a 2026-11-13).** Equipo: DOC-12 y DOC-13 (esta reconciliación, PR #9), BCK-01a (PR #8, con tres correcciones menores pendientes de la revisión del 2026-11-09), L8-QA (PR #10: hallazgos altos y medios QA-01 a QA-16 del informe de QA del sandbox del 2026-11-05, más SEC-03), SEC-01, TER-01, SYNC-01, TK-PAR-04 (dry-run en sandbox), DOC-14 (esqueleto de la memoria). Quedan para otro lote los hallazgos bajos QA-17 a QA-30. Del usuario, fuera de la ventana: la decisión sobre QA-04 (datos personales reales en `crm_sandbox`, ficha d163) y definir `SANDBOX_AUTH_JWT_SECRET` antes de reiniciar el 8001 con el PR #10.
- **Sandbox de Payku:** las variables `PAYKU_SANDBOX_BASE_URL`, `PAYKU_SANDBOX_PUBLIC_TOKEN` y `PAYKU_SANDBOX_PRIVATE_TOKEN` existen pero están vacías; las llena el usuario cuando Payku entregue el sandbox (USR-04). Mientras tanto Payku sigue deshabilitado en sandbox. Ojo: Payku **no tiene guardas de escritura duras como Toku** (`app/integrations/toku/write_guard.py`); solo la bandera `PAYKU_WRITES_ENABLED` / `PAYKU_SANDBOX_WRITES_ENABLED`, así que cualquier escritura de prueba exige la misma cautela que en producción.
- **S7 (2026-11-14 a 2026-11-21, congelamiento al cierre).** MET-01 (cobertura en CI), MET-02 (métricas desde tablas existentes, d159), MET-03 (2 a 3 sesiones con SUS, d160), SEC-02 (modo demo con datos enmascarados, antes del congelamiento), UX-16, DOC-15; corte de terceros.
- **S8 (2026-11-22 hasta la entrega a fines de noviembre).** DOC-14, DOC-16, correcciones de defectos y dos ensayos.

**Ventana de despliegue del usuario (OPS-11), en este orden y con verificación en cada paso:**
1. Respaldo de `crm` con BCK-01a (o `docker compose exec postgres pg_dump -Fc` si el PR #8 no está integrado) y verificación con `pg_restore --list`.
2. `alembic upgrade head` en `crm` (`0068 → 0071`) y `scripts/maintenance/seed_roles.py`.
3. Rotar `AUTH_JWT_SECRET` (USR-12; cierra todas las sesiones, avisar antes) y reiniciar el backend 8000.
4. Recarga de TCH (`docs/data/tch-reload.md`: dry-run con `--exclude-months` de 2023, apply con `--confirm-database crm`, ETL Core de TCH y `scripts/diagnostics/parity_check.py --channel tch`).
5. Backfill de señales de Toku (TK-PAR-04) tras su dry-run, y pepper y reportes nuevos de Toku (TK-PAR-01).
6. Variables SMTP y destinatarios (d140), `ALERTS_ENABLED=true` y un correo de prueba.
7. Usuarios por rol (USR-07); mover `app/templates/reports/virtualpos.html` fuera del proyecto (D40); enviar los pedidos de TER-01. VP-PAR-12 (limpieza de huérfanos) solo con aprobación explícita.

Rescate: si un paso falla, restaurar el respaldo del paso 1.

## 8. Incidentes y errores cometidos

### Recientes (2 al 9 de noviembre)
- **CI en rojo desde el 20/10 sin que nadie lo notara.** Al abrir el PR #6 aparecieron cuatro causas: (1) `.python-version` decía `3.14.5`, que no existe para el runner de Ubuntu 26.04: pasó a `3.14` (`882f5bc`); (2) los paneles de sync formateaban los números sin idioma (en inglés salía «1,234»): ahora es-CL (`882f5bc`); (3) **74 tests perdían la cookie `Secure`** porque el cliente de pruebas usaba `http://`: ahora usan `https://testserver` sin tocar la app (`c5ae5c4`); (4) `test_health` y `test_payku_client` dependían del `.env` local (`c5ae5c4`).
- **Test inestable en `master`:** la corrida de CI del merge del PR #6 falló en `export.integration` porque el test usaba el campo «Monto mínimo» antes de que apareciera. Corregido con una espera explícita (`d278aee`, PR #7). Desde entonces la CI de `master` está en verde.
- **Documentación desfasada unos 175 commits desde el 2026-10-30 (411 en total en el PR #6)** pese a d117; corregido en DOC-12 y DOC-13 (este documento).
- **Test de foco de billing inestable:** en la CI del PR #9 falló una vez `billing.ui.test.tsx` («el foco entra al dialogo y vuelve al cerrar con Escape»), sin relación con el cambio (solo documentación). Corregido con esperas amplias en `36cd115`, dentro del PR #10; hasta integrarlo puede volver a fallar en otros PR.
- **Despliegue de `crm`** (d127, 2026-11-03): sin incidentes; hecho por el orquestador con autorización en el chat y respaldo previo.

### Anteriores (resumen; detalle en `docs/tasks.md` §7.2)
- **Alembic sobre `crm` (2026-10-28):** un agente corrió `downgrade` y `upgrade` sobre la base real. Respuesta: guarda anti-`downgrade` (OPS-10) y regla 6.
- **Túneles públicos de Cloudflare** del 26 al 29 de octubre sobre producción y sandbox (USR-06 los apagó; USR-12 pendiente).
- **VirtualPOS 2 y Payku sin sincronizar** del 27 al 28 de octubre sin alerta (commit `25eafac`); corregido en código y con alertas.
- **Datos personales en el contexto de agentes** al explorar reportes de Toku, TCH y un CSV de VirtualPOS (nada escrito en el repo); captura con nombres de apariencia real detectada antes de subirla.
- **Índice de git compartido** (un commit de frontend dentro de uno de backend, `a514645`) y un `git stash` con otro agente activo.
- **Regresión de errores en pantalla** al pasar el backend a `{code, message}`: invisible para las pruebas con mocks; corregida con 30 pruebas nuevas.

### Errores y correcciones que siguen vigentes
Medir qué cuenta cada campo antes de reportar una cifra; tests nunca contra `crm`; una sola sesión de pytest; verificar rutas nuevas tras cambios de backend; `git add` por ruta; no tomar la documentación del proveedor como cierta; validar el cuerpo y no solo el código HTTP; `npm run build` y no `tsc --noEmit`; todo lo que escribe en `crm` nace apagado; un commit por módulo con su test; mirar cada captura antes de subirla; mirar la CI de `master`.

## 9. Cómo funciona lo construido (mapa)

- **Opción A (cambios de cobro de VirtualPOS):** `app/services/{billing_plan,billing_apply,billing_requests,billing_renewal,charge_stats}.py`, `app/api/v1/routes/billing_changes.py`, `app/models/billing.py`, `frontend/src/features/billing/` (bandeja en `/general/cambios-de-cobro`). Horizonte de 12 meses; crear todos los cobros nuevos antes de cancelar los antiguos, uno por uno; lock por suscripción; compensación; DEC-30 resuelta (d102): el mes atrasado se reemplaza con fecha «mañana» atribuido por `internal_code` (BILL-18). Controles de consistencia (BILL-10) y allowlist del piloto (BILL-09) en código. **Nada se probó contra el proveedor real:** BILL-11 y BILL-12 esperan tarjetas (DEC-09). Diseño: `docs/designs/facturacion-gestionada-escenarios.md`.
- **Recuperador general** `/general/recuperador` con pestañas VirtualPOS, Toku, TCH y Payku (REC-03 a REC-06; definiciones en d119 y d125).
- **Vistas unificadas** de Cobros, Suscripciones y Socios (UX-08 a UX-10) y **Resumen** `/central/resumen` (`GET /api/v1/dashboard/general`, churn unificado D31). «Socios» sigue agrupado por RUT: Socios sobre Core (UX-11) es trabajo futuro.
- **Bajas multicanal y cambio de monto** `/general/bajas` (MGT-07 a MGT-16; `docs/designs/baja-cascada.md`); Toku por PAUSED o `end_date` y negada con facturas en cobro; tareas manuales que el ejecutivo puede confirmar (d136).
- **Importación de reportes** en un panel unificado de Administración (d151): PAT de VirtualPOS (`docs/data/vp-reports.md`), Toku (`docs/data/toku-reports-load.md`), Payku (L7-IMPORT) y Excel de TCH (`docs/data/tch-reload.md`, archivos cargados TCH-PAR-11).
- **Sync:** lock atómico, lectura por ventanas, consolidación diferencial, niveles caliente, tibio y frío, histórico reanudable, bajas por desaparición, métricas por fase (`docs/data/sync-idempotency.md`).
- **Historial de estados y glosas:** `status_change_events` (`docs/data/status-history.md`), `payment_rejection_details` y motivo de rechazo siempre en texto (`docs/data/rejection-details.md`, d143).
- **Webhooks y tiempo real:** cola `webhook_events`, procesador y reconciliación dirigida (`docs/data/webhooks.md`, `docs/operations/webhooks-runbook.md`); SSE con respaldo de polling (D9, OPS-09).
- **Alertas por correo:** `docs/data/alerts.md`.
- **Exportación CSV** en streaming y en segundo plano para listados grandes (`docs/data/exports.md`, EXP-06).
- **Gráficos:** sistema único sobre Recharts con tokens `--series-N` y `KpiCard` v2 (VIZ, d109).
- **Toku:** guardas de escritura (`app/integrations/toku/write_guard.py`), señales de recuperabilidad desde reportes (TK-20), «suscripción activa efectiva» para MRR y ARPU (TK-13, d118).

## 10. Hallazgos sobre los proveedores (medidos)

| Afirmación de la documentación de VirtualPOS | Realidad |
|---|---|
| `POST /v3/charge` falla con E-113 en planes MONTO_FIJO | **Se acepta** |
| Los errores llegan con HTTP 400 | Llegan con **HTTP 200** y cuerpo `{"status":"NOK",...}` |
| `internal_code` evita duplicados (E-086) | **No** |
| Filtros `charge_date_from/to` en `/charges` | **Se ignoran** |
| Cargo manual en un mes con automático pendiente | **Conviven ambos** (doble cobro si no se cancela el automático) |

- VirtualPOS: `GET /v3/suscription/{id}/charges?status=rechazado` trae `rejected_object` por cobro y `payment.order.uuid`; `/payment/{uuid}/attempts` responde 200 en producción y 403 en sandbox.
- Toku: el sandbox usa la misma URL base que producción con otra llave; sin transacciones ni medios de pago; la API no entrega estado de suscripción ni de medio de pago (por eso los reportes del Backoffice).
- Payku: sin sandbox ni credenciales; histórico de transacciones no certificable (DEC-10).

## 11. Decisiones de negocio vigentes

1. Más de 6.000 suscripciones VirtualPOS en `MONTO_FIJO`: no se cambian planes ni se pide de nuevo la tarjeta; VirtualPOS sigue creando los cobros mensuales.
2. El monto de la suscripción es `monto_vigente` (último cobro pagado o procesando).
3. Rechazos: el CRM no crea cobros ni suspende; solo reintenta; la racha (3 o más cuotas) es ayuda de solo lectura. «Recuperable» = racha, tarjeta bloqueada o vencida.
4. Aprobaciones de cambios de cobro: solo admin, con autoaprobación auditada; bajas: jefatura solicita, admin o jefatura aprueban (D12).
5. Un solo universo de «rechazo»; churn unificado (D31); sin metas por ahora (d109).
6. Exportación con datos personales solo admin y jefatura (D22).
7. **Plan post-MVP (d153 a d162):** entrega a fines de noviembre; corte de terceros al cierre de S7; operación local con un PC como servidor; respaldo en disco externo y nube cifrada; JWT rotado en la ventana de la `0071`; congelamiento el 2026-11-21; métricas desde tablas existentes; 2 a 3 sesiones con usuarios más SUS; demo en vivo sobre la producción local con datos enmascarados.
8. El resto de las decisiones del Sprint 5A (D1 a D40) está en `docs/planning/auditoria-2026-10-29/PLAN.md` §5.1.

## 12. Archivos que no son nuestros y datos de prueba

- Sin versionar, del usuario: `Sin título.canvas`, `Sin título 1.canvas`, `graphify-out/`, `knowledge/00 - Home/2026-10-06.md`, `docs/dashboardeinspiracion.png`. `docs/designs/reconciliacion-identidad-socios.md` se versiona como propuesta por d111 (pendiente de hacerlo). En el checkout principal hay además 3 snapshots de Vitest modificados solo por fin de línea (desfase D-12 del plan revisado): no commitearlos sin revisar.
- **Reportes de proveedores: ubicación única** `C:\Users\Usuario\Downloads\Proyectos\CRM_reportes\{VirtualPOS,TCH,Toku,Payku}` (con datos personales; fuera del repo). Desde el 2026-11-13 (ficha d203, ORD-01) las copias duplicadas que había en `docs/Reportes_*/` se movieron a cuarentena (`Downloads\_cuarentena_duplicados_2026-11-13\`, con `MANIFIESTO.csv` para restaurar) y ya no deben usarse; el código no dependía de esas carpetas. `docs/Reportes_*/` sigue en `.gitignore` por si reaparecen. Inventario: `Downloads\inventario_reportes_2026-11-13.csv`.
- Ignorados por git pero presentes en el checkout principal: `app/templates/reports/virtualpos.html` (1.408 nombres reales; D40 decidió moverlo fuera del proyecto, acción del usuario pendiente).
- Datos de prueba: VirtualPOS sandbox (cuenta 1) con `CT-CO-AUTO`, `CT-DUP1` y las suscripciones de la suite de contrato (`CONTRACT_VP_SUB_VARIABLE` = `efc751c04e`: ACTIVA, plan `MONTO_VARIABLE`, con cargos; elegida el 2026-11-10 por descubrimiento de solo lectura descartando las de cliente con correo de aspecto real, QA-04; se pasa solo como variable de proceso); `crm_sandbox` con `DEMO-SUB-001` a `025` y Excel sintéticos de TCH; organización sandbox de Toku con 34 clientes, 37 suscripciones y 41 invoices preexistentes (no se creó ni se borró nada).

## 13. Cómo trabajar con el usuario

- Escribe en **español** (con tildes). Es técnico y delega mucho, con control. Prefiere que el orquestador divida el trabajo en tareas para subagentes, **los verifique** y le resuma con honestidad, admitiendo los errores.
- **Siempre alternativas con una recomendación**; las preguntas y aprobaciones van como **fichas en la Bandeja de decisiones** (artifact privado en claude.ai, colección `decisions`, leída y escrita con `ArtifactData`; el estado de verificación por tarea vive en la colección `crm_tareas`). Las críticas nunca se aprueban en lote y se confirman además en el chat. Cada ficha resuelta con un cambio visible lleva capturas solo del sandbox.
- **Sandbox sí, producción con cuidado.** Lo que puede afectar datos reales se avisa y se pide un «sí» explícito. «Acepto la recomendada» no autoriza lo que el runbook reserva al usuario.
- Las decisiones de **negocio** son suyas; las de **mecánica** puede delegarlas. A veces elige distinto de la recomendada (por ejemplo d161: demo sobre producción en lugar de sandbox): se respeta tal cual.
- **Dos proyectos, dos sesiones:** esta es el CRM; vpbase va en la otra.

## 14. Primeros pasos para retomar

1. Leer `docs/tasks.md` (§2, §3.10 y §4.14) y este documento. `git switch master`, `git pull`, `git log --oneline -10` y `gh pr list` (¿siguen abiertos los PR #8, #9 y #10?).
2. Verificar sin tocar nada: CI de `master` en verde (`gh run list --branch master --limit 3`); `alembic heads` leyendo los archivos (debe dar `20261104_0071`); en local, `pytest -q --basetemp=<scratchpad>\pt`, y en `frontend/`, `npm test`, `npm run build` y `npm run lint`.
3. Correr el chequeo de desfase de `docs/tasks.md` (§1.4, regla 8). Si sale algo nuevo, actualizar la fila antes de seguir.
4. Preguntar al usuario, por la Bandeja, por la ventana de despliegue (sección 7) y por la fecha exacta de entrega y el formato de la universidad (d153 no trae nota).
5. Siguiente trabajo del equipo, en este orden: aplicar las tres correcciones de BCK-01a e integrarlo (PR #8, con su simulacro en `crm_restore_test`); integrar L8-QA (PR #10) avisando antes al usuario de `SANDBOX_AUTH_JWT_SECRET`; SEC-01; TER-01 (redactar los pedidos para que el usuario los envíe); esqueleto de la memoria (DOC-14); luego, en S7, SEC-02 antes del congelamiento, MET-01 y MET-02.
6. Antes de cualquier prueba con escritura real, releer el [runbook](docs/operations/sandbox-testing-and-decisions.md) y la sección 2.
