# Ciclo de pruebas en sandbox y decisiones recomendadas

> Runbook operativo. Describe cómo se prueba cada despliegue en sandbox, quién decide qué y qué ve el usuario al final. Las reglas de seguridad no se inventan aquí: se heredan de [`handoff.md`](../../handoff.md) (sección 2), de [`CLAUDE.md`](../../CLAUDE.md) y de [`docs/tasks.md`](../tasks.md). Si este documento contradice a alguno de ellos, prevalece el otro y se corrige este.
> Creado el 2026-10-28. Los números `DEC-xx` y los IDs de tareas son los de `docs/tasks.md`.
>
> **Estado: APROBADO por el usuario el 2026-10-28**, con esta condición literal: **en sandbox sin problema; en producción siempre con el usuario y con más cuidado.** Registro en `docs/tasks.md` (DEC-27).
>
> **Regla de oro: producción siempre con el usuario.** Si hay duda sobre si un ambiente es sandbox o producción, se trata como producción. Ejemplos: Toku comparte host entre sandbox y producción, y `APP_ENV=development` equivale a producción (usa las llaves y la base reales). Ante la duda, no se ejecuta nada y se pregunta con opciones.

## 0. Decisiones del usuario al aprobar (2026-10-28)

Las seis decisiones que dejó abiertas el redactor quedan resueltas así:

1. **Escritura en sandbox:** autorización permanente solo para escenarios **catalogados** (sección 3), con cancelación de lo que la propia prueba creó, tope de operaciones y variables de proceso. Un escenario nuevo, no catalogado, se anota y se avisa al usuario **antes** de ejecutarlo.
2. **Pruebas de contrato CT-xx:** las 8 se aprueban en bloque una vez escritas; el orquestador registra un DEC-xx al aprobar la receta definitiva. Las que requieren tarjeta o esperar fechas de cobro se coordinan con el usuario.
3. **Excel sintético de TCH:** se carga invocando el servicio de importación directamente con `APP_ENV=sandbox` contra `crm_sandbox`, sin manejar credenciales.
4. **Migraciones y seeds:** en `crm_sandbox` PUEDEN aplicarlas el orquestador o el decisor avisando al usuario (en sandbox no hay problema). En `crm` (producción o local productiva) **NUNCA**: siempre el usuario. Actualiza USR-01 y USR-10 de `docs/tasks.md` (DEC-28).
5. **Límites:** máximo 2 vueltas probar-decidir por despliegue, 1 reintento de limpieza, topes de 30 cobros, 100 GET y 50 filas, aprobados tal cual.
6. **Ubicación:** el runbook queda en `docs/operations/`.

## 1. Propósito y ciclo

Acelerar el trabajo sin perder control: cada cambio desplegado se prueba en sandbox por un agente **probador**, un agente **decisor** convierte el informe en decisiones recomendadas según reglas explícitas, y el **orquestador** (la sesión principal) aplica lo permitido y resume al usuario.

```text
desplegar (orquestador)
  -> probar en sandbox (probador)      -> informe estructurado (sección 4.1)
  -> decidir (decisor, solo lectura)   -> decisiones DEC-xx propuestas (sección 4.2)
  -> aplicar lo permitido (orquestador) y verificar uno mismo
  -> resumen al usuario (sección 6)    -> registrar DEC-xx en docs/tasks.md §5 (sección 7)
```

Reparto de funciones:

| Rol | Hace | No hace |
|---|---|---|
| Orquestador | Despliega, lanza al probador y al decisor, verifica sus reportes (relee archivos, corre `ruff` y las suites él mismo), aplica lo decidido, commitea por ruta, registra DEC-xx y resume | Delegar la verificación; saltarse una decisión de la clase «siempre con el usuario» |
| Probador | Ejecuta solo escenarios del catálogo (sección 3) y devuelve el informe | Tocar el repo, el `.env`, producción; improvisar escenarios con escritura |
| Decisor | Lee el informe y los documentos; devuelve decisiones en el formato de la sección 4.2 | Editar archivos, ejecutar comandos con efectos, hablar con el usuario |

Los agentes viven en la carpeta personal del usuario (`~/.claude/agents/sandbox-tester.md` y `decision-maker.md`) y el procedimiento del orquestador en `~/.claude/skills/sandbox-orchestrator/SKILL.md`, porque `CLAUDE.md` indica que los agentes de Claude no se versionan en el proyecto. Este runbook es la parte versionada.

## 2. Clases de decisión

### 2.1 AUTOMÁTICA (el decisor decide, el orquestador aplica; se menciona en el resumen)

- Arreglos de código **con un test que reproduce el caso** (el test falla antes y pasa después).
- Actualización de documentación (sin cambiar decisiones de negocio ni ADR).
- Commits locales, siempre `git add` por ruta (nunca `git add docs` ni `.`).
- Pruebas de **solo lectura** en sandbox con llaves de sandbox.
- Elegir la opción marcada como **recomendada** cuando es reversible y está dentro del sprint en curso.

### 2.2 AVISAR (el decisor decide, el orquestador aplica e informa con resumen)

- Decisiones de diseño no triviales.
- Nuevas tareas de backlog.
- Escenarios de sandbox **con escritura ya catalogados** (sección 3, marcados «catalogado»).
- Migraciones y seeds en `crm_sandbox`, avisando al usuario (nunca en `crm`).

### 2.3 SIEMPRE CON EL USUARIO (el decisor solo propone opciones; nadie aplica sin respuesta)

- Escrituras reales a un proveedor en un escenario **nuevo, no catalogado** (se anota y se avisa antes de ejecutarlo).
- Cualquier cosa en **producción**.
- `git push`, abrir PR, merge.
- Aplicar migraciones o seeds a la base `crm` (producción o local productiva). En `crm_sandbox` las puede aplicar el orquestador avisando al usuario (clase Avisar, DEC-28).
- Borrar datos o archivos fuera del scratchpad (con la salvedad de la sección 3: borrar o cancelar **lo que la propia prueba creó y registró** es parte del escenario catalogado).
- Manejo de credenciales o de datos personales.
- Debilitar una guarda de seguridad.
- Asignar permisos a roles o crear usuarios.
- Decisiones de negocio (por ejemplo SYNC-GAP-02 / DEC-04, DEC-05, DEC-06, DEC-07).
- Gastar dinero o contactar a terceros, soportes o socios.

**Regla de desempate:** ante la duda entre dos clases, se aplica la más restrictiva. Una decisión que toque dos clases se trata como la más restrictiva. Si no se puede clasificar, es «siempre con el usuario».

## 3. Catálogo de escenarios de sandbox

Solo estos escenarios se pueden ejecutar sin preguntar (según su clase). Todo lo que no esté aquí es un escenario **nuevo** y va al usuario. Las variables se nombran, nunca se muestran sus valores; las de escritura se pasan **solo como variables de proceso** (handoff §2.3) y nunca van en `.env`. Los topes marcados «propuesto» quedaron aprobados tal cual el 2026-10-28 (sección 0).

Comunes a todo escenario de VirtualPOS: `APP_ENV=sandbox` y `CONTRACT_TESTS=1`. La suite aborta (código 2) si el ambiente no es sandbox, si el host no es exactamente el de sandbox o si falta `CONTRACT_TESTS=1` ([`guards.py`](../../tests_contract/virtualpos/guards.py)). Una sola sesión de pytest a la vez, y nunca en paralelo con la suite del backend.

### 3.1 VirtualPOS

| ID | Estado | Clase | Qué hace |
|---|---|---|---|
| VP-LEC | Existe (8 pruebas, lote 1: `test_read_claims.py`) | Automática | Solo lecturas. Comando de [`tests_contract/README.md`](../../tests_contract/README.md) con `-m "contract and not contract_write"` |
| VP-ESC | Existe (9 pruebas, lote 2: `test_write_claims.py`) | Avisar (catalogado) | Escrituras reversibles |
| CT-00, CT-CO-AUTO, CT-CO-DUP, CT-CO-NC3, CT-RZ-MC, CT-RZ-SWAP, CT-CANCEL, CT-STALE | **PENDIENTES DE ESCRIBIR** (BILL-11) | Siempre con el usuario hasta que exista la receta escrita; las 8 se aprueban en bloque y el orquestador registra un DEC-xx; luego Avisar (las que necesitan tarjeta o espera de fechas se coordinan con el usuario) | Recetas P0 de [`facturacion-gestionada-escenarios.md`](../designs/facturacion-gestionada-escenarios.md) |

**VP-LEC.** Crea: nada (genera el informe de drift en `reports/contract/virtualpos/`, ignorado por git). Limpia: nada que limpiar. Tope: una ráfaga de 20 GET (ya incluida en la prueba VP-C16), sin otras ráfagas. Variables: `APP_ENV`, `CONTRACT_TESTS`; `CONTRACT_VP_SUB_VARIABLE` para la prueba que la pide (si falta, esa prueba se omite). Aborto: cualquier mensaje de guarda, un `E-` de autenticación, o un HTTP 429 (no reintentar en bucle).

**VP-ESC.** Crea: cargos `pendiente` a hoy+20 días con `internal_code` `CT-...` sobre las suscripciones de prueba del sandbox (ids en [`handoff.md` §12](../../handoff.md), pasadas por variable). Limpia: el fixture `created_charges` reconsulta y cancela cada cargo registrado que siga `pendiente`; si algo falla la sesión termina en error. Nunca toca cargos pagados o procesando. Tope (aprobado): 30 cargos creados por sesión; el probador cuenta cargos creados y cancelados. Variables: `APP_ENV`, `CONTRACT_TESTS`, `CONTRACT_WRITES`, `VIRTUALPOS_SANDBOX_WRITES_ENABLED`, `CONTRACT_VP_SUB_FIXED`, `CONTRACT_VP_SUB_VARIABLE`. `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN` solo se arma si el escenario pasa por la ruta de la aplicación (WR-VP-05) y no por el cliente de la suite. Aborto: falla de limpieza (se reporta y se reintenta la cancelación una vez, luego se detiene y se avisa), cualquier host distinto del de sandbox, o más cargos creados que el tope.

**CT-xx (P0 de la Opción A).** Estado: sin escribir. Necesitan suscripciones nuevas creadas con el formulario público del plan y tarjetas de sandbox (acción humana o Playwright instalado fuera del proyecto, como en handoff §12), y varias exigen esperar fechas de cobro (DEC-09, DEC-12). Resumen de lo que crearía y limpiaría cada una:

| ID | Crea | Limpia | Tope (aprobado) | Nota |
|---|---|---|---|---|
| CT-00 | Suscripción `MONTO_FIJO` día `0` y un manual a mañana | Cancela el manual si sigue pendiente | 1 suscripción, 1 cargo | Condiciona a las demás: ¿el sandbox cobra en la fecha? |
| CT-CO-AUTO | Suscripción con 12 automáticos y manuales sobre ella | Cancela los manuales | 1 suscripción, 3 cargos | Ya existe una suscripción así (handoff §12) |
| CT-CO-DUP | Igual con primer automático en 1 a 2 días y un manual del mismo mes | Cancela el manual | 1 suscripción, 1 cargo | Mide el doble cobro |
| CT-CO-NC3 | `num_charges` 3, cancelar 3 automáticos y crear manuales | Cancela los manuales pendientes | 1 suscripción, 3 manuales | |
| CT-RZ-MC | `changecard` a tarjeta de rechazo y manual a mañana, observar 4 días | Cancela pendientes | 1 suscripción, 1 cargo | Necesita tarjetas de rechazo (DEC-09) |
| CT-RZ-SWAP | Como CT-RZ-MC más `changecard` y dos `retry_charge` | Cancela pendientes | 1 suscripción, 1 cargo, 2 reintentos | Necesita DEC-09 |
| CT-CANCEL | 2 manuales y luego `DELETE` de la suscripción | La propia prueba cancela la suscripción | 1 suscripción, 2 cargos | Es la única que cancela una suscripción entera |
| CT-STALE | Reemplazo con fecha de mañana sobre un automático pendiente vencido | Cancela el reemplazo | 1 cargo | Requiere encontrar o esperar el automático vencido |

Aborto común de las CT-xx: la suscripción de prueba no existe o no es del sandbox, no hay tarjeta disponible, o la limpieza falla. Estado de estas pruebas: no se ejecutan hasta que exista su código con `ChargeRegistry` y limpieza, se revise y se apruebe la receta definitiva en bloque (esa aprobación las pasa a «catalogado»). Las suscripciones y cargos que sobrevivan se anotan en `handoff.md` §12.

### 3.2 Toku (solo lecturas y verificación de guardas)

El «sandbox» de Toku usa la **misma URL base que producción**; solo cambia la llave, y las escrituras no están verificadas ([`write_guard.py`](../../app/integrations/toku/write_guard.py), tasks.md §3.5). Por eso no hay escenarios catalogados con escritura.

| ID | Estado | Clase | Qué hace |
|---|---|---|---|
| TK-LEC | Disponible (script en scratchpad, aún no hay `tests_contract/toku`: VAL-TK-01) | Automática | `GET` con llave de sandbox y `APP_ENV=sandbox`; imprime solo conteos, nombres de claves y códigos HTTP, nunca valores ni PII. Incluye `GET /reports/{entity}/columns` |
| TK-GUARD | Disponible | Automática | Verifica que las guardas bloqueen: `tests/test_toku_write_guard.py` (pruebas unitarias sin red) y, si se quiere medir, que un intento sin `TOKU_SANDBOX_ALLOW_WRITES_ARMED` se bloquee **antes** de salir a la red |
| TK-ESC | No catalogado | Siempre con el usuario | Cualquier `POST`/`PUT`/`DELETE`, incluido `POST /reports/{entity}` (genera reportes) |

TK-LEC y TK-GUARD no crean ni limpian nada. Tope (aprobado): 100 GET por corrida, sin ráfagas. Variables: `APP_ENV` (llaves `TOKU_SANDBOX_*` ya están en `.env`; no se leen). TK-GUARD con la suite normal usa `pytest` y se rige por la regla de una sola sesión. Para armar una escritura Toku (cuando el usuario la autorice) se necesitarían `TOKU_SANDBOX_WRITES_ENABLED`, `TOKU_SANDBOX_ALLOW_WRITES_ARMED=1`, opcionalmente `TOKU_SANDBOX_ALLOWED_IDS` y `TOKU_SANDBOX_MAX_WRITES` (por defecto 25); todas como variables de proceso. Aborto: HTTP 401/403, un host distinto de `api.trytoku.com`, cualquier respuesta con datos que no estén en la organización de sandbox conocida, o una guarda que **deje pasar** una escritura (eso es un hallazgo crítico: se detiene todo y va al usuario).

### 3.3 Payku (bloqueado)

| ID | Estado | Clase |
|---|---|---|
| PK-VAL | **BLOQUEADO**: variables `PAYKU_SANDBOX_*` vacías y sin sandbox (DEC-10, USR-04) | Cualquier llamada real: siempre con el usuario |

No se ejecuta nada contra Payku. Lo avanzable sin credenciales es código y diseño (PK-06 y la parte 1 de VAL-PK-01, `tests_contract/payku` que se omite sola sin credenciales), y eso lo hace el orquestador, no el probador. Al llegar las credenciales, el procedimiento está en [`VALIDATION-PLAN.md`](../integrations/payku/VALIDATION-PLAN.md) (Q-27, Q-06, Q-08, Q-11, Q-29); cada procedimiento de ese plan se catalogará aquí antes de ejecutarse, con su tope y su limpieza. El probador informa `BLOQUEADO`.

### 3.4 TCH (Excel sintético)

| ID | Estado | Clase |
|---|---|---|
| TCH-XLS | Pendiente de diseñar (VAL-TCH-01) | Avisar (catalogado una vez escrito el script) |

Crea: un `.xlsx` **sintético** en el scratchpad (nunca reportes reales; ver tasks.md §1.4 punto 7) con nombres y RUT de relleno obviamente falsos y un marcador reconocible, importado **solo** a `crm_sandbox`. Cadena a verificar: carga, ETL a `tch_*`, Core ETL, dashboard y recuperador. Limpia: borra del `crm_sandbox` únicamente las filas con el marcador del escenario y el archivo del scratchpad; cualquier otro borrado va al usuario. Tope (aprobado): un archivo de hasta 50 filas. Variables: `APP_ENV=sandbox`; el backend de sandbox se levanta con [`scripts/run_sandbox_backend.ps1`](../../scripts/run_sandbox_backend.ps1) (puerto 8001) y se apaga al terminar. Aborto: `SANDBOX_DATABASE_URL` que no apunte a `crm_sandbox`, o necesidad de una contraseña de administrador (el probador no maneja credenciales: la carga se hace invocando el servicio de importación directamente con `APP_ENV=sandbox` contra `crm_sandbox`, decisión aprobada).

## 4. Formatos

### 4.1 Informe del probador

El probador devuelve un informe en el mensaje final (no en archivos del repo). Cabecera: fecha, commit o versión desplegada (la que le dé el orquestador), ambiente, lista de variables de proceso armadas (**solo nombres**) y comandos ejecutados (sin valores). Luego una fila por escenario:

| Escenario | Esperado | Observado | Veredicto | Evidencia | Limpieza hecha | Recursos creados / cancelados |
|---|---|---|---|---|---|---|
| ID del catálogo | Lo que dice la documentación o el diseño | Lo medido | OK / DRIFT / FALLO / BLOQUEADO | Códigos HTTP, códigos `E-nnn`, conteos, rutas del informe de drift. **Sin PII ni llaves** | Sí / No (si No, qué quedó) | «creados N / cancelados N» por tipo |

Significado: **OK** coincide; **DRIFT** el proveedor se comporta distinto de lo documentado (no es un fallo del CRM; se registra como hallazgo, handoff §2.7); **FALLO** el código del CRM o la prueba falla; **BLOQUEADO** no se pudo ejecutar (guarda, credencial, dependencia externa). Cierre del informe: veredicto global, discrepancias por revisar (recordar que los comparadores también pueden estar mal, handoff §9 #15), y recursos que quedaron vivos con su identificador de prueba.

### 4.2 Decisión del decisor

Una por cada hallazgo que requiera decidir:

```text
ID propuesto: DEC-xx (siguiente libre en docs/tasks.md §5; el orquestador confirma el número)
Decisión: una frase.
Clase: AUTOMÁTICA | AVISAR | SIEMPRE CON EL USUARIO (con la regla de la sección 2 que la sitúa ahí)
Opciones consideradas: A (recomendada), B, C... cada una con su alternativa y su costo
Opción elegida y por qué: referencias a documentos, sección o claim (VP-Cxx, GB-xx, DEC-xx)
Reversibilidad: reversible / costosa / irreversible, y cómo se revierte
Se aplica: lo que el orquestador hace ya (rutas y comandos), vacío si es clase usuario
Queda para el usuario: lo que necesita responder, con las opciones y la recomendación
Evidencia en la que se apoya: filas del informe
```

El decisor devuelve texto; no edita archivos. Si el informe es insuficiente para decidir, lo dice y pide al orquestador una nueva prueba de solo lectura en vez de suponer.

## 5. Reglas de seguridad (heredadas)

1. Jamás imprimir, copiar ni resumir valores del `.env`, llaves, firmas, tokens ni datos de tarjeta (PAN, CVV). Leer solo **nombres** de variables. Sin PII (RUT, nombres, correos, teléfonos) en informes, logs ni documentos.
2. Solo sandbox. Un solo `.env`; con `APP_ENV=sandbox` rigen las variables `*_SANDBOX_*` y `SANDBOX_DATABASE_URL`. Nunca contra producción (puerto 8000, base `crm`).
3. Banderas de escritura (`VIRTUALPOS_SANDBOX_WRITES_ENABLED`, `VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN`, `CONTRACT_WRITES`, `TOKU_SANDBOX_ALLOW_WRITES_ARMED`, `TOKU_SANDBOX_ALLOWED_IDS`, `TOKU_SANDBOX_MAX_WRITES`) **solo como variables de proceso**, nunca en `.env`. Para limpiarlas, `$env:VAR = $null` (no `Remove-Item`, handoff §9 #18).
4. No dejar procesos ni túneles: al terminar, comprobar y apagar `uvicorn` de sandbox, Vite de sandbox y `cloudflared` (`Get-Process cloudflared`; los túneles son públicos y solo los protege el login).
5. Una sola sesión de pytest a la vez (todas recrean `crm_test`).
6. Verificar lo que reporta un agente antes de aceptarlo: releer archivos, correr `ruff` y las suites uno mismo (handoff §2.6).
7. Medir el proveedor, no inferirlo de su documentación (handoff §2.7); lo no medido se marca «a verificar».
8. `git add` por ruta; no hay push ni PR sin pedido del usuario; no se tocan los archivos ajenos sin versionar (handoff §11).
9. Scratchpad para todo temporal; ninguna copia de `.env` en el árbol.
10. No debilitar una guarda para que una prueba pase. Una guarda que falla en bloquear es un hallazgo crítico.
11. CLAUDE.md §9 exige autorización explícita para pruebas con escrituras externas reales. La aprobación del usuario del 2026-10-28 es esa autorización explícita, **limitada a sandbox** y a los escenarios catalogados (sección 3). Nada de esto se extiende a producción: allí siempre con el usuario y con más cuidado.
12. Regla de oro: producción siempre con el usuario. Ante la duda sobre el ambiente (Toku comparte host; `APP_ENV=development` equivale a producción), se trata como producción.

## 6. Qué ve el usuario después de cada ciclo

El orquestador entrega un resumen corto, en este orden:

1. **Qué se probó:** versión o commit, escenarios ejecutados y ambiente.
2. **Qué pasó:** conteo OK / DRIFT / FALLO / BLOQUEADO, hallazgos relevantes en una línea cada uno, y si quedó algo vivo en el sandbox.
3. **Decisiones tomadas por clase:** automáticas aplicadas (qué y dónde), avisadas (qué se decidió y por qué, con su DEC-xx).
4. **Lo que necesita del usuario:** todo resumen incluye **alternativas y recomendación**: cada pregunta con **opciones** (A, B, C), la alternativa de cada una y la **recomendación**. El usuario pidió siempre recibir opciones cuando se le pregunta: nunca una pregunta abierta ni de sí o no sin alternativas.
5. **Siguiente paso propuesto** y cómo detener el ciclo si lo desea.

## 7. Registro de decisiones

- Cada decisión se anota como una fila `DEC-xx` en [`docs/tasks.md`](../tasks.md) §5, con las columnas existentes (decisión, estado, a cargo de, impacto) e indicando **quién decidió** (decisor o usuario), la **fecha** y el **motivo**. Las ya resueltas por el usuario llevan «Resuelta (fecha)» como DEC-16 a DEC-25.
- El decisor **no edita archivos**: devuelve el texto y el orquestador lo registra. El orquestador comprueba que el número esté libre (el último vigente al aprobar este runbook es DEC-30) y que no se repita ningún ID con el comando de la sección 1.4 de tasks.md.
- Las decisiones automáticas menores (por ejemplo, un arreglo con test) se registran en el mensaje de commit y en la nota de sesión (§7.2 de tasks.md); solo las de clase Avisar o usuario reciben DEC-xx.
- Si una decisión cambia una decisión vigente (§1.5 de tasks.md o ADR), es de clase usuario.

## 8. Límites y cómo detener el ciclo

- Máximo **2 vueltas** probar-decidir por despliegue; a la tercera se para y se pregunta al usuario.
- Máximo **un reintento** de limpieza fallida; después se detiene y se informa qué quedó vivo.
- No se encadenan ciclos nuevos sin que el usuario haya visto el resumen del anterior, salvo que lo haya autorizado expresamente.
- Un agente no lanza otros agentes ni amplía el catálogo.
- **Detener:** el usuario dice «para» (o equivalente); el orquestador deja de lanzar agentes, pide al probador (o hace él mismo) la limpieza de los recursos registrados, apaga procesos y túneles, borra las variables de proceso armadas y entrega un resumen del estado. Parada automática: una guarda que falla en bloquear, una limpieza que falla dos veces, un host inesperado, o cualquier señal de que una llave de sandbox ve datos de producción.
- Limitación técnica: los permisos de herramientas de un agente no impiden por sí solos todo comando; la contención descansa en las guardas del código (`guards.py`, `write_guard.py`), en las reglas de este runbook y en la verificación del orquestador.

## 9. Ciclo ejecutado

Plantilla vacía. El orquestador anota aquí cada ciclo al terminarlo. Los resúmenes al usuario siempre incluyen alternativas y recomendación (sección 6). Sin PII ni llaves.

| Fecha | Versión o commit | Qué se probó | Resultado (OK / DRIFT / FALLO / BLOQUEADO) | Decisiones (DEC-xx o automáticas) | Quedó vivo en sandbox |
|---|---|---|---|---|---|
| | | | | | |
