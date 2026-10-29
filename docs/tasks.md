# Plan y estado del proyecto SynkmetriX

> **Única fuente de verdad del plan y del estado.** Este archivo reemplaza a `docs/memory/CURRENT_SPRINT.md`, `docs/product/roadmap.md`, `knowledge/08 - Roadmap/` y a las secciones de pendientes y sprints de `handoff.md`, que ahora solo apuntan aquí.
> Última actualización: 2026-10-28 · Rama `sprint-4/recuperador-vp` · Head de migraciones en el código: `20261028_0038`.

## 1. Propósito, convenciones y reglas de uso

### 1.1 Propósito

Un solo lugar para saber qué se hizo, qué se hace, qué falta, qué está bloqueado y cuándo se considera hecho algo, organizado por sprint (metodología ágil adaptada: sprints de unas dos semanas, sesiones de trabajo delimitadas por sprint). El detalle técnico vive en otros documentos (arquitectura, `docs/data/`, `docs/integrations/`, `docs/designs/`, ADRs); aquí solo se enlaza.

### 1.2 Convención de IDs

Los IDs son estables: no se renumeran ni se reutilizan. Un ID tiene exactamente **una fila canónica** en la sección 4. Las secciones de sprint, bloqueos y deuda mencionan los IDs en prosa, nunca como primera columna de otra tabla.

| Familia | Uso |
| --- | --- |
| BILL | Facturación gestionada por el CRM (Opción A): cambios de cobro VirtualPOS con solicitud y aprobación |
| WR-VP, WR-TK, WR-PK, WR-INF | Escrituras hacia VirtualPOS, Toku, Payku y su infraestructura común |
| REC | Recuperador de socios |
| ENV, BCK, OPS, DEV, MT, STR | Ambientes, respaldo, operación, herramientas de desarrollo, mantenimiento y estructura |
| VAL, CT | Validación de contratos con proveedores (VAL-VP, VAL-PK, VAL-TK, VAL-TCH) y suite de contrato |
| VP, TK, PK, TCH | Trabajo propio de cada canal |
| SYNC, ETL, CORE, DB, STG, DATA, CATALOG, AUD | Sincronización, consolidación, modelo centralizado, base de datos, staging y auditorías |
| UI, KPI, CHART, FE, DASH, PERF, REP | Frontend, indicadores, gráficos, rendimiento y reportes |
| AUTH | Identidad, roles y permisos |
| WFL, BLQ, BUG, RISK, WH, DOC | Revisión de workflows, bloqueantes, defectos, riesgos, webhooks y documentación |
| USR | Acciones que solo puede hacer el usuario o un tercero |
| DEC | Decisiones abiertas (sección 5) |
| HOR | Horizonte sin sprint asignado |

IDs de otros documentos que se citan aquí pero tienen su fila en ellos: `GB-*` (escenarios de `docs/designs/facturacion-gestionada-escenarios.md`), `VP-Cxx` (afirmaciones contrastadas de VirtualPOS), `Q-xx` y `V-n` (preguntas de validación en los `VALIDATION-PLAN.md`), `SYNC-GAP-xx` (`docs/data/sync-idempotency.md`).

### 1.3 Vocabulario de estados (único)

| Estado | Significado |
| --- | --- |
| Pendiente | No iniciada |
| En curso | Con trabajo activo |
| Completada en código | Implementada y con pruebas automáticas, pero falta verificación humana, visual o en sandbox; la fila dice qué falta |
| Completada y verificada | Implementada y verificada con la evidencia que exige su criterio. Las filas históricas marcadas «Completada» antes del 2026-10-28 se normalizaron a este estado: se verificaron con las pruebas de su fecha |
| Bloqueada | No puede avanzar por una dependencia externa o una decisión pendiente; la fila nombra la dependencia |
| Diferida | Decidido no hacerla ahora; se conserva con la razón |

### 1.4 Reglas de uso

1. Al iniciar, bloquear, completar o cambiar el alcance de una tarea, se actualiza **su fila** (sección 4) y, si corresponde, la sección de su sprint (sección 3) y el tablero (sección 2).
2. Cada sprint declara: objetivo, Hecho, En curso, Pendiente, bloqueos, definición de hecho y una retrospectiva breve al cerrar (sección 3).
3. Una tarea no pasa a «Completada y verificada» solo porque exista código: se confirman implementación, pruebas relevantes, validación estática, revisión del diff y documentación (criterios de `AGENTS.md`). Lo que no se pudo validar se escribe en la fila.
4. Cuando este archivo y el código o los commits discrepan, prevalecen el código y los commits; se corrige este archivo y se deja nota en la sección 7.
5. Para cerrar un sprint: marcar sus filas, actualizar `docs/memory/PROJECT_STATE.md` con el estado técnico, completar la retrospectiva (7.1) y activar el siguiente sprint en el tablero.
6. Comprobación de que no hay IDs repetidos como primera columna (PowerShell, desde la raíz del repositorio):

```powershell
Select-String -Path docs/tasks.md -Pattern '^\|\s*([A-Z][A-Z0-9]*(-[A-Z0-9]+)+)\s*\|' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Group-Object | Where-Object Count -gt 1
```

   La salida debe estar vacía.
7. Privacidad al explorar reportes de proveedores (Toku, TCH): leer solo el encabezado de la hoja y confirmar que la fila sea de encabezados antes de imprimir; nunca imprimir filas. En documentos solo van nombres de columnas, conteos y reglas, sin RUT, nombres, correos ni teléfonos.

### 1.5 Decisiones vigentes del proyecto

- Backend FastAPI y Python; base PostgreSQL como fuente central de verdad; React/Vite en el frontend.
- Las sincronizaciones y el ETL solo leen (`GET`) de los proveedores. Las escrituras salen únicamente por rutas internas protegidas (CSRF y permisos), con bandera local por proveedor apagada por defecto y registro en `write_runs`.
- Un solo `.env`: con `APP_ENV=sandbox` la aplicación usa únicamente las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL` (confirmado en `app/core/config.py`). Los secretos nunca se versionan ni se copian a documentos.
- Escrituras de prueba contra sandbox solo con variables de proceso, nunca con banderas encendidas en `.env`.
- Hay más de 6000 suscripciones VirtualPOS en planes `MONTO_FIJO`: no se cambian planes ni se pide de nuevo la tarjeta al socio. VirtualPOS sigue creando los cobros mensuales; el CRM solo crea cobros al aplicar un cambio aprobado o por una tarea puntual (decisiones finales del 2026-10-28 en el documento de diseño de la Opción A).
- El monto de una suscripción VirtualPOS en el CRM es `monto_vigente`: último cobro pagado o procesando con fecha hasta hoy (hora de Chile); si no hay, el de la suscripción y luego el del plan.

## 2. Tablero resumen

| Sprint | Objetivo | Estado | Esfuerzo estimado | Bloqueos |
| --- | --- | --- | --- | --- |
| Sprint 0: Onboarding y fundación | Entorno operativo y `App.tsx` modularizado | Cerrado el 2026-10-24 | Hecho | Ninguno |
| Sprint 1: Auditoría de datos | Documentar el modelo de datos real por canal y auditar la idempotencia | Cerrado el 2026-10-25 | Hecho | Ninguno (decisión de negocio SYNC-GAP-02 abierta, ver DEC-04) |
| Sprint 2: Componentes y KPIs | Componentes compartidos y KPIs estándar por canal | Cerrado en código; falta KPI-01 contra VirtualPOS staging | Hecho | Acceso humano a VP staging (USR-03) |
| Sprint 3: Gráficos y sidebar | Gráficos estandarizados y sidebar con salud de canal | Cerrado en código; falta verificación visual | Hecho | Revisión visual en navegador (USR-02) |
| Sprint 4: Recuperador VP y facturación gestionada (Opción A) | Recuperador VP mejorado y cambios de cobro con solicitud y aprobación | En curso: BILL-01 a BILL-08 y REC-03 completadas en código | Estimación original del handoff: unas 20 h de IA para la Opción A y PK-05; restan BILL-09 a BILL-22 (por re-estimar) | Migraciones 0037/0038 sin aplicar (USR-01; en `crm_sandbox` las aplica el orquestador, en `crm` el usuario); soporte de Payku para PK-05; tarjetas de rechazo para VAL-VP-01 |
| Sprint 5: Recuperador general | Recuperador multicanal en `/general/recuperador` (VP, Toku, Payku, TCH) | Pendiente | 24 a 32 h de IA, 10 a 13 días de equipo | TK-20 (REC-04, que define «suscripción activa» desde los reportes de Toku); PK-06 y sandbox de Payku (REC-05) |
| Sprint 6: Infraestructura y operaciones | Ambientes, respaldo, operación y validaciones | Pendiente | 12 a 16 h de IA, 8 a 10 días de equipo | Decisiones de hosting, RPO/RTO, credenciales de sandbox y quién ejecuta las validaciones (DEC-11, DEC-12) |
| Línea transversal: ciclo de pruebas en sandbox | Desplegar, probar en sandbox, decidir y resumir con skill y agentes personales, según el [runbook](operations/sandbox-testing-and-decisions.md) | Aprobado el 2026-10-28 (DEC-27); ciclos por ejecutar | Por estimar | En producción siempre con el usuario; escenarios nuevos no catalogados se avisan antes |
| Línea transversal: E2E sandbox por canal | Probar de punta a punta cada canal en su sandbox | En curso (VirtualPOS parcial, Toku con guardas, Payku bloqueada, TCH sin iniciar) | Por estimar | Sandbox de Toku sin transacciones ni medios de pago; Payku sin credenciales |

## 3. Sprints

### 3.1 Sprints 0 a 3: cerrados en código

Resumen; el detalle de cada tarea está en la sección 4 y las lecciones en 7.1.

- **Sprint 0 (cerrado el 2026-10-24).** OPS-07 (servicios y base consolidada) y FE-02 (`App.tsx` reducido a una línea, 22 módulos en `features/`). Sin verificación pendiente.
- **Sprint 1 (cerrado el 2026-10-25).** DATA-01 a DATA-04 (modelos de datos por canal en `docs/data/`), TK-10 (filtro y orden por estado secundario de Toku, independiente de `flow_name`) y la parte de auditoría de SYNC-01 (informe de idempotencia en `docs/data/sync-idempotency.md`, cinco brechas). SYNC-GAP-01 resuelta, SYNC-GAP-03 parcial (TCH sigue sin `source_record_id`), SYNC-GAP-04 mitigada, SYNC-GAP-05 documentada. Sin verificación pendiente.
- **Sprint 2 (cerrado en código).** FE-03 (KpiCard, ChannelChart, ChannelKpiStrip) y KPI-01 a KPI-04. **Falta:** verificar las cifras de KPI-01 contra VirtualPOS staging (acceso humano).
- **Sprint 3 (cerrado en código).** CHART-01 a CHART-04, UI-20 (sidebar) y UI-21 (salud de canal, `GET /api/v1/sync-runs/health`). **Falta (acceso humano):** revisión visual en navegador y temas, contraste de los puntos de salud sobre `#1a3d47` y `#091418`, y verificar las cifras de CHART-01 contra VP staging. «Crecimiento real mensual» y «Churn %» siguen con los componentes antiguos porque `ChannelChart` no soporta porcentajes (ver deuda técnica).

### 3.2 Sprint 4: Recuperador VP y facturación gestionada (Opción A)

- **Estado:** en curso. Rama `sprint-4/recuperador-vp` (cada rama de sprint contiene a la anterior), 14 commits locales sin subir al remoto.
- **Objetivo:** mejorar el recuperador de socios VirtualPOS (motivos de rechazo, filtros, CSV trazable) y habilitar que el CRM gestione cambios de cobro de VirtualPOS con solicitud, aprobación, ejecución segura y auditoría (Opción A), sin cambiar planes y sin pedir de nuevo la tarjeta al socio.

**Hecho**

- REC-03: recuperador con motivos desde `latest_rejection_*`, filtros antes de paginar, CSV con auditoría en `write_runs` y módulo `features/recovery` con el canal como parámetro. Falta verificación visual y descarga real del CSV.
- Opción A, pasos 1 a 6b, registrados como BILL-01 a BILL-08 (permisos y rol `ejecutivo`, modelos y migración 0038, cálculo del plan, aplicación con compensación, API `/billing`, bandeja y política en el frontend, chequeo diario de renovación y pestaña Renovaciones). Todas «Completada en código; verificación visual y en sandbox pendientes».
- WR-VP-05 (cancelar cargos futuros y reasignar monto) implementada tras la bandera `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN`; V-5 ejecutada en sandbox.
- BUG-VP-02: «hoy» de `vp_current_amount` calculado en hora de Chile (413a740). Ya no es pendiente del handoff.
- Transversal: ambientes (`APP_ENV`, guardas de URL y credenciales, canales deshabilitados), selector de ambiente y rol `soporte`, pruebas aisladas en `crm_test`, cliente VirtualPOS endurecido (errores con HTTP 200, idempotencia por `internal_code`, `retry_charge` sin reintento ante timeout), suite de contrato VirtualPOS (CT-01, lotes 0 a 2), catálogo de 175 escenarios de la Opción A y guardas duras de escritura de Toku (TK-16).
- Estado de pruebas al cierre de la sesión del 2026-10-28: backend 844 pasan, frontend 179 pasan, `ruff` limpio.

**En curso**

- BILL-19 (tanda 2 de arreglos: API, política, scheduler y KPIs), sin commit aún.
- Ciclo de pruebas en sandbox con skill y agentes personales (`sandbox-orchestrator`, `sandbox-tester`, `decision-maker`, en la carpeta personal del usuario, no versionados) y el [runbook](operations/sandbox-testing-and-decisions.md), aprobado el 2026-10-28 (DEC-27): en sandbox sin problema; en producción siempre con el usuario y más cuidado. Orden acordado: arreglos de la revisión (BILL-17 a BILL-20) → importador de Toku (TK-17 a TK-22) → pruebas de contrato en sandbox de VirtualPOS (BILL-11).
- VAL-VP-01 y CT-01: V-1 y V-5 resueltas; V-2 a V-4 y los lotes 3 y 4 de la suite de contrato requieren tarjeta y cobro real.
- Revisión de Toku contra la API real (TK-13), importador de reportes de Toku (TK-14 a TK-22) y su suite de contrato (VAL-TK-01), que alimentan el Sprint 5.

**Pendiente**

- BILL-09 a BILL-16 (allowlist del piloto, controles de consistencia, pruebas de contrato P0, piloto y reversión, revisión de código independiente, lock por cargo en `retry_charge`, rechazo de tareas de renovación con comentario, reautorización por cambio de categoría) y BILL-17 a BILL-22 (resultado de la revisión independiente: tanda 1 hecha en código, tandas 1b, 2 y 3 y backlog menor).
- Migraciones 0037 y 0038 y seed de roles: en `crm_sandbox` los aplica el orquestador avisando al usuario (DEC-28); en `crm` los aplica el usuario (USR-01).
- Verificaciones humanas: bandeja de cambios de cobro y Renovaciones, recuperador y CSV, Sprints 3 y 4 (USR-02, USR-03).
- PK-05 (certificar cobertura histórica de Payku) depende del soporte de Payku.

**Bloqueos**

- Soporte de Payku: sandbox y preguntas Q-xx (DEC-10). Bloquea PK-05 y VAL-PK-01.
- Tarjetas de prueba con rechazo y cambio de tarjeta para V-2 a V-4 (DEC-09).
- Migraciones 0037/0038 sin aplicar a las bases: bloquea cualquier prueba de BILL en entorno real (en `crm_sandbox` las puede aplicar el orquestador).

**Definición de hecho del Sprint 4**

- [x] REC-03 en código con pruebas automáticas.
- [x] BILL-01 a BILL-08 en código con pruebas automáticas; suite al cierre de sesión: backend 844, frontend 179, `ruff` limpio.
- [ ] REC-03 verificada: revisión visual y descarga real del CSV.
- [ ] Migraciones 0037 y 0038 y seed de roles aplicados en `crm_sandbox` (orquestador) y en `crm` (usuario).
- [ ] BILL-09 a BILL-22 completadas en código.
- [ ] BILL-11 ejecutada: pruebas de contrato P0 en sandbox VP con resultados anotados en el documento de diseño.
- [ ] BILL-12: piloto GB-PI-01 a GB-PI-11 sin criterios de abort y script de reversión probado.
- [ ] BILL-13: revisión de código independiente y documentación de la Opción A al día.
- [ ] Bandeja de cambios de cobro y pestaña Renovaciones verificadas visualmente.
- [ ] WR-VP-05: prueba controlada en producción antes de encender la bandera allí (hoy apagada).
- [ ] PK-05 cerrada, o movida a Diferida por decisión del usuario si el soporte de Payku no responde antes del cierre.
- [ ] Revisar `tests/test_charge_recovery.py::test_retry_history_endpoint_returns_items_and_total` (fallo preexistente reportado por acumulación de filas en la base de pruebas; reverificar tras el aislamiento en `crm_test`).

**Retrospectiva (parcial, se completa al cerrar)**

- Funcionó: medir en el sandbox antes de decidir (la documentación de VirtualPOS se equivocó en seis puntos); aislar pruebas en `crm_test`; diseñar la Opción A con catálogo de escenarios antes de codificar.
- A mejorar: confirmar el alcance con el usuario antes de diseñar una pieza grande (la primera versión de la Opción A creaba cobros para todos los socios); `git add` por ruta; una sola sesión de pytest a la vez; verificar lo que reportan los agentes. La tabla completa de errores y correcciones está en `handoff.md` sección 9.

### 3.3 Sprint 5: Recuperador general (REC-04, REC-05, REC-06)

- **Estado:** pendiente. Estimación: 24 a 32 h de IA, 10 a 13 días de equipo; tres semanas de calendario.
- **Objetivo:** un recuperador multicanal de solo lectura en `/general/recuperador` con pestañas VP, Toku, Payku y TCH; la ruta `/virtualpos/recuperador-socios` se mueve ahí (el módulo `features/recovery` ya recibe el canal como parámetro).
- **Definiciones acordadas:** «recuperable» es el socio con racha de rechazos (3 o más seguidos; ayuda de solo lectura que no suspende nada) **o** tarjeta bloqueada **o** tarjeta vencida. Todos los roles ven todo en el recuperador; el panel de administración es solo admin.
- **Hecho:** nada del sprint; REC-03 (Sprint 4) dejó el módulo listo para multicanal.
- **En curso:** TK-14 (importador de reportes de Toku, diseño hecho) y VAL-TK-01; TK-17 a TK-22 alimentan REC-04.
- **Pendiente:** REC-04, REC-05, REC-06.
- **Bloqueos:** REC-04 necesita TK-20 (señales de «activa efectiva», racha por cuotas, tarjeta bloqueada y vencida desde los reportes de Toku; deja de depender de TK-15, que sigue necesaria para VAL-TK-01). REC-05 necesita un modelo de cargos de Payku por explorar en sandbox (PK-06) y credenciales. E2-BATCH (reintento en lote) queda diferido.
- **Definición de hecho:**
  - [ ] Pestañas VP, Toku, Payku y TCH en `/general/recuperador`, con permisos RBAC aplicados y redirección desde la ruta antigua.
  - [ ] Criterio de «recuperable» implementado igual en los cuatro canales y documentado.
  - [ ] TCH sin acciones de escritura remota; Payku con advertencia de cobertura histórica limitada.
  - [ ] Pruebas automáticas por canal y verificación visual.
- **Retrospectiva:** se completa al cerrar.

### 3.4 Sprint 6: Infraestructura y operaciones (pendiente de definición)

- **Estado:** pendiente; no se puede planificar con detalle hasta resolver las decisiones de abajo. Estimación: 12 a 16 h de IA, 8 a 10 días de equipo.
- **Objetivo:** separar de verdad los ambientes (ENV-01), automatizar respaldo y recuperación (BCK-01), decidir la entrega de progreso en tiempo real (OPS-09) y cerrar las validaciones de contrato de proveedores (VAL-VP-01, VAL-PK-01, VAL-TK-01).
- **Pendiente de decisión (DEC-11 y DEC-12):** hosting; RPO y RTO objetivo; credenciales de sandbox de Toku y Payku; quién ejecuta las validaciones.
- **Definición de hecho:**
  - [ ] ENV-01: cada ambiente con base, credenciales y proveedores propios, y proceso de deploy y migración documentado.
  - [ ] BCK-01: respaldo físico con WAL/PITR más dump lógico, retención definida y un simulacro de restauración documentado.
  - [ ] OPS-09: decisión documentada sobre SSE frente a WebSocket.
  - [ ] Validaciones de contrato ejecutadas y los `VALIDATION-PLAN.md` actualizados.
- **Retrospectiva:** se completa al cerrar.

### 3.5 Línea transversal: E2E en sandbox por canal

Objetivo: demostrar que cada canal funciona de punta a punta en un ambiente aislado. No tiene fecha de sprint: avanza según la disponibilidad de cada sandbox y alimenta los Sprints 4 a 6.

**VirtualPOS (disponible)**

- Cuenta 1 operativa en sandbox; la cuenta 2 está deshabilitada en sandbox y el sync la omite con aviso.
- Suite de contrato en `tests_contract/virtualpos/` con guardas duras (CT-01). V-1 y V-5 resueltas; V-2 a V-4 pendientes (tarjeta y cobro real).
- Pruebas de contrato P0 de la Opción A (CT-00, CT-CO-AUTO, CT-CO-DUP, CT-CO-NC3, CT-RZ-MC, CT-RZ-SWAP, CT-CANCEL, CT-STALE): BILL-11.
- Datos de prueba que quedaron en el sandbox: ver `handoff.md` sección 12.

**Toku (sandbox con datos aislados, sin transacciones ni medios de pago)**

- Guardas duras de escritura fuera de producción (TK-16). Siguiente: suite de contrato con lecturas primero (VAL-TK-01), revisión del modelo contra la API real (TK-13), importador de reportes descargados (TK-14 a TK-22), generación de rechazos de prueba (TK-15) y webhooks (TK-12).
- Hallazgos medidos el 2026-10-28 con solo lecturas (llave de sandbox, sin datos personales): la llave ve una organización aparte (34 clientes, 37 suscripciones, 41 invoices, todas `UNPAID` y vencidas, 0 transacciones, 0 medios de pago y `/organization/payments` responde 404), con 0 IDs en común con producción; la URL base es la misma y las llaves distintas. Las escrituras siguen sin verificarse.
- El header de versión `x-api-version` (y `x-toku-api-version`) no cambia las claves ni los conteos de las respuestas en el sandbox (customers 17 claves, subscriptions 21, invoices 26): hipótesis descartada y el cliente no se cambia. Límite: solo probado en sandbox; producción podría diferir según la fecha de creación de la organización.
- Los campos que la documentación daba por supuestos no faltan por versión: `recurring` y `recurring.status` existen solo si `is_recurring=true` (18 de 37 suscripciones); `remaining_collection_attempts`, `max_collection_attempts` y `expiration_date` pertenecen a la invoice y vienen null en las 41 (sin intentos configurados). La API de invoices no aporta intentos hoy; la API no entrega `status` de cliente ni de suscripción.
- La API de reportes está disponible con la llave de sandbox: `GET /reports/{entity}/columns` respondió 200 para subscription (18 columnas), payment_method (28), payment_intent (22), payment_method_inscription_intent (21), pac_inscription_intent (21), invoice (18) y customer (11). `POST /reports/{entity}` no se ha usado (genera reportes) y queda bloqueado por las guardas de escritura. Cubren estado de suscripción y medio de pago, último código de rechazo por medio, intentos con estado, código y fecha, y rechazos de inscripción PAC.
- La documentación oficial no describe tarjetas de prueba ni cómo simular TE, PE o UE; lo más cercano es el portal sandbox de PAC (RUT de prueba 11.111.111-1, contraseña cualquiera; coordenadas «00 00 00» fuerzan una inscripción fallida). Catálogo oficial de `response_code` (unas 400 filas) con regla de reintento por prefijo (TE temporal, PE permanente, UE desconocido, SU éxito) e incoherencias (1001 TE y 1065 PE, ambos fondos insuficientes). Reintentos: tarjetas los días 1, 2, 3, 4, 5, 10, 15 y 25 y luego mensual indefinido con tope de 15 al mes; PAC cada unos 3 días hábiles. Estados de medio de pago: `chargeable`, `temporary_failed`, `permanent_failed`, `inscription_failed`, entre otros.
- Importador de reportes descargados del Backoffice (TK-14 a TK-22): diseño en 4.3 y decisiones DEC-16 a DEC-25.

**Payku (sin credenciales)**

- Variables `PAYKU_SANDBOX_*` vacías. Avanzable sin ellas: diseño del modelo de cargos (PK-06) y `tests_contract/payku` con guardas, que se omite sola sin credenciales (VAL-PK-01, parte 1).
- Bloqueado por credenciales o por el soporte de Payku: ejecutar la colección de validación y las preguntas Q-01, Q-02, Q-06, Q-08, Q-11, Q-27, Q-29 y Q-33 (ver sección 5).

**TCH (Excel a ETL a dashboard a recuperador)**

- Cadena completa por verificar: carga del `.xlsx` desde administración (TCH-07), ETL a tablas `tch_*`, Core ETL, dashboard y, en Sprint 5, recuperador TCH (REC-06). Tarea de verificación: VAL-TCH-01.

## 4. Backlog por área

Cada ID aparece en una sola fila. Estado según el vocabulario de 1.3. Orden dentro de cada área: el histórico primero y las tareas nuevas de la sesión del 2026-10-28 al final. Origen de las filas WFL, BLQ, VAL y BUG: revisión comparativa del 2026-10-15 de los documentos de VirtualPOS, Toku y Payku frente a `docs/integrations/` ([informe comparativo](https://claude.ai/artifact/7R7N8sJHPRCoTpBnLhcBzg)). Patrón de las escrituras (WR-*): backend en `app/api/v1/routes/`, servicio que actualiza `source_records` y re-materializa la entidad centralizada, y botón del frontend conectado a la ruta interna.

### 4.1 Opción A: facturación gestionada (BILL)

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| BILL-01 | Permisos de cambios de cobro y rol `ejecutivo` | Completada en código; verificación visual y en sandbox pendientes | Permisos `billing_changes.request`, `billing_changes.approve`, `billing_changes.view` y `billing_policy.manage`; rol `ejecutivo` de solo lectura; `soporte` y `ejecutivo` tienen `.view`. Migración 0037 (commit 44f379f). Pendiente: aplicar la migración y `scripts/maintenance/seed_roles.py` en `crm` y `crm_sandbox` (USR-01). |
| BILL-02 | Modelos y migración de solicitudes de cambio de cobro | Completada en código; verificación visual y en sandbox pendientes | Migración 0038 (commit 10ee830). Índice único parcial: una sola solicitud abierta por suscripción en los estados pendiente, aprobada, aplicando y requiere_conciliacion. Pendiente: aplicar la migración (USR-01). |
| BILL-03 | Cálculo puro del plan de cambio de cobro | Completada en código; verificación visual y en sandbox pendientes | Función pura que calcula, mes a mes, qué cobros crear y cuáles cancelar dentro del horizonte de 12 meses (commit 784eaf3). Pruebas automáticas; falta contrastarla con el sandbox (BILL-11). |
| BILL-04 | Aplicar cambios de cobro con compensación y lock | Completada en código; verificación visual y en sandbox pendientes | Orden seguro (crear primero, cancelar los automáticos del horizonte solo si todos los nuevos se crearon), compensación ante fallo a la mitad, lock por suscripción, verificación final de «exactamente un pendiente por mes» y prohibición de `cancel_future_charges` sin `charge_ids` en suscripciones con calendario modificado (commit 7e9121a). |
| BILL-05 | API `/billing` de solicitudes y política de aprobadores | Completada en código; verificación visual y en sandbox pendientes | Solicitudes, aprobación y rechazo con comentario, e historial (commit caf9bd0). Política editable: aprueba solo `admin` por ahora con autoaprobación auditada; doble aprobación implementada y apagada. |
| BILL-06 | Frontend: bandeja de solicitudes y política | Completada en código; verificación visual y en sandbox pendientes | Bandeja con vista previa, aprobar o rechazar con comentario e historial, y panel de política (commit d907f04). Bandeja movida al grupo General con ruta `/general/cambios-de-cobro` y redirección desde `/virtualpos/cambios-de-cobro`; selector de solicitantes (commit 38df759). |
| BILL-07 | Chequeo diario de renovación y expiración de solicitudes | Completada en código; verificación visual y en sandbox pendientes | Chequeo de solo lectura que genera tareas «renovar calendario» y expiración de solicitudes; jobs `billing_renewal_check` a las 03:00 y `billing_expire_requests` cada hora (commit 512ba46). |
| BILL-08 | Pestaña Renovaciones en la bandeja | Completada en código; verificación visual y en sandbox pendientes | Pestaña Renovaciones con las tareas del chequeo, que abren una solicitud de tipo renovación (commit f307b64). |
| BILL-09 | Allowlist del piloto | Pendiente | Solo se aceptan solicitudes y se revisan renovaciones para suscripciones de la allowlist (GB-JB-20); bandera de plan fijo encendida solo para ella. |
| BILL-10 | Controles de consistencia y cola de reconciliación | Pendiente | Controles diarios de solo lectura GB-CS-02 a GB-CS-14 (desfases, doble pendiente, mes sin cargo, cargos no registrados, doble cobro) y cola de reconciliación para `reconciliation_required`, que bloquea la suscripción. |
| BILL-11 | Pruebas de contrato P0 en sandbox VP | Pendiente | Ejecutar CT-00, CT-CO-AUTO, CT-CO-DUP, CT-CO-NC3, CT-RZ-MC, CT-RZ-SWAP, CT-CANCEL y CT-STALE (recetas en el documento de diseño) y anotar resultados; condiciona el piloto (GB-PI-01). Algunas requieren tarjeta y esperar fechas de cobro (DEC-09). Catálogo, topes y limpieza en el [runbook](operations/sandbox-testing-and-decisions.md) (sección 3.1); las 8 pruebas se aprueban en bloque una vez escritas y el orquestador registra un DEC-xx al aprobar la receta definitiva. |
| BILL-12 | Piloto GB-PI-01 a GB-PI-11 y script de reversión | Pendiente | Piloto con 5 a 10 suscripciones voluntarias, fases de 1 mes y 12 meses, criterios de éxito y de abort (GB-PI-05 y GB-PI-06) y script de reversión probado (GB-PI-07). Depende de BILL-09, BILL-10 y BILL-11. |
| BILL-13 | Revisión de código independiente y documentación de la Opción A | En curso | Paso 7 del plan. Revisión independiente completada (4 frentes); sus resultados están en BILL-17 a BILL-22. Pendiente: documentación operativa de la Opción A al día. |
| BILL-14 | Lock por cargo en `retry_charge` | Pendiente | Un solo `/retry` por cargo ante doble clic o dos usuarios a la vez (GB-RZ-30); responde 409 o «ya en curso» sin llamar a VirtualPOS. |
| BILL-15 | Rechazar tareas de renovación con comentario | Pendiente | Al rechazar una tarea de renovación, se cierra con el comentario y la suscripción deja de ser «calendario modificado» desde el fin del horizonte (GB-JB-32). |
| BILL-16 | Reautorización por cambio de categoría de aprobaciones | Pendiente | Entre la solicitud y la ejecución se revalida el estado; si la doble aprobación está encendida y la variación cambió de categoría, se pide reaprobación (GB-AP-13, parte final). |
| BILL-17 | Tanda 1 de arreglos de la revisión independiente (planificador y aplicación) | Completada en código; verificación en sandbox pendiente | Commit 8a77809. Acotó el reemplazo al mes original (meses pasados van a revisión manual con `reason` `replacement_outside_month`), punto abierto en DEC-30. Suite al cierre de la tanda: backend 897, frontend 179. |
| BILL-18 | Tanda 1b: ventana de 31 días y meses sin cobro previo | Pendiente | Depende de DEC-30 (ventana de 31 días y reemplazo de mes atrasado). Además, por decisión del usuario (DEC-29): mes con solo cobros cancelados va a revisión manual; mes sin ningún cobro se crea con aviso `month_without_charge`. |
| BILL-19 | Tanda 2: API, política, scheduler y KPIs | En curso | Arreglos de la revisión independiente en la API `/billing`, la política de aprobadores, el scheduler y los KPIs. Sin commit aún. |
| BILL-20 | Tanda 3: frontend de aplicar y lecturas, y Toku | Pendiente | Frontend de aplicar y lecturas; en Toku, orden de las guardas en `delete_subscription`, aviso en el arranque para `APP_ENV=development` con Toku sin cambiar el comportamiento (DEC-29) y endurecimiento de regex. |
| BILL-21 | Hallazgos menores y de accesibilidad de la revisión | Pendiente | Backlog: `Dialog` inert, `role=tabpanel`, `border-left` del timeline (DESIGN.md), fecha del formulario en la zona de Chile y cobro puntual sin tope superior. |
| BILL-22 | Observabilidad de solicitudes y del barrido | Pendiente | Alerta de solicitudes en `requiere_conciliacion` o barridas; registro del barrido en el tablero. Acción del usuario: ejecutar `SHOW idle_in_transaction_session_timeout` en la base real y reportar el valor, para revisar ese parámetro. |

### 4.2 VirtualPOS

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-01 | Inicializar Git, entorno Python y configuración segura | Completada y verificada | `.venv`, `.gitignore`, `.env.example` y `requirements.txt` disponibles; `.env` no se versiona. |
| VP-02 | Crear API FastAPI y persistencia PostgreSQL | Completada y verificada | API saludable, modelos y migración inicial definidos. |
| VP-03 | Implementar autenticación y cliente VirtualPOS | Completada y verificada | Firma HS256 generada localmente y peticiones solo de lectura. |
| VP-04 | Persistir staging idempotente y ejecuciones de sincronización | Completada y verificada | Repetir una sincronización no duplica registros externos. |
| VP-05 | Normalizar clientes, suscripciones y pagos | Completada y verificada | Las vistas centralizadas preservan la referencia al origen. |
| VP-06 | Exponer consulta y estado de sincronización | Completada y verificada | Endpoints documentados y cubiertos por pruebas. |
| VP-07 | Validar contra Sandbox y documentar resultados | Completada y verificada | Ejecución real registrada sin exponer secretos. |
| VP-08 | Inspeccionar y documentar los payloads reales de Sandbox | Completada y verificada | Campos, identificadores y paginación observados en Sandbox y documentados. |
| VP-09 | Completar paginación y sincronización incremental | Completada y verificada | Paginación y upsert condicional validados por dos sincronizaciones consecutivas. |
| VP-10 | Normalizar modelo centralizado | Completada y verificada | Clientes, planes, suscripciones, cargos y pagos se materializan desde staging. |
| VP-11 | Crear API de consulta del CRM | Completada y verificada | Endpoints paginados para clientes, suscripciones, pagos y detalle. |
| VP-12 | Añadir pruebas de integración del sincronizador | Completada y verificada | Respuestas simuladas cubren éxito, paginación, duplicados y errores. |
| VP-13 | Programar sincronizaciones y alertas | Completada y verificada | Job cron 02:00 + job reintento 04:00; channels_failed en EtlRun; migración 0035 (commit bcf1d47). |
| VP-14 | Iniciar frontend CRM | Completada y verificada | Dashboard y vistas de clientes/suscripciones consumen la API. |
| VP-15 | Mejorar vistas staging de VirtualPOS | Completada y verificada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| VP-16 | Crear ficha de cliente VirtualPOS desde staging | Completada y verificada | UUID abre la ficha y lista todas las suscripciones VirtualPOS relacionadas por RUT. |
| VP-17 | Crear fichas de plan y suscripción VirtualPOS | Completada y verificada | Planes listan suscripciones por plan_id; suscripciones muestran método de pago saneado y cargos por contexto de sync. |
| VP-18 | Añadir filtros y orden en tablas VirtualPOS | Completada y verificada | Filtros por columnas operativas; cargos y transacciones ordenados por fecha descendente. |
| VP-19 | Crear edición visual de clientes VirtualPOS | Completada y verificada | Botones y formulario visual; guardado remoto pendiente de autorizar escritura. |
| VP-20 | Mejorar ficha de cliente VirtualPOS | Completada y verificada | Etiquetas visuales en español y navegación a fichas de subscripción. |
| VP-21 | Traducir tipo de documento VirtualPOS | Completada y verificada | La ficha muestra RUT para 1 y DNI para 2. |
| VP-22 | Crear cancelación visual de subscripciones VirtualPOS | Completada y verificada | Botones y confirmación visual; DELETE remoto pendiente de autorizar escritura. |
| VP-23 | Mejorar ficha de subscripción VirtualPOS | Completada y verificada | Navegación al plan y presentación segura del método de pago. |
| VP-24 | Restringir cancelación visual de subscripciones | Completada y verificada | Cancelar Sub se muestra solo para estado ACTIVA. |
| VP-25 | Crear ficha y navegación de cargos VirtualPOS | Completada y verificada | IDs abren fichas de cargo; fechas ordenadas de más reciente a más antigua. |
| VP-26 | Restaurar navegación en tablas de cargos y pagos | Completada y verificada | ID de cargo y UUID de pago abren sus fichas locales. |
| VP-27 | Desglosar datos de transacción VirtualPOS | Completada y verificada | order y client se muestran como campos individuales en la ficha. |
| VP-28 | Enriquecer cargos y pagos VirtualPOS con detalle verificable | Completada y verificada | `_enrich_charges_with_rejections()` en `core_vp_etl` usa `VpPayment.charge_external_id` para encontrar el pago rechazado más reciente por cargo y pobla `CoreCharge.latest_rejection_*`; incremental e idempotente. |
| WR-VP-01 | Habilitar edición y creación real de clientes VirtualPOS | Completada y verificada | `PUT /v3/client/:uuid` y `POST /v3/client` se ejecutan desde modales internos con selector VP1/VP2; bdlocal actualizada; edición y creación operativas. |
| WR-VP-02 | Habilitar cancelación real de suscripciones VirtualPOS | Completada y verificada | `DELETE /v3/suscription/:id` ejecutado desde el modal de confirmación; estado en bdlocal cambia a CANCELADA. |
| WR-VP-03 | Habilitar cancelación real de cargos VirtualPOS | Completada y verificada | `DELETE /v3/charge/:id` ejecutado desde ficha y tabla; cargo actualizado en bdlocal. |
| WR-VP-04 | Habilitar cancelación real de pagos VirtualPOS | Completada y verificada | `DELETE /v3/payment/:uuid` ejecutado desde la ruta interna `DELETE /api/v1/writes/virtualpos/payments/{id}`; pago actualizado en staging y entidad centralizada. |
| WR-VP-05 | Flujo especial: cancelar cargos futuros y reasignar monto en suscripción activa | Completada en código; validación en producción pendiente | Implementado detrás de `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` (apagada por defecto): cancela cargos futuros pendientes (`DELETE /v3/charges/{suscription_id}`; E-079 y E-059 no-op) y reasigna monto creando primero el cargo nuevo y cancelando el del mismo mes solo si el nuevo funciona. Endpoints con CSRF, permisos de cargos, `dry_run` por defecto y trazabilidad en `write_runs`. V-5 (sandbox, 2026-10-27): `POST /v3/charge` aceptado en plan `MONTO_FIJO`, sin E-113. Falta la prueba controlada en producción antes de encender la bandera allí (DEC-15). La Opción A (BILL-03 y BILL-04) generaliza este flujo de un mes a un horizonte de 12 meses con solicitud y aprobación. |
| WFL-VP-01 | Revisar workflows VirtualPOS individualmente | Completada y verificada | 15 workflows revisados contra código: 3 implementados, 10 parciales, 2 no implementados. Riesgos críticos: retry sin clasificación de motivo, create_subscription sin antiduplicado, url_redirect no persistida. Ver `docs/integrations/virtualpos/REVIEW.md`. Commit `e266ac2`. |
| VAL-VP-01 | Validar contratos VirtualPOS en sandbox (V-1 a V-5) | En curso | Plan en [VALIDATION-PLAN de VirtualPOS](integrations/virtualpos/VALIDATION-PLAN.md) con prerrequisitos de sandbox y requests exactos. V-1 resuelta (el listado trae el `charge_program` completo, VP-C01). V-5 ejecutada el 2026-10-27: `POST /v3/charge` aceptado en plan fijo (contradice la documentación, que indica E-113). V-2, V-3 y V-4 pendientes: requieren tarjeta y cobro real (DEC-09). Cierre de Sprint 6: REVIEW.md actualizado con los resultados. Unificada de Hito 5 y Sprint 6. |
| CT-01 | Suite de contrato VirtualPOS (documentación frente a sandbox) | En curso | Lotes 0 a 2 hechos en `tests_contract/` (17 pruebas; informe `reports/contract/virtualpos/drift-*.md`, no versionado). Lote 3 requiere tarjetas de prueba; lote 4: etiquetado `[CLAIM:VP-Cxx]` de afirmaciones y script de cruce. Las pruebas P0 de la Opción A son BILL-11. |
| BUG-VP-01 | Corregir clave `card_change_url` en `recovery.py` de VirtualPOS | Completada y verificada | `app/api/v1/routes/recovery.py` corregido a `"change_card_url"` (clave correcta según contrato VirtualPOS); 17/17 tests pasan. |
| RISK-VP-01 | Agregar clasificacion de motivo antes de `retry_charge` VirtualPOS | Completada y verificada | `retry_charge` obtiene `payment.order.uuid`, llama a `/attempts` y clasifica el motivo; CAMBIO_TARJETA y DIFERIR lanzan RetryBlockedError (HTTP 409); commit df76bc5. |
| RISK-VP-02 | Agregar antiduplicado en `create_subscription` VirtualPOS | Completada y verificada | Verifica `VpSubscription` ACTIVA/SUSCRIBIENDO antes de llamar al proveedor (HTTP 409); además índice único parcial `uq_vp_sub_active_plan_client` (migración 0036) captura la condición de carrera con `IntegrityError` → `DuplicateSubscriptionError`; commits 267fd47 + 8c2ba4e. |
| BUG-VP-02 | Calcular «hoy» de `vp_current_amount` en hora de Chile | Completada y verificada | El cálculo de `monto_vigente` usaba UTC; ahora usa la hora de Chile (commit 413a740). Ya no es pendiente del handoff. |

### 4.3 Toku

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| TK-01 | Sincronizar colecciones read-only de Toku a staging | Completada y verificada | Ejecuciones registradas por fuente y payloads disponibles en `source_records`. |
| TK-02 | Mejorar vistas staging de Toku | Completada y verificada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| TK-03 | Migrar vistas Toku a BD local | Completada y verificada | Menú, tablas, fichas y dashboard Toku consultan las entidades centralizadas materializadas desde Toku_Local; sincronizar Toku rematerializa solo desde esa BD. |
| TK-04 | Ajustar suscripciones activas Toku | Completada y verificada | El resumen operativo muestra "Subscripciones activas" y MRR/ARPU solo desde suscripciones `ACTIVE` vinculadas a un método `chargeable`; los métodos cuentan solo estado `chargeable`. |
| TK-05 | Ajustar deudas y transacciones Toku | Completada y verificada | El resumen muestra "Deudas pagadas" (`PAID`) y "Transacciones pagadas" (`SUCCESS`) del año seleccionado, con sus montos. |
| TK-06 | Mejorar ficha de método de pago Toku | Completada y verificada | La ficha agrupa información útil y omite tokens, BIN y metadatos técnicos. |
| TK-07 | Mejorar tabla de métodos de pago Toku | Completada y verificada | La tabla muestra cliente, tarjeta, banco y asociaciones como valores escalares, sin objetos ni RUT incorrecto. |
| TK-08 | Corregir relaciones de ficha de cliente Toku | Completada y verificada | Los extractores y la consolidación preservan el customer ID aunque Toku lo entregue como texto; la ficha relaciona suscripciones y métodos por ID o RUT normalizado, deudas por suscripción y transacciones por método de pago cuando no hay cliente directo. |
| TK-09 | Corregir cobros y ficha de suscripción Toku | Completada y verificada | Estado secundario y último cobro usan la última transacción `SUCCESS` de `payment_intents[].id_subscription`; la ficha vincula métodos, deudas y transacciones por el ID de suscripción. |
| TK-10 | Filtrar y ordenar estado secundario Toku | Completada y verificada | Filtro y orden global por estado secundario antes de paginar. No depende de `flow_name`; BLQ-TK-01 es externo y no la bloquea. 6 tests con `offset>0` en `tests/test_staging_api.py` (Toku y VirtualPOS). Unificada de Mantenimiento y Sprint 1. |
| TK-11 | Mejorar registros relacionados de suscripciones Toku | Completada y verificada | Cliente muestra RUT y estado; métodos de pago muestran estado; deudas y transacciones muestran estado y fecha en sus fichas relacionadas. |
| WR-TK-01 | Habilitar edición real de clientes Toku | Completada y verificada | `PUT /customers/:id` ejecutado desde modal; bdlocal actualizada; botón "Guardar cambios" operativo. |
| WR-TK-02 | Habilitar edición de invoices Toku | Completada y verificada | `PUT /invoices/:id` ejecutado desde la ruta interna `PUT /api/v1/writes/toku/invoices/{id}`; SourceRecord actualizado. |
| WR-TK-03 | Habilitar cambio de estado de suscripciones Toku | Completada y verificada | `POST /subscriptions/:id/status` ejecutado desde modal; bdlocal actualizada con nuevo estado. |
| WR-TK-04 | Habilitar eliminación de clientes Toku | Completada y verificada | `DELETE /customers/:id` ejecutado desde fila y ficha; registro marcado en bdlocal. |
| WR-TK-05 | Habilitar eliminación de invoices Toku | Completada y verificada | `DELETE /invoices/:id` ejecutado desde la ruta interna `DELETE /api/v1/writes/toku/invoices/{id}`; SourceRecord marcado como deleted. |
| WR-TK-06 | Habilitar eliminación de suscripciones Toku | Completada y verificada | `DELETE /subscriptions/:id` ejecutado desde la ruta interna `DELETE /api/v1/writes/toku/subscriptions/{id}`; suscripción marcada como deleted. |
| WFL-TK-01 | Revisar workflows Toku individualmente | Completada y verificada | 12 workflows revisados: 3 bloqueados (BLQ-TK-01), 9 parciales, 0 end-to-end completos. Discrepancia crítica en endpoint de asociación de medio de pago. Sin tabla `toku_payment_intents`. Ver `docs/integrations/toku/REVIEW.md`. Commit `aa0ef15`. |
| BLQ-TK-01 | Gestionar el bloqueante Toku: `flow_name` para ENROLLMENT | Bloqueada | Sin respuesta de Toku (DEC-01). Plan de acción en [BLOCKER-TK-A1](integrations/toku/BLOCKER-TK-A1.md): cinco workflows bloqueados identificados y alternativa Customer Portal con sus limitaciones. Requiere que Toku configure `flow_name` en producción. |
| BUG-TK-01 | Confirmar y corregir endpoint de asociación de medio de pago Toku | Completada y verificada | Corregido a `POST /subscriptions/associate/payment-method` con body `{id_subscription, id_payment_method, payment_scope}`; método renombrado a `associate_payment_method_to_subscription`. Confirmado en 3 workflow docs (alta-socio, link-inscripcion, enroll-payment-method). Sin callers en código. |
| WH-02 | Implementar receptor webhook Toku con verificacion HMAC-SHA256 | Completada y verificada | `/api/v1/webhooks/toku` con HMAC-SHA256 sobre `t.event_id`, idempotencia por `uq_stg_toku_webhook_toku_event_id`, tabla `stg_toku_webhook_events` activa, 11 tests pasan; registrado en `main.py` sin autenticacion JWT. |
| RISK-TK-01 | Corregir `cancel-subscription` Toku para hacer void de invoices impagas | Completada y verificada | `delete_subscription` consulta invoices unpaid/partially_paid antes del DELETE y anula las que no están in_progress; añade `list_subscription_invoices()` al TokuClient; commit f2f7ab2. |
| TK-12 | Configurar webhooks de Toku y procesarlos | Pendiente | Usuario: crear los webhooks en Toku y cargar los secretos `TOKU_WEBHOOK_SECRET` (hoy vacío) y `TOKU_SANDBOX_WEBHOOK_SECRET` (falta). Código: procesar los eventos; hoy el receptor (WH-02) solo los guarda en `stg_toku_webhook_events`. |
| TK-13 | Revisar el modelo y el ETL de Toku contra la API real | Pendiente | La API no devuelve `status` de cliente ni de suscripción. Medido el 2026-10-28: `recurring` y `recurring.status` existen solo si `is_recurring=true` (18 de 37 suscripciones del sandbox) y `remaining_collection_attempts`, `max_collection_attempts` y `expiration_date` pertenecen a la invoice (null en las 41); el header de versión no cambia las respuestas. Ajustar modelo, ETL, KPIs (MRR y ARPU de Toku cambian) y documentación a «suscripción activa efectiva» = no eliminada y medio `chargeable` (DEC-18). Depende de TK-20. |
| TK-14 | Incorporar datos de los reportes descargados de Toku (paraguas de TK-17 a TK-22) | En curso | Diseño hecho el 2026-10-28; implementación pendiente. El usuario descarga los reportes del Backoffice y se cargan por la interfaz (análogo a TCH), sin persistir datos personales. Hallazgos: los reportes están en dos carpetas del equipo; el más reciente (2026-10-20) contiene al anterior (2026-08-09) pero las filas mutan (basta cargar el nuevo; cargar uno viejo sobre uno nuevo es un error: guarda por fecha de generación); falta un reporte de Deudas actualizado (solo existe el del 2026-08-09, USR-09). Estructura: filas 1 a 6 con título y metadatos (fecha de generación, tipo de fecha, ventana) y encabezado en la fila 7, salvo excepciones (inscripciones de la carpeta antigua con encabezado en la fila 1 sin título; algunas hojas secundarias en la fila 1); el tipo de reporte se detecta por la firma de columnas, no por título ni nombre de archivo; hay columnas duplicadas («Medio de pago»), por lo que se leen por posición. `Estado` del reporte de Productos no es el estado de la suscripción: es el del medio de pago (`chargeable`, `temporary_failed`, `permanent_failed`, `deleted`, `permanently_deleted`) o vacío; el ciclo de vida se infiere de `Fecha de Eliminación` y, entre los eliminados, hay productos con `Estado` `chargeable`. `ID Producto` es texto libre, hace de `external_id` de la suscripción, contiene el RUT del socio y es el puente entre reportes (Intentos, Medios de pago y Deudas solo traen `ID Producto`; Productos trae además el `sub_`). `last_payment_intent_response_code` viene vacío en el 100 % de los medios de pago: el código por producto sale del último intento fallido del reporte de Intentos. Ningún reporte trae fecha de expiración de tarjeta: «tarjeta vencida» solo por código de rechazo. Cifras del reporte más reciente (agregadas): 658 productos (501 no eliminados; 178 con medio `chargeable`; 175 sin medio de pago), 31.359 intentos (92,4 % fallidos; gravedad SU 2.379, TE 28.082, PE 656, UE 185; códigos más frecuentes 1001 fondos insuficientes 13.361, 1008 tarjeta rechazada 11.037 y 2070 excede reintentos 1.976), 588 filas de medios de pago y 720 inscripciones. Racha de 3 o más: por intentos consecutivos 138 suscripciones frente a 72 por cuotas impagas consecutivas (Toku reintenta mucho: mediana de 13 intentos por cuota impaga, máximo 67). Privacidad: `.gitignore` ahora ignora `*.xlsx` y `*.xls` (los reportes tienen datos personales); ningún xlsx real en el repositorio ni en las pruebas. Modelo y decisiones en TK-17 a TK-22 y DEC-16 a DEC-25. Horas de IA estimadas por el agente de diseño: TK-14 a TK-22 unas 26 a 34 h, sin contar REC-04. |
| TK-15 | Cómo generar rechazos de prueba en el sandbox de Toku | Pendiente | La documentación oficial no trae tarjetas ni montos de prueba ni cómo simular TE, PE o UE (solo el portal sandbox de PAC; ver 3.5). Consulta a soporte de Toku pendiente, resumida en DEC-26 (seis preguntas). Ya no bloquea REC-04 (que depende de TK-20); sigue necesaria para las pruebas de rechazo de VAL-TK-01. |
| TK-16 | Guardas duras de escritura de Toku fuera de producción | Completada en código; verificación en sandbox pendiente | Commit e6202a7: host exacto, doble llave `TOKU_SANDBOX_WRITES_ENABLED` más `TOKU_SANDBOX_ALLOW_WRITES_ARMED` (variable de proceso), lista blanca de endpoints, prefijo `TEST-`, lista `TOKU_SANDBOX_ALLOWED_IDS` y tope `TOKU_SANDBOX_MAX_WRITES`; falla cerrada en `delete_subscription`. Variables de proceso: `TOKU_SANDBOX_ALLOW_WRITES_ARMED`, `TOKU_SANDBOX_ALLOWED_IDS` y `TOKU_SANDBOX_MAX_WRITES`. Los IDs que genera Toku (`cus_`, `sub_`, `in_`, `pm_`) nunca empiezan por `TEST-`, así que para modificarlos o borrarlos hay que listarlos en `TOKU_SANDBOX_ALLOWED_IDS`. |
| VAL-TK-01 | Suite de contrato de Toku | Pendiente | Réplica de `tests_contract/virtualpos` con las guardas de TK-16, empezando por lecturas. Cubre T-S1 (DEC-03) y los campos ausentes de TK-13. |
| TK-17 | Modelos y migraciones 0039 a 0041 de los reportes de Toku | Pendiente | Tablas nuevas `tk_report_files`, `tk_report_response_codes`, `tk_report_products`, `tk_report_payment_methods`, `tk_report_attempts`, `tk_report_debts`, `tk_report_inscriptions` y `core_subscription_signals`; no se reutilizan las `tk_*` porque la sincronización por API hace upsert completo y pisaría los datos del reporte con `status` null (DEC-19). Sin datos personales ni `raw_payload`; `ID Producto` solo como hash con pepper más el `sub_` resuelto (DEC-17). Migración 0039 (tablas `tk_report_*`), 0040 (`core_subscription_signals`) y 0041 (permiso `toku.reports.import`, solo admin). Estimación de IA: 3 a 4 h. Dependencia: TK-14. |
| TK-18 | Parser de reportes de Toku: encabezados por firma, resolución y upsert con guarda de fecha | Pendiente | Validación exacta de encabezados por firma de columnas, lectura por posición, resolución de `ID Producto` a `sub_`, hash del archivo y upsert idempotente por clave natural con guarda de fecha de generación y sin «des-eliminar» con NULL. Estimación de IA: 6 a 8 h. Depende de TK-17. |
| TK-19 | Ruta de subida, permiso, auditoría y panel de carga de reportes de Toku | Pendiente | Carga por la interfaz como TCH: POST de subida con respuesta 202, streaming con tope de tamaño, validación de zip, 409 si hay una corrida activa, archivo temporal borrado en `finally`, permiso `toku.reports.import` (DEC-22), registro del usuario, auditoría en `etl_runs` y panel de carga en administración con aviso si el dato supera 7 días (DEC-21). Estimación de IA: 4 a 5 h. Depende de TK-17 y TK-18. |
| TK-20 | ETL a core desde los reportes de Toku: señales y precedencia | Pendiente | Riesgo alto: define «activa». Señales en `core_subscription_signals` (activa efectiva, racha por cuotas impagas, tarjeta bloqueada, tarjeta vencida), `latest_rejection_*` de `core_charges` y regla de precedencia (DEC-23). Reglas en DEC-16, DEC-18, DEC-24 y DEC-25. Estimación de IA: 5 a 6 h. Depende de TK-18. |
| TK-21 | Pruebas del importador de reportes de Toku con fixtures sintéticas y guarda de datos personales | Pendiente | Fixtures sintéticas obligatorias; ningún xlsx real en el repositorio ni en las pruebas; guarda de pruebas que escanee RUT y correos reales. Estimación de IA: 4 a 5 h. Depende de TK-18 a TK-20. |
| TK-22 | Actualizar `docs/data/toku.md` con el contrato de columnas por reporte | Pendiente | Solo nombres de columnas, conteos y reglas, sin valores ni datos de personas. Estimación de IA: 1 a 2 h. Depende de TK-18. |

### 4.4 Payku

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| PK-01 | Sincronizar colecciones read-only de Payku a staging | Bloqueada | Payku devuelve transacciones recientes sin filtros, pero `date_init`/`date_end` devuelven cero incluso para un rango que contiene datos. El histórico requiere soporte o una exportación del proveedor. |
| PK-02 | Mejorar vistas staging de Payku | Completada y verificada | Cada recurso muestra sus métricas y columnas operativas específicas. |
| PK-03 | Migrar vistas Payku a BD local | Completada y verificada | Menú, tablas, fichas y dashboard Payku consultan las entidades centralizadas materializadas desde Payku_Local; sincronizar Payku rematerializa solo desde esa BD. |
| PK-04 | Corregir métricas y gráficos de ciclo de vida Payku | Completada y verificada | Transacciones, activaciones y bajas se agrupan por estado; activación usa `start` y caída usa `cancel`/`delete`/`suspended` con `end`. |
| PK-05 | Certificar la cobertura histórica de transacciones Payku | Bloqueada | Payku sincroniza transacciones embebidas sin filtros históricos confiables. El backfill local (`scripts/maintenance/backfill_payku_transactions.py`) ya reconstruye de forma idempotente `p_transactions` desde `source_records`; falta certificar cobertura, orden y paginación con el proveedor. Bloqueada solo por Q-08 y Q-11 (DEC-10). Dependencia corregida el 2026-10-28: Q-06 bloquea VAL-PK-01, Q-27 bloquea BLQ-PK-01 y Q-29 el link de inscripción. |
| WR-PK-01 | Habilitar edición de clientes Payku | Completada y verificada | `PUT /api/suclient/:id` ejecutado desde modal; campos de nombre, email y teléfono actualizados en bdlocal. |
| WR-PK-02 | Habilitar eliminación de suscripciones Payku | Completada y verificada | `DELETE /api/sususcription/:id` ejecutado desde fila y ficha; bdlocal actualizada. |
| WR-PK-03 | Habilitar eliminación de clientes suscripción Payku | Completada y verificada | `DELETE /api/suclient/:id` ejecutado desde fila y ficha; bdlocal actualizada. |
| WFL-PK-01 | Revisar workflows Payku individualmente | Completada y verificada | 13 workflows revisados: 5 no implementados, 8 parciales. Bug crítico: `_delete()` sin header `Sign` → 401 en producción en toda cancelación. Firma con trailing `&` en params vacíos. Email sin percent-encode. Ver `docs/integrations/payku/REVIEW.md`. Commit `027ffc9`. |
| BLQ-PK-01 | Confirmar el comportamiento del plan variable de Payku al activar (Q-27) | Bloqueada | Bloqueada por falta de sandbox de Payku y por la respuesta de soporte (DEC-10). Verificar en sandbox si el plan variable cobra al activarse; documentar si hay riesgo de cobro duplicado con el primer aporte Webpay; ajustar el flujo de alta antes de implementar el alta Payku. Unificada de Bloqueantes y Diferidos. |
| VAL-PK-01 | Resolver las preguntas abiertas de Payku (Q-xx) y crear su suite de contrato | Bloqueada | Bloqueada por la falta de credenciales de sandbox y la respuesta de soporte (DEC-10). Plan en [VALIDATION-PLAN de Payku](integrations/payku/VALIDATION-PLAN.md): Q-27, Q-06, Q-08, Q-11 y Q-29 ordenadas por impacto, con requests SP-3/SP-4. Parte 1, avanzable sin credenciales: `tests_contract/payku` con guardas que se omite sola sin credenciales. Parte 2, bloqueada: ejecutar la colección de validación y las preguntas Q-01, Q-02, Q-06, Q-08, Q-11, Q-27, Q-29 y Q-33, y actualizar el plan con los resultados. Unificada de Hito 5 y Sprint 6. |
| BUG-PK-01 | Corregir Sign header ausente en `_delete()` de Payku | Completada y verificada | `app/integrations/payku/client.py` `_delete()` añade el header `Sign` igual que `_get()` y `_post()`; 17/17 tests pasan. |
| BUG-PK-02 | Corregir trailing `&` en `build_sign` de Payku para params vacíos | Completada y verificada | `app/integrations/payku/auth.py` `build_sign` no genera `&` final cuando el diccionario de params está vacío; 17/17 tests pasan. |
| WH-03 | Implementar receptor webhook Payku | Completada y verificada | `/api/v1/webhooks/payku/{kind}` con autenticación por token query `?k=`, tablas `stg_payku_webhook_events` activa, 5 kinds soportados (subscription/payment/transaction/nullification/payout), 10 tests pasan; registrado en `main.py`. |
| PK-06 | Diseñar el modelo de cargos de Payku | Pendiente | Modelo de cargos con `p_cycles` más `p_transactions` ampliada y estado normalizado; avanzable sin credenciales, se valida en sandbox cuando existan. Insumo de REC-05. |

### 4.5 TCH

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| TCH-01 | Restaurar canal TCH y cargar reportes Excel | Completada y verificada | El menú respeta los permisos asignados, las tablas TCH están migradas y los reportes locales se cargan de forma idempotente. |
| TCH-02 | Añadir gráficos operativos al dashboard TCH | Completada y verificada | El resumen muestra series mensuales de cargos y altas, filtrables por año, cantidad y monto. |
| TCH-03 | Corregir histórico, fichas y navegación TCH | Completada y verificada | Fechas se reconstruyen desde reportes, cargos históricos son idempotentes, TCH abre su dashboard y sus objetos tienen ficha local. |
| TCH-04 | Añadir clientes TCH | Completada y verificada | El menú expone clientes TCH, la tabla permite buscar y paginar, y la ficha muestra mandatos asociados. |
| TCH-05 | Añadir contacto y equivalente TCH | Completada y verificada | Fichas de clientes muestran contacto y dirección; suscripciones muestran el equivalente en pesos del mandato. |
| TCH-06 | Conciliar cobros TCH con control mensual | Completada y verificada | Migración `20260916_0021` crea `tch_recaudacion_mensual`; el resumen y el dashboard general usan los controles mensuales oficiales para montos y cantidades; el detalle de mandatos y cargos queda en las tablas de trazabilidad. |
| TCH-07 | Importar reportes TCH desde administración | Completada y verificada | Solo el rol `admin` puede seleccionar un archivo `.xlsx`; la carga incremental queda registrada y no expone ni conserva el archivo temporal. |
| VAL-TCH-01 | Verificar de punta a punta el canal TCH | Pendiente | Excel a ETL a dashboard a recuperador (REC-06) con un caso de ejemplo sin PII, anotando brechas. |

### 4.6 Datos, sincronización, ETL y modelo centralizado

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| CORE-01 | Crear base tecnica del Core centralizado | Completada y verificada | Migraciones 0027–0033 aplicadas y versionadas; modelos Core en `app/models/core.py`; campos `source_status` y `last_payment_status` activos. |
| CORE-02 | Modelar cargos y pagos trazables | Completada y verificada | `CoreCharge.subscription_id` nullable (migración 0034, commit 1ecbf3a); cargos sin suscripción padre persisten con NULL. Campos `latest_rejection_*` modelados; pendiente VP-28 para poblarlos. |
| CORE-03 | Materializar los cuatro canales hacia el Core | Completada y verificada | VP, Toku, Payku y TCH materializan `source_status` y `last_payment_status` correctamente; TCH auditado en ETL-04 (commit 41bbdbe). |
| CORE-04 | Implementar identidad centralizada revisable | Completada y verificada | API `/core/identity/match-candidates` con GET (lista/filtro paginado), GET por id y POST review (confirmed/rejected); RBAC con `core.identity.read` y `core.identity.review`; sin merge automático (ADR-001); 4 tests pasan. Merge técnico queda como extensión futura con permiso separado. |
| CATALOG-01 | Crear catalogo consultable de mapeos y escenarios QA | Completada y verificada | API protegida expone mapeos fuente/STG/Core y escenarios sinteticos sin PII ni datos de pago reales. |
| STG-01 | Exponer staging por canal y rediseñar dashboard temporal | Completada y verificada | Dashboard resume staging local y cada canal consulta únicamente sus registros almacenados. |
| STG-02 | Crear mini dashboards operativos por canal | Completada y verificada | Cada canal muestra métricas, estados y actividad mensual desde staging local. |
| STG-03 | Crear fichas completas para Toku y Payku | Completada y verificada | Fichas locales muestran payload completo y relaciones explícitas por proveedor. |
| STG-04 | Añadir filtros para tablas Toku y Payku | Completada y verificada | Filtros por las columnas visibles y corrección de RUT de clientes Toku. |
| STG-05 | Traducir etiquetas visuales de fichas | Completada y verificada | Etiquetas en español y enlaces seguros para URLs de planes VirtualPOS. |
| CORE-PLAN-01 | Planificar implementacion del Core centralizado | Completada y verificada | Superada: el Core centralizado (migraciones 0027–0034, cuatro ETL, identidad parcial) ya está implementado. Ver PROJECT_STATE.md y CORE-02/03. |
| ETL-01 | Consolidar BDlocales en entidades centralizadas | Completada y verificada | VirtualPOS, Toku y Payku se materializan de forma idempotente desde sus BDlocales; los payloads saneados mantienen trazabilidad. |
| ETL-02 | Orquestar sync read-only y ETL en segundo plano | Completada y verificada | Las rutas `/api/v1/etl/run` y `/api/v1/etl/full-sync` registran estado y fase sin exponer credenciales. |
| DB-01 | Consolidar BDlocales en una sola base por tablas de canal | Completada y verificada | Los datos existentes se migran idempotentemente a las tablas prefijadas, sin nueva lectura completa de proveedores; CRM conserva filtros, orden y fichas. |
| WH-01 | Evaluar e incorporar webhooks de proveedores | Completada y verificada | Toku: receptor HMAC-SHA256 implementado (WH-02); Payku: receptor por token query implementado (WH-03). VirtualPOS: autenticidad no documentada; receptor postergado hasta confirmación. |
| AUD-01 | Auditar pendientes, dashboards, sincronizaciones y persistencia | Completada y verificada | Se identificaron tareas activas, brechas de paridad entre canales, riesgos de sincronizacion y la topologia PostgreSQL efectiva; los hallazgos se registraron sin exponer secretos. |
| SYNC-01 | Contratos de sincronización por canal: auditoría de idempotencia y verificación | En curso | Auditoría de idempotencia y trazabilidad de la consolidación: completada en el Sprint 1 (cinco brechas en `docs/data/sync-idempotency.md`). Verificación de contratos por canal: Payku alinea su lanzador con transacciones embebidas y VirtualPOS conserva cargos embebidos con conciliación agregada, rematerializando solo registros cambiados en cada run. Falta revisar el contrato histórico de Payku y completar la cobertura TCH. Unificada de Auditoría 2026-10-01 y Sprint 1. |
| DB-02 | Verificar topologia y dependencia de PostgreSQL | Completada y verificada | La aplicacion usa PostgreSQL 17 en `localhost:5433/crm`, con volumen persistente y revision `20260923_0022` en `head`; el esquema real y los datos por canal fueron verificados sin exponer secretos. |
| DB-03 | Reconciliar metadata Alembic y estadisticas PostgreSQL | Completada y verificada | La migracion `20261001_0023` alinea indices y metadata; `alembic check` no detecta operaciones pendientes y `ANALYZE` actualizo las estadisticas de tablas TCH voluminosas. |
| WR-INF-01 | Crear capa de servicio de escritura por proveedor | Completada y verificada | Módulos `app/services/write_virtualpos.py`, `write_toku.py`, `write_payku.py` implementados con manejo de errores HTTP, rollback local si la plataforma rechaza y registro durable en `write_runs`. |
| WR-INF-02 | Añadir rutas de escritura a la API interna | Completada y verificada | Endpoints POST/PUT/DELETE internos disponibles para VirtualPOS, Toku y Payku, documentados en Swagger y protegidos por CSRF y permisos. |
| BUG-ETL-01 | Mapear `source_status` en `core_vp_etl._materialize_charges` | Completada y verificada | `VpCharge.status` mapeado al campo `source_status` de `CoreCharge` en row dict y upsert; commit f587f1a. |
| BUG-ETL-02 | Mapear `last_payment_status` en `core_toku_etl._materialize_subscriptions` | Completada y verificada | Derivado desde última `TokuInvoice` por `due_date` por suscripción; mapeado en row dict y upsert; commit f587f1a. |
| BUG-ALB-01 | Registrar modelos webhook en `alembic/env.py` | Completada y verificada | `StgTokuWebhookEvent`, `StgVposWebhookEvent` y `StgPaykuWebhookEvent` importados; `alembic check` sin operaciones pendientes; commit f587f1a. |
| DATA-01 | Documentar modelo de datos VirtualPOS | Completada y verificada | Documento en docs/data/virtualpos.md con tablas de canal, campos clave, consolidación y brechas conocidas. |
| DATA-02 | Documentar modelo de datos Toku | Completada y verificada | Documento en docs/data/toku.md con tablas de canal, campos clave, consolidación y brechas conocidas. |
| DATA-03 | Documentar modelo de datos Payku | Completada y verificada | Documento en docs/data/payku.md con tablas de canal, campos clave, consolidación y brechas conocidas. |
| DATA-04 | Documentar modelo de datos TCH | Completada y verificada | Documento en docs/data/tch.md con ETL, tablas tch_* y brechas conocidas. |
| AUD-02 | Auditoria equipo multi-agente: arquitectura, ETL e integraciones | Completada y verificada | Arquitecto, Data Engineer e Integration Engineer revisaron estado; 3 bugs corregidos (BUG-ETL-01, BUG-ETL-02, BUG-ALB-01); 14 riesgos catalogados en integrations REVIEW.md; deuda tecnica actualizada en PROJECT_STATE.md. |
| ETL-03 | Evaluar nullable en `CoreCharge.subscription_id` (riesgo perdida silenciosa) | Completada y verificada | Migración 0034 hace nullable la columna; ETL VP inserta cargos sin suscripción con subscription_id=NULL en lugar de descartarlos; commit 1ecbf3a. |
| ETL-04 | Auditoria cobertura TCH en Core ETL | Completada y verificada | `core_tch_etl` implementado con clientes, atributos, suscripciones y pagos. Brecha: `last_payment_status` no se derivaba desde `TchTransaccion`. Corregido en commit 41bbdbe: índice por `numero_ficha`, upsert en `CoreSubscription`. |

### 4.7 Frontend, UI, KPI y gráficos

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| FE-01 | Modularizar el frontend (refactor de `App.tsx`) | Completada y verificada | Extraídos `api.ts`, `navigation.ts`, `components/Sidebar.tsx`, `hooks.ts` (commit 8d490e8, 7120 a 6730 líneas), `routes.ts` y `features/dashboard/OperationalAlerts.tsx` (reutilizado en todos los canales). La separación restante (navegación, carga de datos, dashboard y exploradores) se cerró en FE-02 (Sprint 0): `App.tsx` de una línea y 22 módulos en `features/`; build y lint correctos, contratos API y permisos preservados. Unificada de Mantenimiento y de la auditoría del 2026-10-01. |
| REP-01 | Generar reportes operativos por rango | Completada y verificada | VirtualPOS usa el diseño de referencia con snapshot histórico al cierre del rango, cobros y gráficos del período, alertas y tabla de activas; TCH usa su permiso de dashboard sin error 500. |
| UI-01 | Unificar paleta de gráficos | Completada y verificada | Todos los canales usan colores semánticos consistentes para sus estados y series. |
| UI-02 | Ajustar anchos y márgenes de vistas | Completada y verificada | El contenido usa todo el ancho disponible y las tablas conservan sus columnas sin recortarse. |
| UI-03 | Mejorar filtros y orden de tablas | Completada y verificada | Los filtros son claros y cada columna de datos permite ordenar ascendente o descendente. |
| UI-04 | Hacer visibles los controles de tabla | Completada y verificada | El orden es evidente y los campos de estado usan un selector de valores disponibles. |
| UI-05 | Ordenar registros completos desde la tabla | Completada y verificada | El orden usa campos seguros, incluidos anidados, y se aplica antes de paginar los registros. |
| UI-06 | Crear dashboard general consolidado | Completada y verificada | Inicio muestra KPIs, transacciones y activaciones mensuales de VirtualPOS, Toku, Payku y TCH desde sus entidades centralizadas. |
| UI-07 | Añadir clientes al dashboard general | Completada y verificada | Tabla consolidada por RUT muestra origen, suscripciones activas y ficha con IDs, suscripciones, cargos y transacciones relacionadas. |
| UI-08 | Añadir suscripciones al dashboard general | Completada y verificada | El submenú muestra suscripciones consolidadas con cliente, RUT, plataforma, estado, fechas y monto; permite filtrar y paginar; excluye fallidas VirtualPOS, rechazadas TCH y `register` Payku. |
| UI-09 | Corregir filtros y carga progresiva de tablas y reordenar el resumen operativo VirtualPOS | Completada y verificada | Los estados se obtienen de todos los registros del recurso y cada tabla permite cargar más resultados. El dashboard de VirtualPOS prioriza recursos, indicadores, estados y tendencias; elimina el mensaje de consolidación pendiente, muestra el último `SyncRun` real y evita duplicar gráficos de activación y caída. Unificada de dos filas con el mismo ID. |
| UI-10 | Mejorar leyendas y fichas del dashboard general | Completada y verificada | Los gráficos distinguen sus series por color y cada canal resume operación, staging y última sincronización en una ficha. |
| UI-11 | Mejorar clientes consolidados | Completada y verificada | La tabla muestra RUT, nombre, plataformas y suscripciones activas; permite buscar por RUT, nombre, apellido, plataforma, correo o teléfono. |
| UI-12 | Incorporar rutas navegables del CRM | Completada y verificada | Las vistas principales se abren mediante rutas SPA estables, soportan carga directa, recarga e historial sin modificar endpoints ni permisos existentes. |
| UI-13 | Incorporar rutas de fichas de proveedor | Completada y verificada | Las fichas de recursos de VirtualPOS, Toku y Payku usan identificadores externos en la URL, soportan carga directa e historial sin exponer atributos personales. |
| UI-14 | Conservar estado seguro de listados en URL | Completada y verificada | Los listados consolidado y de proveedores conservan paginación, selección de campo, estado, orden y cuenta VirtualPOS mediante query parameters sin incluir términos de búsqueda ni atributos personales. |
| UI-15 | Incorporar rutas de suscripciones TCH | Completada y verificada | La ficha de suscripción TCH usa `numero_ficha` de DUES, único en la proyección, con carga directa e historial sin exponer RUT. |
| UI-16 | Reordenar tablas y enlaces de VirtualPOS | Completada y verificada | Las cinco tablas de VirtualPOS priorizan campos operativos y abren las fichas desde los atributos solicitados, sin exponer identificadores técnicos como columna. |
| UI-17 | Ajustar relaciones en tablas y fichas VirtualPOS | Completada y verificada | Tablas y fichas muestran planes, clientes, suscripciones, cargos y transacciones solo mediante relaciones verificables del staging centralizado. |
| UI-18 | Completar transacciones relacionadas de VirtualPOS | Completada y verificada | Fichas de cliente y suscripción muestran transacciones del mismo cliente y cuenta por RUT; cargos y transacciones muestran el cliente disponible sin inferir asociaciones ambiguas. |
| UI-19 | Mejorar filtros y orden de tablas VirtualPOS | Completada y verificada | Los listados filtran múltiples columnas con AND, rangos explícitos de monto y fecha, y orden tipado; las tablas de fichas incorporan búsqueda y orden local por columna. |
| PERF-01 | Reducir esperas de navegacion en frontend | Completada y verificada | Los dashboards respetan caché local de cinco minutos sin revalidar en cada navegación; las solicitudes se deduplican, búsquedas y listados cancelan cargas obsoletas. La caché se invalida tras una sincronización. El diferimiento de gráficos mensuales queda pendiente de una extracción segura de vistas. |
| DASH-01 | Dar paridad operativa a Toku, Payku y TCH | Completada y verificada | Cada canal presenta KPIs, distribuciones, altas/bajas, suscripciones activas acumuladas, churn mensual y alertas definidos desde datos fechados y estados de su fuente. Toku compara transacciones reales, no facturas; Payku conserva el límite de cobertura histórica documentado; TCH usa reportes ETL locales. |
| FE-02 | Completar modularización App.tsx en feature folders | Completada y verificada | App.tsx < 500 líneas; features/virtualpos/, features/toku/, features/payku/, features/tch/, features/general/, features/admin/ extraídas; build y lint OK; contratos API y permisos preservados. Desbloquea grupos 2, 3 y 5. |
| FE-03 | Crear KpiCard.tsx y ChannelChart.tsx compartidos | Completada y verificada | Componentes en frontend/src/components/ con data contracts explícitos; JetBrains Mono en valores numéricos; tests básicos de render; usados por al menos un canal como validación. |
| KPI-01 | Estandarizar KPIs VirtualPOS/resumen | Completada en código; falta verificación contra VP staging | MRR, ARPU, suscripciones activas, churn mensual y cargos rechazados con `KpiCard`; rótulo «Cargos rechazados». Pendiente verificar las cifras contra VirtualPOS staging (acceso humano, USR-03). |
| KPI-02 | Estandarizar KPIs Toku/resumen | Completada y verificada | Mismos KPI canónicos para Toku; MRR desde suscripciones ACTIVE con método chargeable; nota visible "MRR desde suscripciones activas con medio de pago chargeable · Campos específicos de Toku". |
| KPI-03 | Estandarizar KPIs Payku/resumen | Completada y verificada | KPIs con nota visible de cobertura histórica no certificada; MRR desde última transacción success asociada. |
| KPI-04 | Estandarizar KPIs TCH/resumen | Completada y verificada | `kpis.recaudo_mensual` y transacciones mensuales desde tch_recaudacion_mensual; MRR, ARPU, clientes activos, churn y LTV desde TchSuscripcion (valores distintos, rotulados "Mandatos vigentes" y "Recaudo aceptado del mes"); nota "fuente: reportes Excel oficiales" visible al operador. |
| CHART-01 | Estandarizar gráficos VirtualPOS/resumen | Completada en código; verificación pendiente | ChannelChart.tsx con suscripciones activas acumuladas, cargos mensuales apilados y altas/bajas; datos verificados contra VP. Parcial: cifras pendientes de verificación contra VP staging (acceso humano); gráfico de actividad descartado por solapar con cargos; "Crecimiento real mensual" y "Churn %" siguen con componentes antiguos (ChannelChart no soporta porcentajes); "Transacciones vs Suscripciones" descartado (canal no indicado). |
| CHART-02 | Estandarizar gráficos Toku/resumen | Completada en código; verificación pendiente | Transacciones reales (no facturas) para tendencia de cobros; activaciones vs bajas; métodos por estado chargeable. Parcial: métodos por estado como foto actual; "Crecimiento real mensual" y "Churn %" con componentes antiguos. |
| CHART-03 | Estandarizar gráficos Payku/resumen | Completada en código; verificación pendiente | Series desde p_subscriptions y p_transactions; vacíos de cobertura anotados visualmente. Parcial: meses sin transacciones (coverage_gaps) anotados y nota de cobertura no certificada; "Crecimiento real mensual" y "Churn %" con componentes antiguos. |
| CHART-04 | Estandarizar gráficos TCH/resumen | Completada en código; verificación pendiente | Series desde tch_recaudacion_mensual; gráficos mensuales que requieran extracción de vistas diferidos hasta tener extracción definida. Parcial: nota de fuente según transacciones_fuente; "Crecimiento real mensual" y "Churn %" con componentes antiguos. |
| UI-20 | Auditoría y corrección de barra lateral | Completada en código; falta verificación visual en navegador | Navegación, permisos, comportamiento móvil, collapse y active states revisados y corregidos; no se rompen rutas existentes. Corregidos 4 bugs: estados activos de Dashboard y vistas generales, permisos tch.suscripciones.view / tch.transacciones.view en TCH, accesibilidad del menú móvil (aria-expanded, Esc, retorno de foco). Se mantiene drawer móvil; DESIGN.md pide top-bar (decisión del usuario). |
| UI-21 | Indicadores de salud de canal en sidebar | Completada en código; falta verificación visual en navegador | Punto verde/amarillo/rojo por canal según último SyncRun (verde <24h, amarillo <72h, rojo ≥72h o error); caché TTL 5min; sin bloquear render si falla. Endpoint GET /api/v1/sync-runs/health (permiso dashboard.view); hook useChannelHealth. Pendiente: contraste sobre #1a3d47/#091418 en navegador. |

### 4.8 Recuperador de socios

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| REC-01 | Crear Recuperador de Socios VirtualPOS | Completada y verificada | Módulo con Canceladas, Reintento de Cobros y Tarjetas Vencidas; acciones y trazabilidad protegidas por permisos. |
| REC-02 | Corregir y completar seguimiento de reintentos VirtualPOS | Completada y verificada | La identidad del cliente en cobros rechazados se obtiene desde relaciones verificables o desde el payload trazable de la suscripción cuando falta cliente materializado; los motivos ausentes se muestran como no informados por VirtualPOS; la confirmación de reintentos informa éxitos y fallos. El toggle conserva el historial completo de solicitudes y resultados conciliados. |
| REC-03 | Mejoras al recuperador de socios VirtualPOS | Completada en código; falta verificación visual en navegador y descarga real del CSV | Motivos de rechazo desde latest_rejection_* con catálogo oficial de códigos; filtros por cuenta, código, monto, estado secundario y fecha de rechazo antes de paginar; exportación CSV con columnas de trazabilidad (datos personales solo con permiso de exportar); auditoría en `write_runs` sin contenido ni datos personales; módulo frontend `features/recovery` con el canal como parámetro (hoy solo virtualpos; ruta sin cambios; listo para mover en Sprint 5). Falla preexistente no causada por este trabajo: `tests/test_charge_recovery.py::test_retry_history_endpoint_returns_items_and_total` (la base de pruebas acumula filas). |
| REC-04 | Recuperador Toku en módulo general | Pendiente | Endpoints de recuperación Toku (canceladas, rechazadas) desde core_subscriptions y core_charges (source=toku); entrada de sidebar movida a `/general/recuperador` con pestaña Toku; permisos RBAC aplicados. Depende de TK-20 (señales de «activa efectiva», racha por cuotas, bloqueada y vencida desde los reportes de Toku); ya no depende de TK-15. |
| REC-05 | Recuperador Payku en módulo general | Pendiente | Pestaña Payku en `/general/recuperador`; advertencia de cobertura histórica limitada visible; endpoints desde core_* (source=payku). Depende del modelo de cargos de Payku (PK-06) y de explorarlo en sandbox con credenciales. |
| REC-06 | Recuperador TCH en módulo general | Pendiente | Tab TCH en /general/recuperador; sin acciones de escritura remota (TCH es solo Excel); mandatos eliminados y cargos rechazados accesibles. |
| E2-BATCH | Batch recovery: selección múltiple y reintento en lote | Diferida | Diferida hasta que REC-04 a REC-06 (recuperador multicanal) estén estables; sprint posterior. |

### 4.9 Identidad y permisos

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| AUTH-01 | Implementar autenticación, roles y permisos por módulo | Completada y verificada | Login con cookie HttpOnly y CSRF; usuarios con varios roles; backend protege rutas y React oculta canales/tablas no autorizados. |
| AUTH-02 | Administración de usuarios y roles | Completada y verificada | Roles y usuarios se administran desde el panel: creación, asignación múltiple de roles, edición, desactivación, restablecimiento de contraseña y administración del catálogo fijo de permisos. Las rutas exigen permiso y CSRF; la suite focalizada valida el flujo. |
| AUTH-03 | Evitar pérdida del último administrador activo | Completada y verificada | No se puede desactivar ni quitar el rol `admin` al último usuario activo que lo posee; la regla queda cubierta por pruebas. |

### 4.10 Infraestructura, operación, desarrollo y documentación

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| ENV-01 | Separar Sandbox, QA y Producción | En curso | Cada entorno con base, credenciales y proveedores propios; Producción en un cluster PostgreSQL independiente; proceso de deploy y migración por entorno documentado. Hecho: `APP_ENV` (`production`/`sandbox`/`qa`) selecciona las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL` del único `.env`; guarda de arranque contra URLs y credenciales de otro ambiente; canal sin URL de sandbox deshabilitado (VirtualPOS cuenta 2 y Payku en sandbox) y el sync lo omite con aviso; selector de ambiente en administración; `WRITES_ENABLED` apagados por defecto; scheduler apagado en sandbox por defecto. VirtualPOS tiene sandbox documentado; Toku comparte host con producción y usa otras llaves (guardas en TK-16); Payku sin credenciales. Pendiente: credenciales de sandbox de Toku y Payku, cluster independiente y proceso de deploy (DEC-11). Unificada de Hito 4 y Sprint 6; se corrigió que `APP_ENV` cargara `.env.sandbox`/`.env.qa` (el código usa un solo `.env`). |
| BCK-01 | Automatizar respaldo y recuperación autogestionados | Pendiente | Backup físico con WAL/PITR más dump lógico; verificación, retención y política de retención definidas; simulacro de restauración documentado. Depende de DEC-11 (hosting, RPO y RTO). Unificada de Hito 4 y Sprint 6. |
| BCK-02 | Crear punto de restauracion previo al Core | Completada y verificada | Rama, tag, dump logico y snapshot fisico local verificados antes de la primera migracion Core. |
| STR-01 | Reorganizar estructura del repositorio | Completada y verificada | Artefactos locales quedan fuera de la raiz y excluidos de Git; scripts, documentacion vigente/historica y referencias quedan organizados sin romper comandos ni enlaces. |
| MT-01 | Actualizar rama local desde GitHub | Completada y verificada | `master` queda alineada con `origin/master` sin sobrescribir cambios locales. |
| OPS-07 | Levantar servicios y verificar la base consolidada | Completada y verificada | PostgreSQL saludable en `localhost:5433`, migraciones en `head` (0036 al cierre del Sprint 0), API `/health` y frontend operativos, tablas por canal verificadas en la base `crm`; incluyó el arreglo de la migración 0035 (`op.Column` por `sa.Column`). |
| OPS-08 | Ejecutar sincronización manual multicanal | Completada y verificada | VP: `_records_from_response` retorna `[]` en lugar de ValueError para dict vacío o sin clave conocida (commit f3e3f92). Payku: duplicados ON CONFLICT ya cubiertos por deduplicación `seen` en `upsert_channel`. |
| DEV-04 | Establecer dependencias bloqueadas y CI en verde | Completada y verificada | `.python-version`, `requirements.lock` y CI de backend y frontend; ruff I001 y BLE001 corregidos; test de envelope VP actualizado (OPS-08); build y lint de frontend limpios (commit 8cab09c). Estado al 2026-10-28: `ruff` limpio, backend 844 y frontend 179 pruebas pasan. Unificada: la fila «En curso» (7 fallos de pytest y 74 hallazgos de Ruff) quedó superada por la fila «CI en verde». |
| DOC-03 | Estructurar documentación como vault de Obsidian | Completada y verificada | Índice navegable, arquitectura, producto, datos, integraciones, decisiones, memoria y sesiones creados sin modificar código ni configuraciones. |
| DOC-04 | Inicializar memoria persistente y modelo conceptual | Completada y verificada | Estado, decisiones, riesgos y modelo conceptual documentados sin modificar componentes técnicos. |
| DOC-05 | Normalizar terminología del modelo centralizado | Completada y verificada | La documentación activa usa "modelo centralizado" sin renombrar identificadores técnicos de compatibilidad. |
| DOC-06 | Consolidar instrucciones operativas de agentes | Completada y verificada | `AGENTS.md` define contexto, prioridades, arquitectura, memoria, Context7, validación y seguridad sin modificar componentes técnicos. |
| DOC-07 | Crear skill local project-memory | Completada y verificada | Skill Markdown descubierta tras reiniciar OpenCode; gestiona memoria, ADRs, contradicciones y crecimiento documental. |
| DOC-08 | Crear skill local data-modeling | Completada y verificada | Skill Markdown para diseñar y revisar el modelo centralizado sin acoplar Core a proveedores; descubrimiento, ruta y frontmatter validados en una nueva sesión de OpenCode. |
| DOC-09 | Definir identidad centralizada de socios | Completada y verificada | ADR-001 acepta UUID interno, identidades externas trazables, matching conservador, revision manual y merges reversibles sin implementar esquema tecnico. |
| DOC-10 | Crear skill local provider-integration | Completada y verificada | Skill Markdown para estandarizar connectors, Raw/STG, contratos, seguridad y operacion de proveedores; descubrimiento confirmado en OpenCode. |
| DEV-01 | Asegurar y reproducir configuracion de IA | Completada y verificada | `cookies.txt` queda ignorado; configuracion y skills de OpenCode quedan versionables; `AGENTS.md` es la unica jerarquia de instrucciones compartida. |
| DEV-02 | Consolidar herramientas de IA y vault Obsidian | Completada y verificada | OpenCode mantiene Context7 compartido; Claude conserva ajustes locales; el vault se abre desde la raiz y `.obsidian/` queda local. |
| DEV-03 | Corregir consistencia del entorno local | Completada y verificada | Vite redirige `/api` a FastAPI en `127.0.0.1:8000`; el healthcheck de PostgreSQL usa `POSTGRES_USER` y `POSTGRES_DB` de Compose. |
| DEV-05 | Completar agentes documentales de OpenCode | Completada y verificada | Las definiciones locales `obsidian-vault` y `adr-governance` se validan con el cargador de OpenCode; el vault distingue navegacion de fuente tecnica y refleja que ADR-001 no esta implementado tecnicamente. |
| DOC-01 | Actualizar documentación del proyecto | Completada y verificada | Tareas, operación, arquitectura y proveedores reflejan el estado actual sin datos de pago sensibles. |
| DOC-02 | Documentar API VirtualPOS | Completada y verificada | `docs/history/integrations/virtualpos-appscript-research.md` conserva la investigación histórica de rutas, contratos, autenticación, paginación y estrategia incremental. |
| OPS-01 | Corregir configuración de sincronización local | Completada y verificada | VirtualPOS confirmó una sincronización idempotente; Toku se sincronizó correctamente con 21 registros y una segunda ejecución idempotente de 0 registros usando `api.trytoku.com`. No se expusieron credenciales. |
| OPS-02 | Robustecer sincronización read-only de Toku | Completada y verificada | Reintenta hasta dos `ReadTimeout` de solicitudes GET y configura 120 segundos por intento; prueba automatizada validada. |
| OPS-03 | Robustecer sincronización read-only de Payku | Completada y verificada | Reintenta hasta dos `ReadTimeout` de solicitudes GET y configura 120 segundos por intento; prueba automatizada validada. |
| OPS-04 | Completar paginación de VirtualPOS | Completada y verificada | Clientes, pagos, suscripciones y cargos recorren todas las páginas con `page` y `limit`; prueba automatizada validada. |
| OPS-05 | Mostrar progreso y robustecer la sync histórica manual | Completada y verificada | Los scripts manuales de VirtualPOS, Toku y Payku muestran recurso y avance por página (porcentaje cuando el proveedor informa totales; páginas y registros procesados en caso contrario); VirtualPOS reintenta lecturas y usa 120 segundos por intento sin omitir el historial. Unificada de dos filas con el mismo ID. |
| OPS-06 | Respetar límite de transacciones Toku | Completada y verificada | Pausa un segundo entre páginas y reintenta respuestas temporales 429/503. |
| MT-02 | Corregir relaciones y métricas VirtualPOS desde BD local | Completada y verificada | Clientes relacionan suscripciones por RUT; cargos muestran suscripción; KPIs filtran estados operativos y el monto de suscripciones se materializa desde la BD local. |
| MT-03 | Desglosar gráficos mensuales por estado | Completada y verificada | Actividad, cargos, transacciones y activaciones muestran barras apiladas por estado. |
| OPS-09 | Evaluar la entrega de progreso en tiempo real | Pendiente | Decisión documentada: el SSE actual se mantiene o evoluciona a WebSocket o infraestructura compartida, con autenticación, reconexión y persistencia de eventos evaluadas; no se confunde el transporte al navegador con la lectura de proveedores. Sprint 6. Unificada de Auditoría 2026-10-01 y Sprint 6. |
| OPS-10 | Guarda contra downgrade accidentales de Alembic | Completada en código | `alembic/env.py` llama a `check_downgrade_allowed` (`app/db/migration_guard.py`): ningún `downgrade` (CLI o `alembic.command.downgrade`) corre si la base no termina en `_test` ni contiene `sandbox` o `qa`, salvo `ALEMBIC_ALLOW_DOWNGRADE=1` en el proceso (documentada en `.env.example`). Los `upgrade` no cambian. `tests/test_migration_guard.py` (lógica pura, inspección de `env.py` y round-trip programático solo en `crm_test`). Origen: incidente del 2026-10-28 (§7.2). |
| WFL-INF-01 | Incorporar workflows a docs/integrations/ y crear capa transversal | Completada y verificada | `docs/integrations/virtualpos/`, `docs/integrations/toku/` y `docs/integrations/payku/` estructurados por flujo operacional (29+24+36 archivos); `docs/integrations/transversal/` creada con link seguro de inscripción, seguimiento común y cambio de monto; los tres `docs/integrations/*.md` actualizados. Commit `7b1c0d7`. |
| DOC-11 | Actualizar `docs/architecture/overview.md` con estado real de identidad | Completada y verificada | Seccion "Limite actual" reemplazada por estado parcialmente implementado con referencia a ADR-001 y CORE-04; commit f587f1a. |

### 4.11 Acciones del usuario o de terceros

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| USR-01 | Aplicar migraciones 0037/0038 y seed de roles en cada base | Pendiente | `alembic upgrade head` y `scripts/maintenance/seed_roles.py`. En `crm_sandbox` (con `APP_ENV=sandbox`) los aplica el orquestador avisando al usuario (DEC-28); en `crm` (producción o local productiva) siempre el usuario, nunca un agente (incidente del 2026-10-28, OPS-10). Sin esto no existen los permisos ni el rol `ejecutivo` en la base y la Opción A no funciona en esos ambientes. |
| USR-02 | Revisión visual en navegador | Pendiente | Usuario: Sprints 3 y 4 (franja de sandbox, tema oscuro, menú móvil, contraste de los puntos de salud, gráficos, recuperador y descarga real del CSV), bandeja de cambios de cobro y pestaña Renovaciones. |
| USR-03 | Verificar KPI-01 y CHART-01 contra VirtualPOS staging | Pendiente | Usuario: acceso humano a VP staging. |
| USR-04 | Respuesta del soporte de Payku | Pendiente | Usuario: activar el sandbox y responder las preguntas Q-xx (DEC-10). |
| USR-05 | Tarjetas de prueba de rechazo | Pendiente | Usuario: tarjetas con rechazo y cambio de tarjeta para V-2 a V-4 de VirtualPOS y mecanismo de rechazos de Toku (DEC-09). |
| USR-06 | Apagar los túneles de Cloudflare | Pendiente | Usuario: los túneles son públicos y solo los protege el login; buscar con `Get-Process cloudflared` y detener con `Stop-Process`. Las URLs cambian en cada arranque. |
| USR-07 | Crear usuarios `soporte` y `ejecutivo` en cada ambiente | Pendiente | Usuario: cada ambiente tiene su propia base de usuarios; hoy no hay usuarios con rol `soporte`. Evaluar también un secreto JWT propio para sandbox. |
| USR-08 | Subir la rama y abrir PR | Pendiente | Solo cuando el usuario lo pida: hoy `sprint-4/recuperador-vp` tiene 14 commits locales sin subir y no hay PR abierto; `master` local está un commit adelante del remoto. |
| USR-09 | Exportar un reporte de Deudas de Toku actualizado | Pendiente | Usuario: descargar del Backoffice de Toku un reporte de Deudas nuevo (hoy solo existe el del 2026-08-09) y luego exportar los reportes cada semana (DEC-21). Insumo de TK-14. |
| USR-10 | Aplicar las migraciones 0039 a 0041 y repetir el seed de roles cuando existan | Pendiente | Ampliar USR-01 (0037 y 0038) con las migraciones 0039 a 0041 (TK-17): `alembic upgrade head` y `scripts/maintenance/seed_roles.py`. En `crm_sandbox` los aplica el orquestador avisando al usuario (DEC-28); en `crm` siempre el usuario, nunca un agente (OPS-10). El permiso `toku.reports.import` queda solo para admin (DEC-22). El webhook de Toku ya está cubierto por TK-12. |
| USR-11 | Revisar el estado de `crm` tras el incidente de Alembic | Pendiente | Usuario: `crm` quedó en `20261028_0041` (migrada por un agente, sin que el usuario lo decidiera); revisar si es lo deseado, correr `scripts/maintenance/seed_roles.py`, y considerar un respaldo (`pg_dump`) antes de futuras migraciones: el último respaldo es del 2026-10-07 (pre-core). Ver nota de sesión del 2026-10-28 (incidente de Alembic). |

### 4.12 Horizonte sin sprint asignado

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| HOR-01 | Contrato de liquidaciones y taxonomía común | Diferida | Contrato transversal de liquidaciones y taxonomía común de estados, montos, monedas y periodicidad. Sin sprint asignado. |
| HOR-02 | Gobierno de datos personales | Diferida | Gobierno de atributos personales, retención y rectificación; conflictos entre fuentes. Sin sprint asignado. |
| HOR-03 | Migrar las lecturas del frontend hacia el Core | Diferida | Deprecar gradualmente las proyecciones por canal sin romper contratos vigentes. Sin sprint asignado. |
| HOR-04 | Analítica predictiva | Diferida | Evaluar solo con datos trazables y suficientes, en una fase posterior. |

### 4.13 Unificaciones realizadas

Para auditoría: filas que existían más de una vez en la versión anterior de este archivo (12 IDs, 12 filas sobrantes) y cómo quedaron. En todos los casos prevalece el estado más reciente y se combinan los criterios.

- **ENV-01** (Hito 4 «Parcial» y Sprint 6 «Parcial»): una fila, estado En curso; se integraron los hechos de ambientes del handoff y se corrigió que `APP_ENV` cargara `.env.sandbox`/`.env.qa` (el código usa un solo `.env`). Unificada de Hito 4 y Sprint 6.
- **BCK-01** (Hito 4 y Sprint 6, ambas Pendiente): una fila; se sumó la política de retención y la dependencia de DEC-11. Unificada de Hito 4 y Sprint 6.
- **OPS-05** (dos filas «Completada» con títulos distintos sobre progreso de sincronización): una fila con ambos criterios.
- **DEV-04** (una fila «Completada» con CI en verde, commit 8cab09c, y otra «En curso» con 7 fallos de pytest y 74 hallazgos de Ruff): una fila Completada y verificada; la fila «En curso» estaba superada. Se agregó el estado de pruebas actual.
- **FE-01** («Completada parcial», commit 8d490e8, y «En curso» de la auditoría del 2026-10-01): una fila Completada y verificada, porque FE-02 (Sprint 0) terminó la modularización. Unificada de Mantenimiento y Auditoría 2026-10-01.
- **UI-09** (dos tareas distintas con el mismo ID: «Corregir filtros y carga progresiva de tablas» y «Reordenar resumen operativo VirtualPOS», ambas Completadas): una fila con ambos criterios; el ID no se renumeró.
- **SYNC-01** (Sprint 1 «Auditar idempotencia» Completada y Auditoría 2026-10-01 «Corregir y verificar contratos» En curso): una fila En curso con la auditoría marcada como completada y la verificación de contratos como pendiente. Unificada de Auditoría 2026-10-01 y Sprint 1.
- **TK-10** (Mantenimiento y Sprint 1, ambas Completada): una fila con los criterios del Sprint 1. Unificada de Mantenimiento y Sprint 1.
- **OPS-09** (Auditoría 2026-10-01 y Sprint 6, ambas Pendiente): una fila. Unificada de Auditoría 2026-10-01 y Sprint 6.
- **VAL-VP-01** (Hito 5 «En curso» y Sprint 6 «En curso»): una fila En curso; se agregó V-1 resuelta, V-5 ejecutada y el enlace al plan. Era la «doble fila VAL-VP-01» que el handoff anotaba como deuda menor. Unificada de Hito 5 y Sprint 6.
- **VAL-PK-01** (Hito 5 y Sprint 6, ambas «En curso»): una fila Bloqueada, con su parte 1 avanzable (suite `tests_contract/payku`) y la parte 2 bloqueada; se agregó Q-01, Q-02 y Q-33. Unificada de Hito 5 y Sprint 6.
- **BLQ-PK-01** (Bloqueantes «Pendiente» y Diferidos del antiguo `TODOS.md`): una fila Bloqueada con la razón del diferimiento. Unificada de Bloqueantes y Diferidos.
- **Normalización de estados:** «Completada» pasó a «Completada y verificada»; «Parcial», «Completada parcial», «Implementada…» y «Pendiente (bloqueada por…)» pasaron al vocabulario único (ENV-01, FE-01, KPI-01, WR-VP-05, PK-05); BLQ-TK-01 «En curso» pasó a Bloqueada; UI-20 y UI-21 pasaron a «Completada en código».
- **Duplicación de contenido en otros archivos:** las tablas de sprint de `CURRENT_SPRINT.md` (REC-03, WR-VP-05, PK-05, CHART, KPI, DATA, TK-10, SYNC-01, OPS-07, FE-02), las tablas del «Hito 6» de este archivo y la hoja de ruta se reemplazaron por las secciones 2 y 3 más las filas únicas de la sección 4.
- **Sección 5:** las referencias usan la familia DEC y citan los IDs en prosa, para no repetir IDs como primera columna.

## 5. Bloqueos y decisiones abiertas

Las referencias de la primera columna son propias de esta sección (familia DEC); el ID de la tarea afectada va en la prosa.

| Ref. | Tema | Estado | Quién o qué lo desbloquea | Impacto y siguiente paso |
| --- | --- | --- | --- | --- |
| DEC-01 | BLQ-TK-01 (T-A1): Toku debe configurar `flow_name` para el Checkout de inscripción (ENROLLMENT) | Bloqueada, sin respuesta de Toku | Soporte de Toku (escalar) | Bloquea el alta de socios y el cambio de tarjeta en Toku. No bloquea KPIs ni el estado secundario. La alternativa Customer Portal (`flow_name: "0"`) no es apta para producción. Detalle: [BLOCKER-TK-A1](integrations/toku/BLOCKER-TK-A1.md) |
| DEC-02 | T-A2: host real del Checkout de Toku, desconocido hasta la primera sesión real | Abierta | Primera sesión real de Checkout (depende de DEC-01) | No se puede completar la lista de hosts permitidos de la capa común ni validar el origen del link en producción |
| DEC-03 | T-S1: ambigüedad sobre si `start_date` y `end_date` de `GET /transactions` filtran por `transaction_date` o por `initialization_date` | Abierta | Medición en sandbox de Toku o respuesta de soporte (VAL-TK-01 puede medirla con lecturas) | Afecta la ventana del job diario de seguimiento de cobros |
| DEC-04 | SYNC-GAP-02: ¿un rechazo y un pago posterior de la misma cuota TCH son dos cargos distintos? | Decisión de negocio pendiente | Usuario | Caracterizado con 9 tests en `tests/test_etl_tch.py` y el script de solo lectura `scripts/maintenance/audit_tch_duplicate_cuotas.sql`. Define la clave de deduplicación del ETL TCH |
| DEC-05 | GB-RZ-13: rechazo por límite del comercio (`-1003`, `-1009`, …): ¿cuenta para la racha del socio? | Abierta (propuesta: no) | Usuario | Define el clasificador de rechazos y la alerta a finanzas. Ver el documento de escenarios |
| DEC-06 | GB-RZ-17: una pausa registrada entre dos rechazos, ¿corta o suma la racha? | Abierta (propuesta: ni corta ni suma) | Usuario | Baja prioridad: la racha es solo una ayuda opcional de lectura |
| DEC-07 | GB-JB-09: M-1 y M0 sin cubrir con ambas fechas pasadas, ¿dos cobros el mismo día o espaciados? | Abierta (propuesta: espaciar, M-1 mañana y M0 pasado mañana) | Usuario | Afecta el cálculo del plan de BILL-03/BILL-04 en la ventana de 31 días |
| DEC-08 | Destino de `docs/designs/reconciliacion-identidad-socios.md` (documento del usuario, sin versionar) | Abierta | Usuario | Decidir si se versiona, se integra a ADR-001/CORE-04 o se descarta. Mientras tanto no se toca |
| DEC-09 | Tarjetas de rechazo para pruebas | Abierta | Usuario | VirtualPOS: tarjetas de prueba con rechazo y cambio de tarjeta para V-2 a V-4 (requieren esperar días). Toku: cómo generar rechazos en sandbox (TK-15) |
| DEC-10 | Soporte de Payku: activar el sandbox y responder las preguntas Q-01, Q-02, Q-06, Q-08, Q-11, Q-27, Q-29 y Q-33 | Abierta, a cargo del usuario | Soporte de Payku | Dependencias: Q-08 y Q-11 bloquean PK-05; Q-06 bloquea VAL-PK-01; Q-27 bloquea BLQ-PK-01; Q-29 bloquea el link de inscripción (caso A de alta pendiente). Q-01, Q-02 y Q-33 afectan la firma y la validación general. Detalle: [VALIDATION-PLAN de Payku](integrations/payku/VALIDATION-PLAN.md) |
| DEC-11 | Sprint 6: hosting, RPO y RTO objetivo, credenciales de sandbox de Toku y Payku | Abierta | Usuario | Sin esto no se pueden cerrar ENV-01 ni BCK-01 |
| DEC-12 | Sprint 6: quién ejecuta las validaciones de contrato (VAL-*) y las pruebas con tarjeta | Abierta | Usuario | Varias pruebas necesitan acceso humano, tarjeta y espera de fechas de cobro |
| DEC-13 | `monto_vigente` no está registrado como ADR | Abierta | Usuario | Decisión vigente (ver 1.5) usada por ETL, KPIs y recuperador; evaluar registrarla como ADR |
| DEC-14 | UI-20: el drawer móvil se mantiene aunque `DESIGN.md` pide top-bar | Abierta | Usuario | Discrepancia anotada; no se cambió |
| DEC-15 | Continuidad de cobros mensuales en WR-VP-05 antes de activar la bandera en producción | Abierta | Usuario | La Opción A (BILL-04) fija horizonte de 12 meses con automáticos posteriores como red de seguridad; falta la prueba controlada en producción |
| DEC-16 | D1: la racha se mide por cuotas impagas «en firme», no por intentos | Resuelta (2026-10-28) | Usuario | Una cuota está impaga en firme con código 2070 o tras cierto número de días sin intento. Medido: racha de 3 o más son 72 suscripciones por cuotas frente a 138 por intentos consecutivos. Implementa TK-20 |
| DEC-17 | D2: `ID Producto` se guarda solo como hash más el `sub_` resuelto | Resuelta (2026-10-28) | Usuario | El campo contiene el RUT; no se persiste en claro. Implementan TK-17 y TK-18 |
| DEC-18 | D3: «suscripción activa» de Toku = no eliminada y medio de pago `chargeable` | Resuelta (2026-10-28) | Usuario | El estado secundario queda visible. Cambia MRR y ARPU de Toku (TK-13); define TK-20 |
| DEC-19 | D4: los reportes van en tablas nuevas `tk_report_*` y `core_subscription_signals` | Resuelta (2026-10-28) | Usuario | No se reutilizan las `tk_*` porque la sincronización por API las sobrescribiría. TK-17 |
| DEC-20 | D5: la carga de reportes de Toku se hace por la interfaz | Resuelta (2026-10-28) | Usuario | Análogo a TCH. TK-19 |
| DEC-21 | D6: exportación semanal de reportes con aviso si el dato supera 7 días | Resuelta (2026-10-28) | Usuario | Incluye exportar ya un Deudas nuevo (USR-09). TK-19 |
| DEC-22 | D7: permiso propio `toku.reports.import`, solo admin al inicio | Resuelta (2026-10-28) | Usuario | Migración 0041 (TK-17) |
| DEC-23 | D8: precedencia entre reporte y API | Resuelta (2026-10-28) | Usuario | El reporte gana para estado y medio de pago cuando es más reciente que el último sync de API; la API gana para montos y facturas. TK-20 |
| DEC-24 | D9: «tarjeta bloqueada» y «vencida» | Resuelta (2026-10-28) | Usuario | Bloqueada = código 1019 o medio `permanent_failed` (con el motivo visible); se incorporan del catálogo oficial de Toku 1051 (bloqueada en primer uso) y 2043 (lista negra) como bloqueada y 2044 (junto a 1010 y 2063) como vencida, aunque no estén entre los 24 códigos observados en los reportes. TK-20 |
| DEC-25 | D10: un medio con falla temporal sin racha no es recuperable | Resuelta (2026-10-28) | Usuario | Definición de recuperable sin cambios: racha de 3 o más cuotas impagas seguidas, o tarjeta bloqueada, o tarjeta vencida. REC-04 |
| DEC-26 | Consultas a soporte de Toku (seis preguntas) | Abierta, a cargo del usuario | Soporte de Toku | (1) ambiente de pruebas oficial; (2) tarjetas y montos de prueba para TE, PE y UE, y cómo generar una transacción fallida y medios en `temporary_failed`, `permanent_failed` e `inscription_failed`; (3) regla exacta de paso a `permanent_failed` y su combinación con `max_collection_attempts`; (4) dónde se expone el estado de una suscripción no recurrente y cómo se cancela; (5) entrega de webhooks (2xx frente a 200, secreto en GET, retención); (6) permisos de la API de reportes. Relacionada con TK-15, TK-12 y VAL-TK-01 |
| DEC-27 | Aprobación del [runbook de pruebas en sandbox y decisiones](operations/sandbox-testing-and-decisions.md) | Resuelta (2026-10-28) | Usuario | Condición literal: en sandbox sin problema; en producción siempre con el usuario y más cuidado. Es la autorización explícita de CLAUDE.md §9, limitada a sandbox y a escenarios catalogados. Resuelve las seis decisiones abiertas del redactor: escritura permanente solo en escenarios catalogados (los nuevos se avisan antes); las 8 pruebas CT-xx se aprueban en bloque una vez escritas (el orquestador registra un DEC-xx al aprobar la receta; las de tarjeta o espera de fechas se coordinan); el Excel sintético de TCH se carga con el servicio de importación directo con `APP_ENV=sandbox` contra `crm_sandbox`; límites de 2 vueltas, 1 reintento de limpieza, 30 cobros, 100 GET y 50 filas; el runbook vive en `docs/operations/`. Ante la duda sobre el ambiente se trata como producción (Toku comparte host; `APP_ENV=development` equivale a producción). Afecta BILL-11 |
| DEC-28 | Migraciones y seeds en `crm_sandbox` | Resuelta (2026-10-28) | Usuario | El orquestador o el decisor pueden aplicarlos en `crm_sandbox` avisando al usuario; en `crm` (producción o local productiva) nunca: siempre el usuario. Actualiza USR-01 y USR-10 |
| DEC-29 | Decisiones del usuario sobre la revisión independiente de la Opción A | Resuelta (2026-10-28); implementación pendiente en parte | Usuario | (1) Los arreglos van en tres tandas: A = BILL-17, BILL-19 y BILL-20. (2) Mes con solo cobros cancelados: revisión manual. (3) Mes sin ningún cobro: se crea con aviso `month_without_charge` (pendiente de implementar en la tanda 1b, BILL-18). (4) Aviso en el arranque para `APP_ENV=development` con Toku, sin cambiar el comportamiento (pendiente de implementar en la tanda 3, BILL-20). (5) Orden: arreglos, luego importador de Toku (TK-17 a TK-22), luego pruebas de contrato en sandbox de VirtualPOS (BILL-11) |
| DEC-30 | Ventana de 31 días y reemplazo de un mes atrasado | Abierta | Usuario | La tanda 1 (commit 8a77809) acotó el reemplazo al mes original (meses pasados van a revisión manual con `reason` `replacement_outside_month`), lo que contradice la decisión del usuario del handoff: «si el mes ya pasó hace 31 días o menos y no tiene cobro pagado, procesando o rechazado se crea el reemplazo con fecha de mañana». Opciones: **A (recomendada)** respetar la regla del usuario atribuyendo cada cobro a su mes de origen por el `internal_code` `{sub}-{YYYYMM}-{monto}` y no por la fecha, en el plan y en la verificación; **B** dejar el comportamiento actual (meses atrasados siempre a revisión manual); **C** híbrido: respetar la regla, pero a revisión manual si mañana cae en el mes siguiente y ya existe el cobro regular de ese mes. Relacionada con DEC-07 y BILL-18 |

## 6. Deuda técnica

Resumen; la lista priorizada y comentada vive en [Technical Debt](../knowledge/08%20-%20Roadmap/Technical%20Debt.md), que no repite el backlog.

- **Crítica:** identidad centralizada (ADR-001) sin esquema físico completo, merge reversible ni gobierno de atributos personales (parcial: CORE-04 revisión sin merge automático).
- **Alta:** unicidad de `tch_clientes` por RUT en tensión con ADR-001; historial de cargos VirtualPOS incompleto para algunas suscripciones (hay cargos no recuperables, ver historial); Payku sin historial de transacciones certificable; taxonomía transversal de estados, montos, monedas y periodicidad pendiente (HOR-01).
- **Media:**
  - `crm_materialization.py` desactivado pero no borrado (`POST /etl/run` devuelve 410); borrarlo con su test cuando se confirme que no afecta.
  - TCH sigue sin trazabilidad en `source_records` (`source_record_id` en NULL).
  - «Crecimiento real mensual» y «Churn %» siguen con componentes antiguos; migrarlos a `ChannelChart` exige soporte de porcentajes.
  - `tests/test_health.py` espera `"development"` y depende del `.env`.
  - El filtro `chargeable` de Toku también cambia las series históricas.
  - El scheduler puede terminar con errores por canal sin ser un fallo total.
  - Documentación histórica puede contradecir la actual; conviven materialización legacy y consolidación.
- **Baja:** `compose.yaml` y el healthcheck de PostgreSQL con usuarios distintos; Context7 con configuraciones separadas para OpenCode y Claude.
- **Documentación del proveedor:** no tomarla como verdad; medir en sandbox (la de VirtualPOS se equivocó en seis puntos).
- Los puntos de «Horizonte» sin sprint están en el backlog (HOR-01 a HOR-04).

## 7. Historial y retrospectivas

### 7.1 Retrospectivas breves por sprint cerrado

- **Sprint 0 (cerrado el 2026-10-24).** Funcionó: modularizar `App.tsx` en dos fases (22 módulos y un `AppCore.tsx` para dejarlo en una línea) y revisar con `/review` (sin hallazgos). Corregido en el camino: la migración 0035 usaba `op.Column` en lugar de `sa.Column`. Rama `sprint-0/onboarding` lista para merge.
- **Sprint 1 (cerrado anticipadamente el 2026-10-25).** Funcionó: documentar antes de tocar; salieron cinco brechas de idempotencia con evidencia. Lección: `source_record_id` en NULL en todos los canales y `platform` variable en VirtualPOS eran riesgos reales (SYNC-GAP-03 y SYNC-GAP-01); el legado `crm_materialization.py` coexiste con la consolidación por canal. Decisión de negocio SYNC-GAP-02 sigue abierta (DEC-04).
- **Sprint 2 (cerrado en código).** Funcionó: contratos de datos explícitos para KPIs y notas de fuente visibles. Lección: TCH mezcla fuentes (recaudo mensual desde `tch_recaudacion_mensual`, MRR desde `TchSuscripcion`); se rotulan los valores distintos. Pendiente la verificación humana de KPI-01.
- **Sprint 3 (cerrado en código).** Funcionó: mapeos puros de datos a gráficos (`features/dashboard/channelCharts.ts`) y descarte explícito de gráficos que solapaban. Lección: los porcentajes no están soportados por `ChannelChart`; quedó deuda. Pendiente la verificación visual.
- **Sprint 4 (en curso).** Ver la retrospectiva parcial en 3.2 y la tabla de errores en `handoff.md` sección 9.

### 7.2 Notas de sesión relevantes

Migradas desde `docs/memory/CURRENT_SPRINT.md`. Plan visual original de los sprints: <https://claude.ai/artifact/RjnJYnghhrxA8AJb33kZjr>. Flujo de trabajo por sesión: indicar el sprint activo, tomar tareas de su sección, actualizar filas y notas al cerrar.

- **2026-10-24 (Sprint 0 y 1).** OPS-07 completada incluyendo el arreglo de la migración 0035. FE-02 en dos fases. DATA-01 a DATA-04 completos. Brechas principales: `source_record_id` NULL en todos los canales (SYNC-GAP-03), VirtualPOS con `platform` variable (SYNC-GAP-01), TCH con RUT como `external_id` en tensión con ADR-001 (GAP-TCH-01). BLQ-TK-01 sin respuesta de Toku.
- **2026-10-25 (cierre Sprint 1 y arranque Sprint 2).** SYNC-GAP-01 resuelto (`platform` acotado a `virtualpos1`/`virtualpos2`). SYNC-GAP-03 parcial: VirtualPOS, Toku y Payku vinculan `source_record_id`; TCH no. SYNC-GAP-05 documentado (las tablas centralizadas son una copia derivada). `crm_materialization.py` desactivado, no borrado; nota en ADR-001 sobre RUT como ID de proveedor en TCH. Sprint 2: KpiCard, ChannelChart y ChannelKpiStrip con vitest; `kpis.rejected_charges` en los cuatro canales; Payku calcula MRR desde la última transacción `success` (5.339.000, sin cambio); TCH agrega `kpis.recaudo_mensual`; Toku filtra `chargeable` en el churn.
- **2026-10-26 (Sprints 2 y 3).** TK-10 completada (6 tests con `offset>0`). SYNC-GAP-02 caracterizado (9 tests y script de auditoría). SYNC-GAP-04 mitigado (49 tests de formas de payload; log agregado `_log_null_relations`, solo conteos). KPI-01 a KPI-04 y FE-03. UI-20: cuatro bugs corregidos (estados activos, permisos `tch.suscripciones.view` y `tch.transacciones.view`, accesibilidad del menú móvil). UI-21: `GET /api/v1/sync-runs/health` (ok menos de 24 h, warn menos de 72 h, error desde 72 h, último run fallido o run en ejecución más de 72 h, unknown sin runs; VirtualPOS toma el peor de vp1/vp2; TCH desde `EtlRun`; caché de 5 minutos). CHART-01 a CHART-04 con `ChannelChart`; descartados el gráfico de actividad de VirtualPOS (solapaba con cargos) y «Transacciones vs Suscripciones».
- **2026-10-26/27 (Sprint 4).** REC-03 completada en código. Decisión `monto_vigente`: impacto medido en base local, MRR 63.991.386 a 64.087.821 (+0,15 %), 9 suscripciones cambian de monto y 15 del origen legacy `virtualpos` sin monto propio toman el del plan. WR-VP-05 implementada detrás de la bandera. Ambientes (ENV-01 parcial).
- **2026-10-27 (sandbox VirtualPOS).** V-5 ejecutada: `POST /v3/charge` aceptado en plan `MONTO_FIJO`, sin E-113 (contradice la documentación). Suite de contrato: 29 afirmaciones, 12 discrepancias; los errores llegan con HTTP 200 y cuerpo `NOK`; `internal_code` no es idempotente; los filtros de fecha de `/charges` se ignoran. Cargo manual en un mes con automático pendiente: conviven ambos (el riesgo es el doble cobro si no se cancela el automático).
- **2026-10-28 (Opción A y Toku).** Decisiones finales de la facturación gestionada (VirtualPOS sigue creando los cobros; horizonte de 12 meses solo al aplicar un cambio; chequeo diario de solo lectura; solo admin aprueba con autoaprobación auditada; doble aprobación apagada); catálogo de 175 escenarios vigentes. Implementados BILL-01 a BILL-08. Corregido BUG-VP-02. Guardas de escritura de Toku (TK-16) y mediciones del sandbox de Toku (ver 3.5). Esta reorganización documental unificó el plan en este archivo.
- **2026-10-28 (Toku: hallazgos y diseño del importador de reportes).** Medido con solo lecturas en el sandbox y diseñado el importador de reportes (TK-14 a TK-22; decisiones DEC-16 a DEC-25; consultas a soporte en DEC-26). `.gitignore` ahora ignora `*.xlsx` y `*.xls` (datos personales). Estado al cierre: backend 844 pruebas, frontend 179; rama `sprint-4/recuperador-vp` con 13 commits locales sin subir (último de código e6202a7; documentación 7c967c7 y este registro).
- **2026-10-28 (incidente: Alembic ejecutado sobre la base real `crm`).** Un agente de la tarea TK-17 corrió 3 `downgrade -1` y un `upgrade head` contra `crm` (base local con datos de producción; `.env` tiene `APP_ENV=development`, alias de producción) porque su script fijó `DATABASE_URL` en `os.environ` después de importar `settings`, y `alembic/env.py` usa `settings.database_url`. Medido: `crm` quedó en `20261028_0041` sin decisión del usuario y faltaban 2.169 filas de `core_charges` (VP1 744, VP2 1.425). Reparado: se ejecutó `run_vp_core_etl` sobre `crm` con autorización del usuario; los totales coinciden otra vez con `vp_charges` (+2.002 pagos y +15 suscripciones core recreadas). No se pudo confirmar: la causa del faltante (el downgrade de 0034 hace `DELETE FROM core_charges WHERE subscription_id IS NULL`, pero las filas reconstruidas quedaron vinculadas); además se perdió el contenido previo de `etl_runs.channels_failed` (estaba vacío). Último respaldo de `crm`: 2026-10-07 (pre-core). Lección: el orquestador no debe pedir un round-trip de migraciones cuya seguridad dependa de que un agente fije bien la base; las migraciones se prueban solo por pytest (`crm_test`), ningún agente corre Alembic, y la base se fija antes de importar `settings`. Respuesta: guarda de downgrade (OPS-10) y pendiente del usuario USR-11.
- **Lección de privacidad (2026-10-28).** Durante el diseño se imprimió por error, en el contexto de un agente, contenido de hojas de reportes con datos personales (no se guardó en disco ni se reprodujo). Al explorar reportes de Toku se lee solo el encabezado de la hoja y se confirma que la fila sea de encabezados antes de imprimir (regla 7 de 1.4).
- **2026-10-28 (revisión independiente de la Opción A y ciclo de pruebas en sandbox).** Revisión en 4 frentes con resultados en BILL-17 a BILL-22: (1) planificador y aplicación: reemplazo acotado al mes original, contradice la regla de 31 días del usuario (DEC-30); (2) API, política, scheduler y KPIs: arreglos de la tanda 2 (BILL-19); (3) frontend y Toku: aplicar y lecturas, orden de guardas en `delete_subscription`, aviso con `APP_ENV=development`, regex (BILL-20); (4) accesibilidad y observabilidad: `Dialog` inert, `role=tabpanel`, zona horaria del formulario, alertas del barrido (BILL-21, BILL-22). Estado de pruebas al cierre de la tanda 1: backend 897 y frontend 179. La rama `sprint-4/recuperador-vp` lleva 14 commits locales sin subir (verificado con `git rev-list --count '@{u}..HEAD'`). Aprobado el runbook de pruebas en sandbox (DEC-27, DEC-28) y registradas las decisiones del usuario sobre la revisión (DEC-29, DEC-30 abierta).

**Correcciones de inconsistencias detectadas el 2026-10-28** (prevalece el código y los commits):

- `handoff.md` sección 1 decía head `20261021_0036` y 542 tests; el head del código es `20261028_0038` y la suite de cierre son 844 de backend y 179 de frontend.
- `CURRENT_SPRINT.md` decía que `soporte` y `ejecutivo` no existen en el código: existen (rol `soporte` desde e9e775a, `ejecutivo` desde 44f379f); falta aplicar las migraciones y el seed en las bases (USR-01).
- El README de Toku decía que el receptor de webhooks no estaba implementado: WH-02 lo implementó (los eventos se guardan en `stg_toku_webhook_events`; el procesamiento es TK-12).
- `PROJECT_STATE.md` estaba desactualizado (fecha 2026-10-26).
- ENV-01 en varios documentos decía que `APP_ENV` carga `.env.sandbox` y `.env.qa`; el código usa un solo `.env` con variables `*_SANDBOX_*`.
- PK-05 listaba Q-06, Q-08, Q-11, Q-27 y Q-29 como dependencias; solo Q-08 y Q-11 la bloquean.

### 7.3 Archivo de notas históricas (2026-08 a 2026-10)

Registro cronológico migrado sin cambios de fondo desde la versión anterior de este archivo. Es historia, no estado: puede describir situaciones ya superadas (por ejemplo, «escritura remota pendiente de autorizar» o el flujo de BDlocales). El estado vigente está en las secciones 2 a 5.

#### Verificación local

- Fecha: 2026-08-30.
- Entorno: Python 3.14 en `.venv` y PostgreSQL 17 mediante Docker Compose en `localhost:5433`.
- Resultado: pruebas unitarias y lint correctos; migración `20260830_0004` aplicada.
- El lanzador `python scripts\sync_virtualpos.py` fue verificado localmente tras corregir la resolución de imports.
- VP-07 fue validada mediante sincronizaciones Sandbox read-only; las credenciales permanecen exclusivamente en `.env`.

#### Auditoría de secretos

- Fecha: 2026-08-30.
- Alcance: commit `c7e0f94`.
- Resultado: no hay archivos `.env` versionados ni patrones de claves AWS, tokens GitHub/Slack o claves privadas.
- `.env` y `.venv` permanecen ignorados por Git.
- `postman/` no forma parte del commit porque es un repositorio Git anidado sin historial.

#### Configuración de OpenCode

- Fecha: 2026-08-30.
- Se añadió la skill local `.opencode/skills/prompt-optimizer/SKILL.md` y la regla permanente correspondiente en `AGENTS.md`.
- Se configuró el servidor MCP remoto Context7 en `.opencode/opencode.json` para documentación actualizada de librerías y APIs externas.
- La configuración se aplica tras reiniciar OpenCode.

#### Estado local de integraciones

- Fecha: 2026-09-09.
- VirtualPOS: sincronización manual completada localmente.
- Toku: sincronización manual completada localmente con 20 registros procesados.
- Payku: autenticación read-only validada para clientes, planes y suscripciones tras incorporar la firma `Sign` requerida. La colección de transacciones excede el timeout local de 30 segundos; aumentar `PAYKU_TIMEOUT_SECONDS` antes de ejecutar la sincronización completa.

#### Plan de consolidacion 2026-09-13

- Se inventariaron las BDlocales: VirtualPOS tiene 260.179 registros, Payku 58.338 y Toku 36.404. Se eligio migrar estos datos existentes en vez de ejecutar una sincronizacion completa contra los proveedores.
- El plan operativo, los riesgos de identidad de las dos cuentas VirtualPOS y la validacion de datos sensibles estan en `docs/history/migrations/bdlocales-consolidation-closed.md`.
- Se aplico la migracion `20260913_0020`: las tablas de canal usan `vp_*`, `tk_*` y `p_*`; VirtualPOS conserva la plataforma en su identidad unica.
- La importacion usa la clave remota de cada BDlocal, procesa lotes saneados y no rematerializa TCH durante la carga de proveedores.
- Se cargaron las 354.921 filas historicas de VirtualPOS, Toku y Payku en `crm`; las sincronizaciones read-only para datos del dia estan en ejecucion y se validan por canal.
- Se corrigió el dashboard Payku: las activaciones usan `start`; las caídas consideran `cancel`, `delete` y `suspended` con `end`. Los payloads actuales no contienen fecha de reactivación ni historial fechado de estados.
- Se rematerializaron las 58.338 filas Payku: las 5.699 suscripciones centralizadas ya tienen inicio y 1.441 término. Como Payku no entrega monto recurrente en la suscripción, se usa la última transacción `success` asociada como monto operativo para KPIs y gráficos.
- Los KPIs de Payku cuentan solo suscripciones `active` y transacciones `success`, mostrando sus montos cuando el proveedor los entrega.
- La consolidación ahora persiste en `p_subscriptions.amount` el monto de la última transacción `success` asociada; 2.283 suscripciones y las 484 activas ya tienen monto materializado.

#### Avance 2026-08-30

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

#### Actualizacion documental 2026-09-09

- Se corrigio el estado de VP-14: el dashboard y las vistas CRM iniciales estan implementados.
- PK-01 queda bloqueada hasta completar la lectura de transacciones Payku; clientes, planes y suscripciones ya se validaron localmente.
- `README.md`, `docs/architecture/overview.md`, `frontend/README.md` y la referencia de Payku describen el staging de VirtualPOS, Toku y Payku, sus limites actuales y la operacion local.
- Se retiraron ejemplos de numeros de tarjeta y CVV de la documentacion versionada.

#### Actualizacion documental 2026-09-11

- Se incorporaron VP-18 a VP-27: fichas de cargo y pago VirtualPOS, filtros avanzados por campo, modales de edicion y cancelacion visual (escritura remota pendiente), mejoras de etiquetas y navegacion en fichas de los tres canales.
- Se agrego DOC-02: guia completa de la API VirtualPOS, conservada como investigación histórica en `docs/history/integrations/virtualpos-appscript-research.md`.
- `examples/dashboard_referencia.py` se incluye como template Streamlit de referencia para futuros dashboards analiticos; no es codigo productivo.

#### Actualización documental 2026-09-11 (hito escritura)

- Se añadió el Hito 2: Operaciones de escritura con 13 tareas de escritura por proveedor (WR-VP-01 a WR-VP-05, WR-TK-01 a WR-TK-06, WR-PK-01 a WR-PK-03) y 2 tareas de infraestructura transversal (WR-INF-01, WR-INF-02).
- Las plataformas soportan: VirtualPOS (PUT cliente, DELETE suscripción/cargo/pago), Toku (PUT y DELETE sobre cliente/invoice/suscripción), Payku (PUT y DELETE sobre cliente/suscripción).

#### Actualización documental 2026-09-11 (consolidación y tablas)

- Se añadieron migraciones `20260911_0007` a `20260911_0010`: soporte para payloads centralizados, relaciones de cliente, ejecuciones ETL y métodos de pago Toku.
- El ETL consolida las tres BDlocales en las entidades centralizadas; la sincronización completa mantiene operaciones contra proveedores exclusivamente en modo read-only.
- Las tablas aprovechan el ancho disponible, filtran por columnas operativas, ofrecen selector de estados y ordenan globalmente antes de paginar, incluidos campos anidados visibles de Toku.
- La escritura remota continúa pendiente de autorización e implementación de las tareas `WR-*`; los botones visuales no realizan llamadas de escritura.
- WR-VP-05 documenta el flujo especial de reasignación de monto/fecha en VirtualPOS: no existe PUT directo sobre suscripciones; el flujo equivalente es cancelar los cargos pendientes y recrearlos con los valores nuevos.
- Todos los botones de escritura del frontend ya existen visualmente (disabled); se habilitarán conforme se implementen los endpoints internos correspondientes.

#### Inicio de escritura controlada 2026-09-12

- Se reemplazó la política global de solo lectura por escritura controlada: las sincronizaciones y ETL siguen usando exclusivamente `GET`.
- Cada proveedor requiere una bandera local explícita (`VIRTUALPOS_WRITES_ENABLED`, `TOKU_WRITES_ENABLED` o `PAYKU_WRITES_ENABLED`) y permanece denegado por defecto.
- Se iniciaron `WR-INF-01` y `WR-INF-02`. Las operaciones remotas se limitarán a los flujos PUT/DELETE documentados; no se implementarán creaciones de pago, autorizaciones, reintentos, enlaces de pago, wallets ni payouts sin una nueva tarea aprobada.
- Se inició `WR-VP-01`: el backend cuenta con el registro durable `write_runs`, el cliente PUT de VirtualPOS y la ruta interna protegida. El modal de cliente ya utiliza la ruta interna; falta validar la operación contra Sandbox con la bandera local habilitada.

#### Actualización 2026-09-12 (identidad)

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

#### Actualización 2026-09-12 (TCH)

- Las tablas TCH ya contienen 28.982 clientes, 29.295 suscripciones y 255.914 transacciones cargadas desde los reportes Excel locales.
- Se añadió la migración `20260912_0015`: crea los permisos del canal TCH y los asigna al rol `admin` existente.
- El menú TCH ofrece resumen, suscripciones y transacciones; el resumen consulta correctamente la última carga ETL de TCH.
- El dashboard TCH muestra cargos mensuales aceptados/rechazados y altas mensuales de mandatos, con selector de año y alternancia entre cantidad y monto.
- La recarga histórica procesó 29 reportes desde enero de 2017 hasta agosto de 2026. Los cargos de `BK:CT` se desnormalizan y no se repiten entre ventanas mensuales; las hojas de cargos aportan el detalle de fecha y rechazo.
- La suscripción usa `Fecha Activación` como inicio y `Fecha Eliminado` o `Fecha Rechazo` como término. TCH abre su dashboard al pulsar el canal y sus tablas enlazan a fichas locales de suscripción y transacción.
- Se agregó Clientes TCH: `28.982` socios disponibles en tabla paginada por RUT/nombre y ficha local con suscripciones relacionadas. La migración `20260912_0018` asigna su permiso de lectura al rol administrador.
- La migración `20260912_0019` incorpora contacto de cliente y equivalente en pesos. El backfill local completó teléfono para 28.962 clientes, email para 25.372 y el equivalente para las 29.295 suscripciones TCH.

#### Actualización 2026-09-14

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

#### Actualización 2026-09-15 (retiro del flujo de BDlocales)

- Se detectó que `cancel_subscription`, `cancel_charge`, `retry_charge`, `update_client`, `create_client`, `create_plan`, `create_charge` y `create_subscription` en `write_virtualpos.py` intentaban reconciliar contra las tres BDlocales por canal (`VirtualPOS_Local`, `Toku_Local`, `Payku_Local`) usando columnas (`platform`, `remote_id`, `raw_payload`) que el esquema real ya no tiene desde la consolidación DB-01. Esto hacía fallar toda escritura de VirtualPOS con `reconciliation_required`, aunque la operación remota hubiera sido exitosa.
- Se retiró por completo el flujo de bases locales, ya innecesario tras DB-01/ETL-01: se eliminaron `app/services/bdlocales_sync.py`, `bdlocales_import.py`, `etl_consolidation.py`, `etl_orchestration.py` (sin importadores en la app viva) y los scripts `scripts/import_bdlocales.py`/`inspect_bdlocales.py`.
- Las 8 funciones de escritura de VirtualPOS ahora reconcilian solo `source_records` (staging) y la entidad centralizada correspondiente tras el `GET` de confirmación al proveedor, sin resincronizar el canal completo.
- Se quitaron `virtualpos_db_url`, `toku_db_url` y `payku_db_url` de `app/core/config.py` y las variables `VIRTUALPOS_DB_URL`/`TOKU_DB_URL`/`PAYKU_DB_URL` de `.env`/`.env.example`. `docs/history/migrations/bdlocales-consolidation-closed.md` queda marcado como completado y cerrado.
- `tests/test_virtualpos_writes.py` se actualizó para verificar la reconciliación contra `SourceRecord` en vez de mockear las funciones locales retiradas.

#### Operación local 2026-09-16

- PostgreSQL quedó saludable en `localhost:5433`, las migraciones se aplicaron hasta `head` y API FastAPI (`:8000/docs`) y frontend Vite (`:5173`) responden correctamente.

#### Actualización 2026-09-17 (dashboard general y TCH)

##### UX móvil y despliegue

- Se convirtió el sidebar en un drawer deslizable con botón burger (`☰`) en móvil: `position: fixed; transform: translateX(-100%)` → `.open { transform: translateX(0) }`. El overlay cierra el menú al tocar fuera.
- El frontend se compila (`npm run build`) y se sirve desde FastAPI en `/` vía `StaticFiles`, eliminando los 595 módulos cargados por Vite dev server que saturaban el túnel Cloudflare. El acceso remoto funciona correctamente a través de `trycloudflare.com`.
- Se corrigió el grid de KPI en móvil: `Staging.css` sobreescribía la regla de `App.css`; se agregó la regla `@media (max-width: 800px)` directamente en `Staging.css`.

##### Canal TCH — mejoras de KPIs y montos

- `monto_suscripcion` ahora usa `equivalente_pesos` (valor CLP) en lugar de `monto` (siempre nulo en los reportes Excel). Corregido en backend y frontend.
- Se añadieron tarjetas KPI al resumen TCH: **MRR** ($71.478.107), **ARPU** ($7.973), **Churn mensual promedio** (1.8%), **LTV estimado** ($442.944). El churn usa promedio de bajas/mes ÷ subs vigentes en lugar del ratio histórico acumulado (antes 211.3%, incorrecto).
- Las tarjetas principales del resumen TCH (Vigentes, Eliminadas, Total, Transacciones) ahora muestran sus montos CLP secundarios y responden al toggle Cantidad/Monto.
- Las fichas de métricas en todos los canales responden al toggle Cantidad/Monto: en modo Monto, el valor monetario pasa a ser el número principal.
- TCH-06 marcada Completada: se añadió la migración `20260916_0021` con la tabla `tch_recaudacion_mensual`; el resumen TCH usa los controles mensuales oficiales para montos y cantidades de transacciones.

##### Dashboard general — consolidación y nuevos gráficos

- Se eliminó el segundo encabezado duplicado ("DASHBOARD GENERAL / Indicadores consolidados"); los controles Cantidad/Monto/Año se integraron en el `hero-panel` del título principal.
- Las tarjetas "Suscripciones vigentes" y "Transacciones" del general ahora muestran su monto CLP: $142.693.178 en subs activas (todos los canales) y $6.553.083.993 en transacciones.
- Se agregó el endpoint `subscriptions.amount` al dashboard general: calcula la suma de `CSub.amount` por canal (VIGENTE/activa) más `TchSuscripcion.equivalente_pesos` para TCH.
- **Bajas mensuales por canal**: nuevo gráfico de panel ancho que muestra `CSub.canceled_at` (VirtualPOS, Toku, Payku) y `TchSuscripcion.fecha_eliminacion` (TCH) agrupadas por canal.
- **Deudas mensuales por canal**: gráfico que consolida `CCharge.charge_date` (online) con el total de intentos TCH (ACEPTADA + RECHAZADA), con filtro **Todas / Pagada / Rechazada**.
- **Transacciones por canal**: gráfico que consolida `CPayment` (online) con `TchRecaudacionMensual` agrupados por canal, con el mismo filtro de estado.
- Ambos gráficos de Deudas y Transacciones incorporan `charge_status` en cada entrada; el helper `applyChargeFilter` pre-agrega las entradas antes de pasarlas al componente de barras.

##### Escrituras completadas (WR-VP-04, WR-TK-02, WR-TK-05, WR-TK-06)

- **WR-VP-04** Completada: `DELETE /v3/payment/:uuid` implementado en `VirtualPOSClient`; servicio `cancel_payment` con registro `WriteRun` y ruta `DELETE /api/v1/writes/virtualpos/payments/{id}`.
- **WR-TK-02** Completada: `PUT /invoices/:id` implementado en `TokuClient`; servicio `update_invoice` actualiza el `SourceRecord` correspondiente.
- **WR-TK-05** Completada: `DELETE /invoices/:id` implementado; servicio `delete_invoice` marca el `SourceRecord` como deleted.
- **WR-TK-06** Completada: `DELETE /subscriptions/{id}` implementado; servicio `delete_subscription` marca la suscripción centralizada como deleted.

#### Actualización 2026-09-21 (operación consolidada)

- Clientes consolidados muestra RUT, nombre completo, plataformas de origen y suscripciones activas. Permite buscar por RUT, nombre, apellido, plataforma, correo o teléfono y pagina los resultados.
- Suscripciones consolidadas está habilitada en el submenú general con ID, cliente, RUT, plataforma, estado, fechas y monto; permite filtrar y paginar. Excluye `SUSCRIPCION_FALLIDA` de VirtualPOS, `RECHAZADA` de TCH y `register` de Payku.
- Las rutas estáticas de dashboard se registran antes de la ficha dinámica de staging para que `/dashboard/general/clients` y `/dashboard/general/subscriptions` no se interpreten como recursos de proveedor.
- Se documentaron las rutas de consulta consolidada, reportes operativos y reintento por lote de cargos VirtualPOS en `README.md`.

#### Mantenimiento 2026-09-21 (rutas directas de proveedores)

- Completada: se retiraron las rutas directas inactivas de Payku y Toku. La aplicación continúa operando mediante sincronización a staging y rutas internas protegidas; los clientes de integración, sincronizadores y escrituras no cambian.
- Verificado: migraciones en `head`, PostgreSQL saludable, frontend compilado y FastAPI respondió `200` en `/` y `/health`.

#### Mantenimiento 2026-09-21 (artefactos locales)

- Completada: los logs locales de API, frontend y sincronizaciones se centralizaron en `logs/`, carpeta ignorada por Git.

#### Mantenimiento 2026-09-21 (ejemplos)

- Completada: el template Streamlit no productivo se movio de la raiz a `examples/dashboard_referencia.py` y se documento su alcance.

#### Mantenimiento 2026-09-25 (servicios locales)

- En curso: se detuvieron los dos procesos `cloudflared` que exponian el frontend local.
- Bloqueada: detener MariaDB, PostgreSQL local y las dos instancias de SQL Server requiere una consola elevada. El contenedor PostgreSQL del CRM en `localhost:5433` permanece saludable y no se modifico.
- Bloqueada: el listener local en `127.0.0.1:8002` pertenece a un proceso no visible desde la sesion actual; requiere privilegios elevados para identificarlo y detenerlo.

#### Investigación 2026-09-25 (VirtualPOS: cargos y transacciones)

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
