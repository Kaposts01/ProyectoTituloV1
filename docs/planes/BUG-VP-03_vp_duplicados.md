# Plan BUG-VP-03 · Sincronización VirtualPOS: guardar las suscripciones con mismo RUT y plan en vez de omitirlas

Planner: `Esp_Planner`, 2026-11-17. Rama propuesta: `fix/vp-duplicados-activos` (base `master` en `54814f4`). Encargo del Orquestador. Decisiones ya aprobadas en la Bandeja: **d236 = a** (quitar el índice en `crm_sandbox` y `crm`, con vuelta atrás), **d237 = a** (el alta avisa y deja crear si se confirma), **d238 = a** (el vínculo pago→suscripción por código es CORE-05, fuera de este plan).

## 1. Contexto

Palabras del usuario (17/11): «dejemoslos pasar ya que un mismo rut puede tener varias subscripciones con diferentes id» y «Con respecto al alcance en productivo tambien tengo algunos casos de personas con mas de una subscripcion. Deberiamos cambiar esta regla quizas ya que el caso de usario es posible».

Hoy la sincronización de VirtualPOS omite toda suscripción ACTIVA o SUSCRIBIENDO cuando la persona ya tiene otra en el mismo plan y plataforma. En el sandbox omite 5 de 18 en cada corrida (entre ellas, con alta probabilidad, la `7259a36b15` de la captura del usuario), así que no se pueden gestionar desde el CRM. En producción no hay omitidas en toda la historia ni personas con dos activas en el mismo plan: allí el cambio es preventivo. El pedido está en `00-Sistema-Agentico\pedidos\2026-11-17_crm_vp_duplicados_activos\PEDIDO.md`; el diagnóstico, en el campo `diagnostico` de BUG-VP-03 en `crm_tareas`.

## 2. Estado actual (comprobado en el código)

**La regla en la base**
- Índice único parcial `uq_vp_sub_active_plan_client` sobre `vp_subscriptions (platform, plan_external_id, client_social_id) WHERE status IN ('ACTIVA', 'SUSCRIBIENDO')`, creado por `alembic/versions/20261021_0036_vp_subscriptions_partial_unique_active.py` (commit `8c2ba4e`). Su docstring lo justifica como guarda de la carrera en `create_subscription`.
- El modelo lo declara en `app/models/vp.py:79-90` (`Index(..., unique=True, postgresql_where=...)` dentro de `__table_args__`). La base de pruebas `crm_test` se construye con `alembic upgrade head` (`tests/conftest.py:4`), así que el modelo y la migración deben cambiar juntos.
- Cabeza actual de Alembic: `20261116_0081` (`alembic/versions/20261116_0081_core_charges_latest_rejection_payment_index.py`). `alembic/env.py:121-125` tiene la guarda anti-`downgrade` (OPS-10, `app/db/migration_guard.py`).

**La omisión en la sincronización** (commit `cb8a6d5`)
- `upsert_channel` (`app/services/channel_store.py:117-205`): con `skipped` distinto de `None`, un lote que viole una restricción única distinta de la identidad se reintenta fila a fila en SAVEPOINT; el desempate conserva la más reciente por `suscription_date` y, en empate, el mayor `external_id` (`:175-199`). Las omitidas se marcan como vistas con `_touch_skipped_seen` (`:218-227`) para que `detect_removals` no las dé de baja.
- `store_vp_resources` (`:557-597`) activa ese camino solo para `subscription`, registra el aviso en el log (`:589-592`) y devuelve los `external_id` omitidos.
- `virtualpos_sync.py:312-313`: la corrida termina `completed` con `error_message = "N suscripciones omitidas por duplicado activo"`.
- Prueba `tests/test_channel_store_vp_duplicates.py` (5 pruebas) **afirma la omisión**: hay que reescribirla, no borrarla.

**El alta desde el CRM**
- `create_subscription` (`app/services/write_virtualpos.py:1224`): antiduplicado por SELECT (`:1239-1255`) que lanza `DuplicateSubscriptionError`; la ruta `POST /api/v1/writes/virtualpos/subscriptions` (`app/api/v1/routes/writes.py:298-325`) lo convierte en 409 `operation_conflict`. El esquema de entrada es `VirtualPOSSubscriptionCreate` (`writes.py:282-296`).
- El `except IntegrityError` de `write_virtualpos.py:1322-1333` busca el nombre del índice en el error, pero el `try` que lo precede (`:1298-1321`) solo escribe `SourceRecord` y `Subscription` (tabla canónica), nunca `vp_subscriptions`. **Ese ramal nunca se ejecutó**: el índice jamás protegió el alta en la base; la fila `vp_*` llega después, por la sincronización. En la práctica el índice solo actuó sobre la sincronización, y ahí producía las omisiones.
- El diccionario `data` se envía tal cual al proveedor (`provider.create_subscription(data)`, `:1273`): cualquier campo nuevo de control debe quitarse antes.

**Interfaz**
- `frontend/src/features/virtualpos/useVirtualPosWrites.ts:295-353` (`createVirtualPOSSubscription`) hace el POST y muestra el error con `friendlyError`; el formulario vive en `frontend/src/features/virtualpos/VirtualPosWriteDialogs.tsx`. No hay en `features/virtualpos` un patrón de confirmación reutilizable (0 coincidencias de `window.confirm`, `ConfirmDialog`, `useConfirm`).

**Contrato y documentación que nombran el índice:** `docs/data/virtualpos.md:38`, `docs/data/sync-idempotency.md:25` y `:163`, `docs/data/camino-lectura-sync.md:124`, `docs/memory/PROJECT_STATE.md:146` (RISK-VP-02), `docs/tasks.md:418` (RISK-VP-02). El golden de OpenAPI (`tests/test_api_contract_openapi.py`, `tests/golden/openapi_operations.json`) cambia si cambia el cuerpo del alta.

**Contradicciones que señalo sin resolver**
1. `docs/operations/sandbox-testing-and-decisions.md:17` y `:65` dicen que en `crm_sandbox` el orquestador puede aplicar migraciones avisando; la regla 13 del mismo documento (`:190`) dice que los agentes nunca ejecutan la CLI de Alembic contra ninguna base. El encargo fija la versión estricta: en las dos bases las aplica el usuario. Este plan sigue el encargo.
2. `docs/tasks.md` se declara única fuente de verdad del plan (`CLAUDE.md` §2), pero BUG-VP-03 existe solo en `crm_tareas` de la Bandeja; la fila de `tasks.md` queda para el paso Docs.
3. RISK-VP-02 (`tasks.md:418`, `PROJECT_STATE.md:146`) afirma que el índice «captura la condición de carrera» del alta; por lo anterior, no era así.

## 3. Propuesta

Quitar la regla completa y de una vez: la migración borra el índice, el modelo deja de declararlo, la sincronización vuelve a guardar todo lo que entrega VirtualPOS identificado por `(platform, external_id)`, y el alta desde el CRM cambia de bloqueo a aviso con confirmación explícita. El código y el esquema se despliegan en una ventana con orden fijo (sección 6), porque el código nuevo con el índice todavía puesto haría fallar la corrida.

Decisiones de diseño que tomo:
- **Confirmación por bandera en el cuerpo del alta** (`confirm_duplicate: bool = False` en `VirtualPOSSubscriptionCreate`). Sin bandera, si hay una activa en ese plan, el alta responde 409 con `code = "duplicate_active_subscription"` y el detalle trae `existing_external_id` y `existing_status`. Con bandera, se crea y el `WriteRun` guarda `duplicate_confirmed: true` en `request_payload` para auditoría. La bandera se quita de `data` antes de llamar al proveedor.
- **Se elimina el camino `skipped` entero** (`upsert_channel`, `store_vp_resources`, `virtualpos_sync`, `_touch_skipped_seen`): sin el índice no existe ninguna restricción que lo ejercite para suscripciones, y el desempate por `suscription_date` es específico de VirtualPOS dentro de una función genérica. `upsert_channel` vuelve a propagar `IntegrityError`, como antes de `cb8a6d5`.
- **La migración lleva `downgrade`** que recrea el índice (d236). Si en ese momento ya hay dos activas en el mismo plan, el `CREATE UNIQUE INDEX` falla: el docstring lo dice y el paso de vuelta atrás comprueba antes con un SELECT de conteo.
- **El `except IntegrityError` muerto se reduce** al ramal que sí puede ocurrir (`reconciliation_required`).

Alternativas descartadas, una línea cada una:
- Mantener el fallback `skipped` «por si acaso»: código sin ningún camino que lo ejercite ni prueba que lo cubra.
- Confirmación por cabecera HTTP o por un segundo endpoint: más superficie en el contrato y en el golden que una bandera en el cuerpo.
- `window.confirm` en el navegador: bloquea la pestaña y no hay patrón previo en el proyecto; se usa un estado de confirmación dentro del mismo diálogo.
- Relajar el índice (por ejemplo, incluir `external_id`): equivale a quitarlo y deja un objeto sin propósito.
- Quitar solo en sandbox (d236 b): descartada por el usuario.

## 4. Componentes afectados y fronteras

| Capa | Archivos | Qué cruza |
|---|---|---|
| Esquema | `alembic/versions/20261117_0082_drop_vp_sub_active_plan_client_index.py` (nuevo), `app/models/vp.py` | migración con vuelta atrás; `down_revision = "20261116_0081"` |
| Ingesta | `app/services/channel_store.py`, `app/services/virtualpos_sync.py` | quitar la omisión y el mensaje de la corrida |
| Escritura | `app/services/write_virtualpos.py`, `app/api/v1/routes/writes.py` | bandera de confirmación, nuevo `code` 409, limpieza del ramal muerto |
| Interfaz | `frontend/src/features/virtualpos/useVirtualPosWrites.ts`, `VirtualPosWriteDialogs.tsx` | estado de confirmación y reenvío con la bandera |
| Pruebas | `tests/test_channel_store_vp_duplicates.py` (reescrita), `tests/test_virtualpos_fixed_plan_writes.py` o archivo nuevo, `tests/golden/openapi_operations.json` | `crm_test` |
| Docs (paso Docs) | los seis archivos de la sección 2 más `docs/tasks.md` (fila BUG-VP-03 y corrección de RISK-VP-02) | |

Fuera de este plan: `app/services/core_vp_etl.py` (`_build_rut_to_sub_index`, `_materialize_payments`): es CORE-05 por d238. `detect_removals` no cambia: las filas que antes se omitían ahora se guardan y se marcan vistas por el camino normal.

## 5. Tareas

Todas sobre `fix/vp-duplicados-activos`, cada una en su commit. Pruebas acotadas por archivo contra `crm_test`; ningún agente ejecuta Alembic contra `crm` ni `crm_sandbox`.

**BUG-VP-03a · Migración que quita el índice y el modelo sin él (backend)** — ~1 h
- Archivos: `alembic/versions/20261117_0082_drop_vp_sub_active_plan_client_index.py` (nuevo), `app/models/vp.py`, `tests/test_migration_0082_vp_index.py` (nuevo).
- Hecho cuando: `upgrade()` ejecuta `DROP INDEX IF EXISTS uq_vp_sub_active_plan_client`; `downgrade()` recrea el índice con la misma definición de 0036 y su docstring advierte que falla si ya existen dos activas en el mismo plan; `VpSubscription.__table_args__` ya no declara el `Index`; `alembic upgrade head` en `crm_test` deja `pg_indexes` sin ese nombre.
- Pruebas: una consulta a `pg_indexes` tras el `upgrade head` de la sesión de pruebas no encuentra el índice; insertar dos `VpSubscription` ACTIVA con mismo `platform`, `plan_external_id` y `client_social_id` y distinto `external_id` no lanza error. `ruff check alembic app`.

**BUG-VP-03b · Sincronización sin omisión (backend)** — ~1,5 h — depende de 03a (las pruebas necesitan `crm_test` sin el índice)
- Archivos: `app/services/channel_store.py`, `app/services/virtualpos_sync.py`, `tests/test_channel_store_vp_duplicates.py` (reescrita como `tests/test_channel_store_vp_same_plan.py`).
- Hecho cuando: `upsert_channel` no tiene parámetro `skipped` ni el reintento por SAVEPOINT; `_touch_skipped_seen` desaparece; `store_vp_resources` no tiene `skipped_subscriptions` ni el aviso del log; `virtualpos_sync` no escribe `error_message` por omitidas (la corrida `completed` queda con `error_message` vacío); no queda ninguna referencia a «omitidas por duplicado activo» en `app/`.
- Pruebas (4): el lote de la prueba actual (dos activas mismo plan, una de otro plan, una cancelada) guarda las 4 filas; una activa existente más una activa nueva en el mismo plan quedan ambas; `sync_virtualpos` con el `_FakeVp` de la prueba actual termina `completed` con `error_message` en `None` y guarda las 3; el log no contiene el RUT de prueba.

**BUG-VP-03c · Alta con aviso y confirmación, y limpieza del ramal muerto (backend)** — ~1,5 h — independiente de 03a
- Archivos: `app/api/v1/routes/writes.py`, `app/services/write_virtualpos.py`, `tests/test_virtualpos_create_duplicate_confirm.py` (nuevo), `tests/golden/openapi_operations.json`.
- Hecho cuando: `VirtualPOSSubscriptionCreate` acepta `confirm_duplicate: bool = False`; `create_subscription` quita la bandera de `data` antes del proveedor; con una activa en el mismo plan y sin bandera lanza `DuplicateSubscriptionError` y la ruta responde 409 con `detail = {code: "duplicate_active_subscription", message, existing_external_id, existing_status}`; con bandera continúa y el `WriteRun.request_payload` lleva `duplicate_confirmed: true`; el `except IntegrityError` ya no menciona el índice y conserva solo `reconciliation_required`; el golden de OpenAPI se regenera con el procedimiento de `tests/test_api_contract_openapi.py`.
- Pruebas (4): 409 con el `code` nuevo y el `external_id` existente; con `confirm_duplicate` y proveedor simulado, 200 y `WriteRun` `completed` con la marca; el cuerpo enviado al proveedor simulado no contiene `confirm_duplicate`; el contrato OpenAPI pasa.

**BUG-VP-03d · Confirmación en el diálogo de alta (frontend)** — ~1,5 h — construible en paralelo con 03c sobre el contrato de arriba
- Archivos: `frontend/src/features/virtualpos/useVirtualPosWrites.ts`, `frontend/src/features/virtualpos/VirtualPosWriteDialogs.tsx`, prueba `*.test.tsx` junto al diálogo si el patrón existente lo permite.
- Hecho cuando: ante un 409 con `code = "duplicate_active_subscription"`, el diálogo no cierra ni muestra el error genérico: muestra «Esta persona ya tiene una suscripción activa en este plan (código …). ¿Crear otra?» con botones «Crear de todas formas» y «Cancelar»; «Crear de todas formas» reenvía el mismo cuerpo con `confirm_duplicate: true`; cualquier otro 409 sigue mostrando el mensaje como hoy; el estado de confirmación se limpia al cerrar el diálogo.
- Pruebas: prueba de componente con `fetch` simulado (409 con el `code` nuevo → aparece la pregunta; clic → segundo POST con la bandera); `npm run build` y `npm run lint` del frontend en verde.

**BUG-VP-03e · Ventana de migración y despliegue (no es tarea de especialista: la ejecuta el usuario con GitOps al lado)** — ~30 min por base
- Se detalla en la sección 6. Entra a la cadena después de QA y Docs, cuando GitOps tenga el PR aprobado.

Orden: 03a → 03b; 03c y 03d en paralelo; QA; Docs; GitOps (push y PR con permiso del usuario); después la ventana 03e, primero `crm_sandbox` y luego `crm`.

## 6. Riesgos

- **Orden entre código y esquema (el riesgo principal).** Con el código de 03b desplegado y el índice todavía en la base, la primera corrida de sincronización falla con `IntegrityError` (vuelve al comportamiento de antes de `cb8a6d5`). Además, `docs/operations/estado-produccion.md:62` recuerda que un `git pull` en el checkout principal recarga el 8000 en caliente. Por eso el merge a `master` y el `git pull` de producción van **dentro** de la ventana, después de la migración. Secuencia por base: (1) respaldo con `scripts\maintenance\backup_db.ps1 -Database <crm_sandbox|crm>`; (2) el usuario aplica `alembic upgrade head` (la 0082 es un `DROP INDEX` sobre una tabla chica: bloqueo breve); (3) `git pull` del código; (4) una corrida de sincronización VirtualPOS en esa base y lectura de `sync_runs` (estado `completed`, `error_message` vacío); (5) en sandbox, comprobar en Cartera → Suscripciones que aparece `7259a36b15`. Primero `crm_sandbox` (8001/5174), después `crm` con confirmación del usuario en el chat del CRM. Ningún agente ejecuta Alembic contra esas bases.
- **Vuelta atrás.** El `downgrade` recrea un índice único: falla si ya hay dos activas en el mismo plan (en producción hoy no las hay; en sandbox sí, 5). Además `alembic/env.py` bloquea `downgrade` sobre bases no seguras (OPS-10): la vuelta atrás en `crm` requiere la autorización de esa guarda y el respaldo del paso 1.
- **Pagos del Core sin vincular.** `core_vp_etl.py` une pago y suscripción por RUT; con más suscripciones por persona habrá algunos casos más sin vínculo. Es CORE-05 (d238 a), no se toca aquí; QA lo anota, no lo corrige.
- **Datos personales.** Las pruebas usan RUT de relleno; el aviso del alta no debe imprimir el RUT en logs ni en `error_message` (hoy el mensaje de `DuplicateSubscriptionError` incluye `social_id`: 03c lo deja fuera del mensaje y conserva solo `external_id` y estado).
- **Golden de OpenAPI.** Un campo nuevo en el cuerpo del alta cambia `openapi_operations.json`; se regenera en 03c, no se parchea a mano.
- **Sandbox sin escrituras.** Con `VIRTUALPOS_SANDBOX_WRITES_ENABLED=false`, el alta en sandbox llega al antiduplicado antes de la guarda de escrituras (`write_virtualpos.py:1239` antes de `:1257`), así que el 409 y la pregunta se pueden probar en 5174; la creación confirmada solo se prueba con el proveedor simulado en pytest.
- **Producción.** `.venv` y los puertos 8000, 5173 y 5433 no se tocan fuera de la ventana. Suite completa solo con turno del Orquestador.

## 7. Decisiones del usuario

Ninguna nueva: d236, d237 y d238 cubren el alcance. Lo que sigue necesitando al usuario ya está regulado: aplicar la migración en `crm_sandbox` y luego en `crm` (d236 aprobada + confirmación en el chat del CRM en cada ventana), y el push y merge de la rama (GitOps, con permiso en el chat). Si QA encontrara en sandbox que alguna de las 5 suscripciones omitidas no es un duplicado sino otro problema, se abre una ficha nueva; no se adelanta aquí.

## 8. Verificación (para QA)

1. Pruebas acotadas, en este orden:
   ```
   python -m pytest -q tests/test_migration_0082_vp_index.py tests/test_channel_store_vp_same_plan.py
   python -m pytest -q tests/test_virtualpos_create_duplicate_confirm.py tests/test_api_contract_openapi.py tests/test_virtualpos_fixed_plan_writes.py
   ruff check app tests alembic scripts
   ```
   y en `frontend/`: `npm run lint`, `npm test -- VirtualPosWriteDialogs`, `npm run build`.
2. Revisión estática: `grep -rn "uq_vp_sub_active_plan_client\|omitidas por duplicado" app alembic` solo debe encontrar la migración 0036 y la 0082.
3. En sandbox (5174 contra 8001, sin tocar producción), antes de la ventana: abrir el alta de suscripción con un plan y RUT de prueba que ya tengan una activa; debe aparecer la pregunta con el código existente y, al confirmar, el 403 de escrituras deshabilitadas (esperado en sandbox).
4. Después de la ventana en `crm_sandbox`: `sync_runs` de `virtualpos1` con `completed` y `error_message` vacío; `vp_subscriptions` con las 18 filas (hoy 13); `7259a36b15` visible en Cartera → Suscripciones.
5. Después de la ventana en `crm`: la siguiente corrida `completed` sin `error_message`; el conteo de `vp_subscriptions` no cambia (producción no tenía omitidas). Cualquier diferencia se reporta antes de dar por cerrada la tarea.
6. Documentación (paso Docs, misma rama): `docs/data/virtualpos.md`, `sync-idempotency.md`, `camino-lectura-sync.md`, `PROJECT_STATE.md` (RISK-VP-02 con la aclaración de que el índice no protegía el alta), `docs/tasks.md` (fila BUG-VP-03 y RISK-VP-02), y la nota de la contradicción del runbook de sandbox sobre quién aplica migraciones.
