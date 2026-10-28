# Handoff: CRM SynkmetriX (sesión de sprints 0 a 4, 26 al 28 de octubre de 2026)

Documento para quien retome el trabajo (persona o Claude). Léelo completo antes de tocar nada. No contiene secretos: las variables de entorno aparecen solo por nombre.

## 1. Estado en una mirada

| Tema | Estado |
|---|---|
| Sprints 0 a 3 | Completos en código, subidos al remoto |
| Sprint 4 | Completo en código. Falta: PK-05 (Payku), verificación visual y cerrar la opción A (solicitud y aprobación) |
| Sprints 5 y 6 | Solo planificados (ver sección 8) |
| Ramas | `sprint-0/onboarding`, `sprint-1/auditoria-datos`, `sprint-2/componentes-kpis`, `sprint-3/graficos-sidebar`, `sprint-4/recuperador-vp`. Cada una contiene a la anterior. Tip de sprint-4: `5278507` |
| PR | **No hay ningún PR abierto.** `master` local está 1 commit adelante de `origin/master` (el plan de sprints) y no se subió |
| Pruebas | Suite normal: 542 tests (`pytest -q`, ~12 s, base `crm_test`). Contrato VirtualPOS: 17 pruebas. Frontend: 92 tests (`npm test`). `ruff` limpio |
| Migraciones | Head `20261021_0036`. No creamos migraciones nuevas |
| Bloqueado por terceros | Soporte de Payku (sandbox y 5 preguntas), tarjetas de rechazo para pruebas |

## 2. Reglas de trabajo (leer primero)

1. **Nunca mostrar ni copiar valores del `.env`.** Leer solo nombres de variables. Para modificarlo, scripts que no impriman nada. Existe una guarda de arranque que compara credenciales de sandbox con las de producción.
2. **Un solo `.env`.** No existe `.env.sandbox` (solo `frontend/.env.sandbox`, sin secretos: puerto y proxy de Vite). Con `APP_ENV=sandbox` la app usa **solo** las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL`.
3. **Escrituras al proveedor solo en sandbox y solo con variables de proceso**, nunca dejando las banderas encendidas en `.env`: `VIRTUALPOS_SANDBOX_WRITES_ENABLED=true` y `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN=true`. Producción: ambas apagadas.
4. **Una sola sesión de pytest a la vez.** Todas recrean `crm_test` al arrancar; dos en paralelo producen fallos falsos.
5. **`git add` siempre por ruta.** Nunca `git add docs` ni `.`: hay archivos ajenos sin versionar (ver sección 11).
6. **Verificar lo que reportan los agentes.** Releer los archivos, correr ruff y la suite uno mismo. Varias veces el reporte de un agente fue optimista o incompleto.
7. **No inferir el comportamiento del proveedor de su documentación.** Medirlo en el sandbox con la suite de contrato (la documentación de VirtualPOS se equivocó en 6 puntos).
8. Scripts temporales y respaldos van fuera del repositorio (carpeta de scratchpad de la sesión). No dejar copias de `.env` en el árbol.
9. Los mensajes de commit terminan con la línea `Co-Authored-By` que indique la sesión. No se hace push ni se abren PR sin que el usuario lo pida.

## 3. Cómo levantar todo (local, Windows/PowerShell)

| Pieza | Puerto | Comando (desde la raíz) |
|---|---|---|
| Backend producción | 8000 | `.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload` |
| Front producción | 5173 | `cd frontend; npm run dev` |
| Backend sandbox | 8001 | `scripts/run_sandbox_backend.ps1` (fija `APP_ENV=sandbox`) |
| Front sandbox | 5174 | `cd frontend; npm run dev:sandbox` |

- **El `--reload` del backend 8000 falló en silencio** (el proceso era del 24 de octubre y no tenía ninguna ruta nueva). Tras cambios de backend, comprobar `GET /openapi.json` o reiniciar a mano.
- Bases de datos locales, mismo PostgreSQL (puerto 5433): `crm` (datos locales de producción), `crm_sandbox`, `crm_test` (se destruye y recrea en cada sesión de pytest; no usar para nada más).
- Para correr algo contra el sandbox: `$env:APP_ENV='sandbox'` antes del comando; migraciones: `alembic upgrade head` con esa variable.
- Selector de ambiente (panel Administración, al final de la página): usa `SANDBOX_APP_URL` y `PRODUCTION_APP_URL`. Con túneles hay que pasar las URLs públicas como variables de proceso al reiniciar.
- Túneles de Cloudflare (`cloudflared tunnel --url http://localhost:5173` y `:5174`): **son públicos y solo los protege el login**. Se dejaron abiertos durante las pruebas; apagarlos al terminar (`Stop-Process -Id <pid>`; buscar con `Get-Process cloudflared`). Las URLs cambian en cada arranque.
- Tests normales: `PYTHONPATH=. .venv\Scripts\pytest.exe -q`. Frontend: `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`.
- Suite de contrato contra el sandbox: ver `tests_contract/README.md` (exige `APP_ENV=sandbox`, `CONTRACT_TESTS=1`, `CONTRACT_WRITES=1`, flags de sandbox y los ids `CONTRACT_VP_SUB_FIXED` / `CONTRACT_VP_SUB_VARIABLE`). Genera `reports/contract/virtualpos/drift-*.md` (ignorado por git).
- Roles en la base: `admin`, `coordinador`, `jefatura`, `soporte` (en `crm`); `admin` y `soporte` en `crm_sandbox`. `ejecutivo` no existe aún. No hay usuarios con rol `soporte`.

## 4. Lo que se hizo, por sprint

### Sprint 1 (auditoría de datos)
- Documentación de los modelos de datos por canal (`docs/data/`), análisis de idempotencia (`docs/data/sync-idempotency.md`).
- **SYNC-GAP-01** (plataformas de VirtualPOS): validación contra `virtualpos1/virtualpos2`.
- **SYNC-GAP-03** (`source_record_id`): se rellena en VirtualPOS, Toku y Payku; la segunda pasada no lo borra. TCH sigue en NULL porque no escribe en `source_records`.
- **SYNC-GAP-02** (TCH `_dedupe_key`): caracterizado con tests y script de auditoría. Decisión de negocio pendiente (ver 7).
- **SYNC-GAP-04**: tests de formas de payload y log agregado de relaciones NULL (sin PII).
- Código legacy `crm_materialization.py`: **desactivado, no borrado** (`POST /etl/run` devuelve 410; el botón "Solo ETL" del front se eliminó).
- Cada consolidación corre en SAVEPOINT; `sync_virtualpos` falla el run si algo falla.
- TK-10 (filtro y orden por estado secundario de Toku) cerrada; **no depende de `flow_name`**. BLQ-TK-01 es un bloqueo externo (Toku) sin sprint.

### Sprint 2 (componentes y KPIs)
- `KpiCard`, `ChannelChart`, `ChannelKpiStrip` en `frontend/src/components/`; contrato de KPIs en `features/shared/kpis.ts`; vitest configurado.
- Backend: `rejected_charges` en los 4 canales (mes en hora de Chile), MRR de Payku desde la última transacción exitosa, TCH conserva "Mandatos vigentes" y suma `recaudo_mensual`, churn de Toku coherente con su MRR.
- Notas visibles de Payku, Toku y TCH.

### Sprint 3 (gráficos y sidebar)
- `ChannelChart` ampliado (leyenda, barras agrupadas, bandas de anotación, `pivotByStatus`, `fillMonths`); gráficos de los 4 canales con mapeos puros en `features/dashboard/channelCharts.ts`.
- Sidebar (UI-20): estados activos correctos, permisos de TCH, accesibilidad del menú móvil. Salud de canal (UI-21): `GET /api/v1/sync-runs/health` y puntos en el sidebar.
- Quedaron con el estilo viejo "Crecimiento real mensual" y "Churn %" (porcentajes).

### Sprint 4 (recuperador de VirtualPOS)
- **REC-03**: motivos de rechazo legibles (`latest_rejection_*` con respaldo en `raw_payload`), filtros (cuenta, código, monto, estado secundario, fecha), CSV con columna genérica `cuenta` y auditoría de cada exportación en `write_runs`, módulo de front `features/recovery/` reutilizable.
- **`monto_vigente`**: el monto de una suscripción en el CRM es el último cobro pagado o procesando con fecha hasta hoy (si no hay: monto de la suscripción, luego del plan). Usado por ETL, KPIs (MRR, ARPU, LTV) y recuperador. Impacto medido en la base local: MRR +0,15%.
- **WR-VP-05**: cancelar cobros futuros y reasignar monto, con orden seguro (crear el nuevo primero), simulación (`dry_run`) por defecto y bandera `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN`.
- **PK-05**: **sin hacer** (depende de las respuestas de Payku).

### Transversal
- **Ambientes**: `APP_ENV` (`production`/`sandbox`/`qa`), guardas de URLs y de credenciales, canales deshabilitados (VP cuenta 2 y Payku en sandbox), sync que omite canales deshabilitados.
- **Tests aislados**: `tests/conftest.py` fija la base `crm_test`, aborta si el nombre no termina en `_test`, recrea el esquema y aplica `alembic upgrade head`.
- **Rol `soporte`** + permiso `system.environment.switch`, endpoints `/system/environment` y `/system/environment/switch`, franja de ambiente y sección "Ambiente" en el panel admin, cookie de sesión con sufijo en sandbox, scheduler apagado en sandbox por defecto.
- **Limpieza de la base `crm`**: se borraron 549 usuarios y 310 roles de prueba generados por pytest antiguos (respaldo temporal fuera del repo). Quedan 3 usuarios y 4 roles reales.
- **Secreto JWT rotado** por uno aleatorio (el anterior era el marcador público de `.env.example`). Sesiones anteriores quedaron invalidadas.
- **Cliente de VirtualPOS endurecido** (ver sección 5): errores con HTTP 200, idempotencia por `internal_code`, `retry_charge` sin reintento ante timeout.
- **Suite de contrato** `tests_contract/virtualpos/` (guardas duras, limpieza obligatoria, informe de drift) con 17 pruebas.

## 5. Hallazgos sobre VirtualPOS (medidos en el sandbox el 2026-10-27)

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

Sin medir todavía: si el proveedor cobra ambos cargos del mismo mes en sus fechas, si los cargos cancelados consumen `num_charges`, el comportamiento tras `changecard`, reintentos automáticos de cargos manuales rechazados y rate limits en lotes grandes.

## 6. Decisiones de negocio del usuario (vigentes)

1. Hay 6000+ suscripciones en planes `MONTO_FIJO`; **no se pueden cambiar planes** ni pedirle la tarjeta de nuevo al socio.
2. El "monto de la suscripción" en el CRM es el último monto cobrado (`monto_vigente`).
3. **VirtualPOS sigue creando los cobros mensuales.** El CRM solo crea cobros al aplicar un cambio de monto o de fecha, o por una tarea puntual. Por lo demás sincroniza, reintenta rechazados y gestiona pendientes.
4. Cambio de monto: horizonte de 12 meses; se cancelan los automáticos **solo dentro del horizonte** (los posteriores quedan como red de seguridad, con el monto antiguo). Orden seguro: crear todos los nuevos primero y cancelar los antiguos del mismo mes solo si todos se crearon.
5. El día de cobro es el del último cargo y se guarda como dato propio (`charge_day`); cambiar la fecha a pedido del socio es una operación explícita que reprograma.
6. Rechazos: el CRM no crea cobros ni suspende nada; solo reintenta. La "racha de rechazos" (3 o más) es una ayuda opcional de solo lectura en el recuperador.
7. Ventana de 31 días: solo dentro de un cambio. Si el mes ya pasó hace 31 días o menos y no tiene cobro pagado, procesando ni rechazado, se crea el reemplazo con fecha de mañana; si es más antiguo, se marca para revisión manual.
8. Aprobaciones: por ahora solo **admin** aprueba (jefatura aún no está capacitada), con autoaprobación activada y auditada. Debe haber una configuración en el panel admin para asignar quién aprueba y una **bandeja de solicitudes** (vista previa de los cobros a crear y cancelar, aprobar o rechazar con comentario, historial). La doble aprobación (más de 20 suscripciones o variación de monto mayor al 50%) queda **apagada**.
9. Columna del CSV del recuperador: `cuenta` (genérica, para sumar otros canales). El CSV con datos personales solo con permiso de exportar.
10. Tabla de roles propuesta (no confirmada del todo): admin y jefatura exportan; soporte reintenta cobros; ejecutivo solo ve.

Todo el detalle de escenarios está en `docs/designs/facturacion-gestionada-escenarios.md` (175 escenarios vigentes, resultados medidos al principio).

## 7. Pendientes

### Del usuario o de terceros
- **Payku**: respuesta del soporte (activar sandbox y las preguntas Q-06, Q-08, Q-11, Q-27, Q-29 de `docs/integrations/payku/VALIDATION-PLAN.md`). Bloquea PK-05 y la validación de Payku.
- Verificar **KPI-01 contra VirtualPOS staging** (acceso humano).
- **Revisión visual en navegador** de los Sprints 3 y 4: franja de sandbox, tema oscuro, menú móvil, contraste de los puntos de salud, gráficos, recuperador y descarga real del CSV.
- Decidir el destino de `docs/designs/reconciliacion-identidad-socios.md` (documento suyo sin versionar).
- Decisión de negocio de SYNC-GAP-02: ¿un rechazo y un pago posterior de la misma cuota son dos cargos distintos?
- Tarjetas de prueba de rechazo y cambio de tarjeta para completar V-2, V-3, V-4 (requieren esperar días).
- Crear el rol `ejecutivo` cuando se decida su matriz; crear usuarios `soporte` en cada ambiente (cada uno tiene su propia base de usuarios).
- Apagar los túneles de Cloudflare y evaluar un secreto JWT propio para sandbox.

### Técnicos, en orden sugerido
1. **Opción A, solicitud y aprobación** (diseño en el catálogo de escenarios):
   - Tabla de solicitudes de cambio y configuración de aprobadores editable en el panel admin.
   - Bandeja de solicitudes con vista previa y auditoría.
   - Aplicar cambio: crear los 12 cargos nuevos, cancelar los automáticos del horizonte uno por uno, compensar si falla a la mitad y verificar "exactamente un pendiente por mes".
   - **Prohibir `cancel_future_charges` sin `charge_ids`** (el DELETE plural cancelaría también los manuales y los automáticos fuera del horizonte).
   - Bloqueo por suscripción (`pg_advisory_xact_lock`) contra solicitudes simultáneas.
   - Registro propio de los `charge_id` creados por el CRM.
   - Chequeo diario **de solo lectura** que avisa cuando a una suscripción con calendario modificado le quedan menos de 60 días de horizonte.
2. Corregir la fecha de "hoy" en `vp_current_amount.py` (usa UTC; debe usar la hora de Chile).
3. Suite de contrato, lotes 3 y 4: pruebas con tarjeta (V-2 a V-4, rechazos), etiquetas `[CLAIM:VP-Cxx]` en los documentos y script que cruce afirmaciones con pruebas. Añadir pruebas de contrato de la coexistencia de cargos (usar `CT-CO-AUTO`). Replicar el esquema para Toku (cuidado: comparte host con producción).
4. PK-05 y **Sprint 5** (recuperador general `/general/recuperador` con pestañas VP, Toku, Payku y TCH, solo lectura; REC-04, REC-05, REC-06; Payku necesita un modelo de cargos). **Sprint 6** (ENV-01 completo, BCK-01, OPS-09, VAL-VP-01/VAL-PK-01).
5. Migrar "Crecimiento real mensual" y "Churn %" a `ChannelChart` (necesita soporte de porcentajes).
6. Deuda menor: dos filas `VAL-VP-01` distintas en `docs/tasks.md`; `tests/test_health.py` espera `"development"` y depende del `.env`; borrar `crm_materialization.py` y su test cuando se confirme que no afecta; TCH sigue sin trazabilidad en `source_records`; el filtro `chargeable` de Toku también cambia las series históricas.

## 8. Plan resumido de los sprints que faltan (estimación de IA / equipo)

| Sprint | Alcance | Esfuerzo | Necesita |
|---|---|---|---|
| 4 (resto) | Opción A, PK-05 | ~20 h IA | Respuestas de Payku |
| 5 | Recuperador general (REC-04 a REC-06) | 24 a 32 h / 10 a 13 días | Definir qué es "recuperable" por canal, roles por pestaña, modelo de cargos de Payku |
| 6 | ENV-01, BCK-01, OPS-09, validaciones | 12 a 16 h / 8 a 10 días | Hosting, RPO/RTO, credenciales de sandbox, quien ejecute las validaciones |

## 9. Errores cometidos y cómo se corrigieron

| # | Error | Cómo se corrigió | Para no repetirlo |
|---|---|---|---|
| 1 | Informé "5.644 activos" en TCH; eran transacciones aceptadas, no clientes | Se rotuló "Transacciones aceptadas" y se añadió `accepted_transactions` | Verificar qué cuenta cada campo antes de reportar una cifra |
| 2 | Los tests escribían en la base `crm` (552 usuarios y cientos de roles basura) | Aislamiento en `crm_test`, guarda dura, limpieza con respaldo y verificación | Los tests jamás apuntan a una base con datos reales |
| 3 | Dos agentes corrían pytest a la vez sobre `crm_test`: fallos intermitentes que se atribuyeron a los tests | Se confirmó con corridas limpias | Una sola sesión de pytest; esperar a que termine el otro agente |
| 4 | El backend del 8000 tenía código viejo (`--reload` no recargó); el selector no aparecía | Reinicio y verificación por `/openapi.json` | Tras cambios de backend, comprobar rutas nuevas, no suponer |
| 5 | `.gitignore` con `.env.*` ignoraba `frontend/.env.sandbox` (el dev sandbox no funcionaría en otra copia) | Excepción explícita para ese archivo | Probar los comandos desde cero tras tocar `.gitignore` |
| 6 | `git add docs` agregó un documento ajeno sin versionar | Se reescribieron los dos commits locales (aún sin push); árbol idéntico verificado | `git add` por ruta; revisar `git status` antes de cada commit |
| 7 | Condición de carrera en el test de `EnvironmentBanner` (1 de 20 corridas) | `waitFor` sobre la clase del `<html>`; 30 corridas sin fallos | Probar los tests de front 20 o más veces antes de darlos por estables |
| 8 | Tests asíncronos con `@pytest.mark.asyncio`, sin `pytest-asyncio` | `asyncio.run` como el resto del proyecto | Revisar cómo prueban los tests existentes antes de escribir uno |
| 9 | La documentación del proveedor se aceptó como cierta (E-113, HTTP 400, `internal_code`, filtros) | Prueba V-5 y suite de contrato | Medir antes de decidir; marcar como "a verificar" lo inferido |
| 10 | El cliente trataba como éxito los errores con HTTP 200 (cancelaba localmente un cargo rechazado por el proveedor, y el sync leía listas vacías) | `VirtualPOSAPIError` central y revisión de cada llamador | Todo cliente de un proveedor debe validar el cuerpo, no solo el código HTTP |
| 11 | `retry_charge` (un GET que relanza el cobro) se reintentaba ante un timeout | `retry=False` para ese método, con test que falla con el código viejo | Un GET con efectos no se reintenta |
| 12 | `scripts/sync_virtualpos.py` y `sync_toku.py` rotos desde `master` (función renombrada) | Corregidos | Ejecutar los scripts auxiliares al renombrar funciones |
| 13 | El primer sync del sandbox falló: suscripciones activas duplicadas violaban un índice único y tumbaban todo el lote | Reintento fila por fila en SAVEPOINT, omitiendo solo las duplicadas con nota en el run | Un dato malo no debe tumbar toda la sincronización |
| 14 | `AUTH_JWT_SECRET` era el marcador público de `.env.example` | Rotado por un valor aleatorio | Comprobar que ningún valor sensible de `.env` coincida con lo versionado |
| 15 | Mis comparadores de la suite de contrato daban falsos "drift" (`int` frente a "number", textos esperados mal escritos) | Corregidos | Las pruebas de contrato también se prueban: revisar cada discrepancia antes de creerla |
| 16 | Un agente eliminó el botón "Solo ETL" en vez de apuntarlo a full-sync como se había elegido | Se reportó la desviación (el efecto era equivalente) | Revisar que la implementación respete la opción elegida |
| 17 | La opción A se diseñó con un job que crea cobros para todos los socios; el usuario aclaró que VirtualPOS crea los mensuales | Rediseño: solo cambios puntuales y chequeo de renovación de solo lectura; catálogo reescrito | Confirmar el alcance con el usuario antes de diseñar una pieza grande |
| 18 | El validador de comandos de PowerShell se confundía con `Remove-Item` (rutas con `C:`) | Evitarlo (`$env:VAR = $null`) | No usar `Remove-Item` para limpiar variables de entorno |
| 19 | Apareció un `.env copy` sin versionar en la raíz (el `.gitignore` no lo cubría por el espacio) | El usuario lo retiró | No dejar copias de `.env` en el árbol |

## 10. Archivos y documentos clave

- Estado y sprints: `docs/memory/CURRENT_SPRINT.md`, `docs/memory/PROJECT_STATE.md`, `docs/tasks.md`.
- Opción A y escenarios: `docs/designs/facturacion-gestionada-escenarios.md`.
- VirtualPOS: `docs/integrations/virtualpos/` (cada afirmación observada en sandbox lleva su `[CLAIM:VP-Cxx]`), `VALIDATION-PLAN.md`, `tests_contract/README.md`.
- Datos: `docs/data/` (modelos por canal y `sync-idempotency.md`).
- Código crítico: `app/services/write_virtualpos.py`, `app/integrations/virtualpos/client.py`, `app/services/channel_consolidation.py`, `app/services/vp_current_amount.py`, `app/api/v1/routes/{recovery,staging,tch,sync_runs,system,writes}.py`, `app/core/config.py` (ambientes y guardas), `tests/conftest.py` (aislamiento), `frontend/src/features/{recovery,dashboard,admin,shared}/`.
- Scripts de mantenimiento: `scripts/maintenance/` (backfill de `source_record_id`, comparaciones de MRR, `seed_roles.py`, limpieza de usuarios de prueba con borrado comentado).

## 11. Archivos sin versionar que NO son nuestros

- `docs/designs/reconciliacion-identidad-socios.md` (documento del usuario).
- `Sin título.canvas`, `Sin título 1.canvas`, `graphify-out/`, `knowledge/00 - Home/2026-10-06.md`.

## 12. Datos de prueba que quedaron en el sandbox de VirtualPOS

- `CT-CO-AUTO` (`c98d0682d8`): plan fijo "Plan Básico", ACTIVA, 12 automáticos pendientes intactos.
- `CT-DUP1` (`d2000dd026`): ACTIVA; noviembre de 2026 reemplazado por un cobro manual de $6.500 (el automático de ese mes está cancelado).
- Suscripciones previas del sandbox usadas por la suite de contrato: una de plan fijo (`a7c5fd80d0`) y una de plan variable (`940cad2ddb`).
- Se crean con el formulario público del plan (sus enlaces salen de `vp_plans.raw_payload->>'suscription_url'` en `crm_sandbox`) y las tarjetas de prueba de `docs/integrations/virtualpos/resources/sandbox.md`, automatizado con Playwright instalado **fuera** del proyecto (la extensión de Chrome no quedó disponible en la sesión).
