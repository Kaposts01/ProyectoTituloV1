# ML-10: lotes sinteticos durables posteriores a Core

Fecha: 2026-11-25. **Preparacion implementada y probada; ejecucion operativa apagada.** Sin entrenamiento, carga de modelos, proveedores o datos reales. El socio validara sus datos completos. ADR-002 sigue Proposed.

## Alcance y frontera de integracion

Se añade una cola acotada en PostgreSQL para probar la secuencia **Core confirmado -> lote -> elementos -> resultados ML-09 e historial**, separada de `etl_runs`, `sync_runs` y `write_runs`. No se cambia el significado ni el estado de esas corridas.

La entrega prepara un contrato interno de confirmacion; **no instala hooks en los ETL operativos ni programa un job**. Los ETL actuales hacen commits propios y no tienen un recibo historico comun por cuenta que sirva como outbox de ML; el marcador de frescura actual tampoco lo sustituye. Su conexion real exige revisar esas fronteras transaccionales con los datos del socio. TCH se prueba bajo el mismo contrato que VP1, VP2, Toku y Payku, sin tratar su importacion Excel como confirmacion automatica de Core.

`ML_REJECTIONS_BATCHES_ENABLED=false` se añade a Settings y `.env.example`. No se modifica `.env`/`.env.local`. El worker `process_next()` respeta esa bandera; apagado retorna `disabled` sin conectar. Aun encendido exige `synthetic=true` y base descartable cuyo nombre termine en `_test`. No basta cambiar una variable para habilitar ML real. No hay endpoint o comando de entrenamiento/activacion.

Los helpers de preparacion/claim/procesamiento tienen ademas opt-in `enabled=true, synthetic=true` para el arnes de pruebas. No son permisos ni una API publica. Las funciones son internas, confian en callbacks locales revisados y no deben recibir parametros/resolvers desde un navegador. La bandera sintetica es una declaracion del llamador, no anonimiza una base restaurada con datos reales.

## Esquema nuevo y seguridad de la migracion

Revision **20261125_0085**, posterior a 0084, con modelos importados en Alembic:

| Tabla | Responsabilidad |
|---|---|
| `ml_core_receipts` | Fuente/cuenta, UUID de confirmacion, corte y hash del estado materializado declarado. Inmutable. |
| `ml_batches` | Manifiesto, confirmacion, versiones, limites, total y estado global. Identidad inmutable. |
| `ml_batch_items` | Referencias UUID/recurso/evidencia, hash de entrada, intentos, reserva temporal y resultado. Entrada inmutable. |
| `ml_batch_results` | Resultado ML-09, su hash e identidad logica unica, marcado `purpose=synthetic`. Inmutable. |
| `ml_batch_events` | Historial append-only por elemento/intento con token de reserva y codigo de error acotado. |

FK compuestas impiden cruzar cuentas entre confirmacion/lote/elemento/resultado. CHECK limita estados, intentos, proposito sintetico, recursos y coherencia de resultado/reserva. Triggers impiden modificar/borrar evidencia y cambiar identidades del manifiesto. El servicio controla transiciones bajo bloqueo; no se afirma que SQL directo de un administrador constituya una API autorizada o auditoria invulnerable. Permisos, retencion y exposicion siguen en ML-11/13.

**0085 se aplico solo a `crm_ml_registry_test`, recreada por la guarda de pruebas.** QA conserva su esquema y la base original no se toca. No ejecutar upgrade desde `.env` original ni habilitar esta funcion en QA con su esquema antiguo. Downgrade se rechaza si existen confirmaciones, lotes o resultados: requiere revision de archivo/retencion, no borrado automatico.

## Protocolo transaccional

1. En el arnes sintetico, el llamador realiza cambios Core y llama `stage_core_receipt()` dentro de **la misma transaccion**. Esa funcion inserta/comprueba el recibo y no hace commit. Si el trabajo falla, ambos se revierten. Un recibo es una afirmacion interna de materializacion satisfactoria; no demuestra por si solo cobertura, conciliacion ni calidad del ETL.
2. Solo despues del commit se llama `prepare_batch()` con una fabrica de **sesiones nuevas e independientes**, nunca la sesion que materializa. No ve recibos sin confirmar y los rechaza; no transforma un sync/staging exitoso en Core confirmado.
3. El manifiesto contiene hasta 1.000 snapshots de la misma cuenta y corte, referencias y hashes; no almacena glosas/contextos de entrada, nombres, contactos, claves ni payloads de proveedor. Rechaza duplicados por entrada o recurso/evidencia. Ordena de forma estable: invertir la entrada no crea otro lote.
4. La identidad incluye recibo/hash Core, corte, bundle de motor/reglas/taxonomia/politica y limites. Insertar nuevamente el mismo manifiesto, incluso desde dos procesos, devuelve el mismo lote sin duplicar elementos. Un lote vacio termina `completed` con total cero, sin inventar trabajo.
5. `claim_next()` reserva un elemento con token nuevo y reloj de PostgreSQL. Lote/elemento se bloquean en un orden fijo durante transacciones cortas. El calculo ocurre **fuera** del bloqueo. Se permiten varios elementos en ejecucion; dos procesos no obtienen la misma reserva vigente.
6. `process_claim()` comprueba propietario/vigencia antes del callback y al guardar. El resolver reconstruye el snapshot sintetico **exacto** desde su fixture privado; no se guarda ese texto en la cola. Si cambia su hash/recurso/cuenta/evidencia, el elemento falla con `snapshot_changed`: no usa estado viejo ni reconstruye historia con filas actuales. Una nueva realidad requiere un lote/corte adecuado.
7. Resultado inmutable, enlace del elemento, estado e historial se confirman juntos. Un fallo de almacenamiento revierte todo ese paso y deja la reserva recuperable. Otra ejecucion con igual identidad ML-09 reutiliza el resultado; nunca sobreescribe contenido distinto con el mismo ID.

Los metodos que reciben una fabrica poseen sus transacciones; `stage_core_receipt` es la excepcion explicitamente controlada por su llamador. No se confirma trabajo ajeno. La cola no crea transacciones distribuidas ni garantiza exactamente una ejecucion del callback: garantiza deduplicacion del resultado y confirmacion protegida por propietario. El resolver debe ser local, determinista y sin efectos externos.

## Reinicios, limites y errores

- Reserva: 60 segundos por defecto, configurable entre 1 y 300. No hay heartbeat en esta entrega. Un calculo que supere la reserva no puede guardar; el reemplazo puede recomputarlo.
- Hasta tres intentos por defecto, configurable entre uno y cinco. Un error esperado reprograma el elemento 30 segundos despues; no bloquea los demas. `snapshot_changed` falla sin reintentar la misma entrada.
- Una reserva vencida permite retomar con otro token; el token anterior queda invalidado. La expiracion se registra. Si ya agoto intentos, termina `failed` con `lease_expired` en el historial.
- Estados finales del lote: `completed` si todos terminaron bien, `completed_with_errors` si hay elementos fallidos. Que el worker retorne `idle` solo significa que ahora no hay elemento disponible: pueden quedar reintentos o reservas vigentes. No equivale a exito ni a 100 % completado.
- Errores esperados se convierten en `snapshot_changed`, `invalid_snapshot` o `calculation_failed`. No se almacena el mensaje de excepcion, traceback, glosa, SQL o respuesta de proveedor. Fallos inesperados/de infraestructura se propagan y dejan una reserva recuperable; si se abandona, queda registrada su expiracion. No se oculta un fallo de guardado como exito del lote o del ETL.

Los limites acotan lote, intentos y propietario. **No son un aislamiento de memoria/CPU ni un timeout del callback.** Antes de inferencia real habra que definir proceso confiable/limites, verificar latencia y dimensionar carga. No se añaden Celery, Redis, SSE u otro servicio para esta preparacion.

## Relacion con el motor y datos del socio

Se ejecuta ML-09 con reglas/abstencion y sin modelos: probabilidades reales nulas, ejecucion prohibida, ninguna llamada WR. `purpose=synthetic` de la fila distingue datos ficticios del resultado de reglas; el campo `simulation` de ML-09 sigue reservado a salidas de modelos simulados, que este worker no suministra.

El socio debera auditar relojes, enlaces, estados, cobertura, conciliacion completa/parcial/reversas y contexto revisado antes de construir snapshots reales. No convertir confirmacion Core o `updated_at` en cobertura o mandato vigente. Las restricciones de ML-09 permanecen: sin conciliacion verificada no se propone gestion operativa.

No se implementa aun enumeracion SQL/paginacion de todos los candidatos, almacenamiento historico inmutable de entradas reales, particionado de millones de registros, worker programado, cancelacion por interfaz o inferencia de artefactos. La entrada acotada viene del arnes; esto permite validar durabilidad sin extraer datos completos. Integracion con ETL, custodia de snapshots, permisos/activacion y adaptador real requieren su siguiente autorizacion y evidencia.

## Evidencia reproducible

**518 pruebas distintas aprobadas:** 385 puras y 133 en la suite PostgreSQL/ETL. ML-10 añade 35 pruebas (14 de contrato y 21 de servicio); las demas son regresiones ML-02 a ML-09, registro/anotaciones/lector Core y helpers/orquestacion ETL. Ruff completo y diff sin errores.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_batch_contract.py tests/test_ml_recommendation.py tests/test_ml_artifacts.py tests/test_ml_model_evaluation.py tests/test_ml_evaluation.py tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml10-pure-final -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Para las pruebas con DB, configurar antes las variables de proceso de pruebas para una base descartable *_test distinta de la operativa y con proveedores sinteticos. La guarda de conftest recrea public y migra toda la cadena. No se publica el wrapper local ni URLs/credenciales; nunca usar QA/original.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_batches.py tests/test_ml_artifact_registry.py tests/test_ml_annotations.py tests/test_ml_core_reader.py tests/test_sync_core_etl.py tests/test_core_etl_helpers.py --basetemp=.local/pytest-ml10-db -q
~~~

PostgreSQL prueba: commit/rollback del recibo junto con Core sintetico; rechazo antes del commit; cinco cuentas/canales; doble disparo; resultado compartido; concurrencia de reservas; reinicio con sesiones nuevas; rechazo del propietario antiguo; reintentos y expiracion terminal; entrada cambiada; rollback de resultado/estado/auditoria ante fallo; versiones incompatibles; invariantes/esquema/downgrade; y fallos ML sin alterar corridas operativas. Se comprueba tambien que la bandera apagada no conecta y que la ejecucion real/base operativa se rechazan sin usar esas bases.

No se entreno/cargo modelo, no se ejecutaron proveedores ni se midio calidad estadistica/carga con datos reales. No hay migraciones en QA/original, publicacion, skills incluidas o cambios en el ETL operativo. **ML-10 queda preparado para pruebas sinteticas; no se inicia ML-11 automaticamente.**
