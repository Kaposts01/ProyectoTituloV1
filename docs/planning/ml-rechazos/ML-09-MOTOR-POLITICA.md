# ML-09: motor y politica de recomendacion en sombra

Fecha: 2026-11-25. **Implementado y probado con datos sinteticos; no conectado al CRM.** Sin entrenamiento, carga de modelos, predicciones reales o activacion. ADR-002 sigue Proposed. El socio valida vocabularios, conciliacion y cobertura con sus datos completos; tener mas registros no verifica esos contratos automaticamente.

## Componentes y uso

- `app/ml/recommendation.py`: contratos inmutables `CoreSnapshot`, `Simulation`, `Recommendation`, `snapshot_hash()` y funcion pura `recommend()`.
- `app/services/ml_core_reader.py`: `read_core_evidence()` lee una entidad por UUID interno, cuenta y tipo desde Core; `ReviewedStateMapping` y `map_core_evidence()` preparan el snapshot sin inventar estados.
- Pruebas puras y PostgreSQL independientes. No hay rutas HTTP, cambios frontend, flags habilitados, scheduler, consumidor del registro ML-08 ni escrituras en proveedores.

`recommend(snapshot)` funciona sin sklearn, skops, configuracion de app o conexion DB. Usa ML-02 sobre contexto ML-03 previamente saneado/revisado; no copia glosas, codigos crudos, UUID del recurso o datos personales a la salida. No lee Raw/STG ni intenta enriquecer datos desde el proveedor.

El snapshot contiene cuenta concreta (VP1 y VP2 separados), recurso charge/payment/transaction, UUID interno del recurso/evidencia, fecha del rechazo, corte, cobertura verificada hasta, estado interpretado, hashes del mapeo y datos, contexto opcional y restricciones comprobadas. No asume identidad transversal por RUT. Un rechazo asociado solo a pago es admisible; la lectura SQL soporta charge/payment, sin inventar un cargo para el pago aislado. `transaction` requiere un adaptador centralizado auditado distinto; no hay consulta a tablas particulares de canales.

El limite de confianza es interno: estos contratos no autentican al llamador. Construir un objeto o proporcionar un hash no demuestra que los hechos esten verificados. El futuro servicio autorizado debe obtenerlos de relaciones/procedencia auditadas y nunca aceptar estos flags directamente del navegador.

## Precedencia de la politica

| Condicion, en orden | Resultado en sombra |
|---|---|
| Pagado, cancelado o suscripcion comprobada inactiva | `no_action`, incluso si existe señal de seguridad o simulacion P2 alta. |
| Cobertura desconocida, anterior al rechazo o vencida | `refresh_data`; no proponer una gestion con informacion antigua. |
| Estado distinto de rechazo, enlaces o conciliacion no verificados | `review_evidence`. |
| Señal de seguridad sustentada por reglas | `review_security_signal`; no afirmar fraude de una persona. |
| Mandato inactivo, instrumento inutilizable o cuenta cerrada | `review_mandate_or_instrument`. |
| Conflicto, ausencia, codigo no mapeado, regla provisional, restricciones desconocidas o limite alcanzado | `review_evidence`. |
| Incidente tecnico clasificado y controles anteriores satisfechos | `review_service_incident`. |
| Otro motivo clasificado y controles anteriores satisfechos | `review_collection_options`, solo revision humana de opciones. |

Todas las salidas tienen `execution_allowed=false`, restriccion `no_automatic_retry`, confianza nula y probabilidad real de recuperacion nula. No se generan fechas de reintento, contactos, enlaces, cobros o cambios de tarjeta. La categoria no concede permisos. Antes de cualquier flujo WR futuro deben releerse estado y restricciones actuales y aplicar sus permisos/banderas existentes; una recomendacion guardada no mantiene habilitada una accion.

Vigencia: `max_age_seconds` es configurable entre 1 y 86.400 segundos, con valor inicial de ingenieria de 3.600; no es un SLA del proveedor ni un umbral aprobado por negocio. El corte y todos los relojes requieren zona y se normalizan a UTC para la identidad del calculo. Evidencia/cobertura futuras se rechazan. `updated_at` es revision de una fila, nunca prueba de completitud o mandato vigente.

La politica conserva todas las restricciones ML-02 y añade las verificadas por el snapshot. Un codigo de procesador ML-03 separado no se interpreta como codigo del proveedor: obliga a revisar hasta tener un mapeo aceptado. Conflictos no se resuelven automaticamente con P1. Las familias, submotivos y gravedad proceden de reglas versionadas, no de una causalidad demostrada.

## Lectura centralizada y limites deliberados

La conexion pertenece al llamador. Antes de llamar al lector debe existir una transaccion PostgreSQL **REPEATABLE READ READ ONLY** (o SERIALIZABLE READ ONLY). El lector comprueba ambas condiciones y solo ejecuta SHOW/SELECT con parametros; no empieza, confirma o cambia la transaccion. Lee como maximo una fila con sus enlaces directos. La cuenta se exige en WHERE y en cada comprobacion de relacion, incluso si la FK existe.

La proyeccion excluye nombres, contactos, instrumentos y textos libres. Devuelve estados crudos, codigo, relojes y enlaces estrictamente necesarios. `repr` no muestra sus campos; sigue siendo informacion restringida y no debe registrarse en logs. La salida del motor tambien es restringida: los hashes de evidencia son enlazables y no equivalen a anonimizar.

Core conserva estados propios de las fuentes. No se introduce un diccionario improvisado: el socio aporta un `ReviewedStateMapping` por cuenta/tipo, con vocabulario exacto y hash de su revision. Valores nuevos o nulos quedan desconocidos. El contenido del mapeo y su revision cambian la identidad del calculo. No confundir estado activo con mandato vigente.

`map_core_evidence()` exige identificador/reloj de evidencia, rechaza proyecciones posteriores al corte y compara el codigo del contexto ML-03. El enlace de la glosa revisada a esa evidencia sigue requiriendo auditoria del llamador; que un texto tenga el mismo codigo no prueba su procedencia. No extrae historicos a partir del estado actual.

**El lector no concilia todos los pagos, abonos y reversas.** Por ello el mapper siempre deja `settlement_verified=false`: una fila de rechazo no puede producir por si sola una sugerencia de gestion. Solo un adaptador de conciliacion futura auditado puede construir un snapshot completo con esa verificacion. Los demas flags desconocidos tambien conservan su estado desconocido. Una fecha reciente o una FK no sustituyen estas comprobaciones.

## Ausencia de modelos, simulacion y trazabilidad

En uso normal siempre se ejecutan reglas y/o abstencion. El motor informa `p1_unavailable` y `p2_unavailable`; versiones de artefactos nulas no generan una probabilidad falsa. No carga ningun archivo del registro, ni siquiera uno marcado activo en una simulacion ML-08. Entrenamiento, seleccion y promocion reales siguen separados.

Para probar la futura frontera se pueden proporcionar hasta dos objetos `Simulation`, uno P1 y otro P2, **solo con `simulation=true`**. Deben corresponder a cuenta y hash exacto del snapshot, con identificador de artefacto sintetico y valores validos. No se aceptan duplicados, NaN, infinitos o booleanos como scores. Son valores escritos a mano, no inferencia ni evidencia estadistica; no se afirman como artefactos autenticados del registro ML-08.

P1 simulado solo completa evidencia sin clasificar; nunca sustituye una regla clasificada o un conflicto ni elimina restricciones. P2 se expone unicamente como `simulated_p2`, separado de `recovery_probability=null`. Cambiarlo no selecciona una accion ni fija un dia de cobro. Su probabilidad observacional futura a 30 dias tampoco estimara efecto causal de contactar o reintentar. No conectar estos resultados de simulacion a una interfaz operativa.

El resultado conserva estado original de reglas, estado final, categoria/submotivo/gravedad, reglas coincidentes, restricciones, razones y versiones independientes de motor/politica/taxonomia/reglas/P1/P2. La politica tiene huella de version y presupuesto de vigencia. `logical_id` es SHA-256 del snapshot normalizado, politica y salidas simuladas ordenadas; no usa una clave con modelo NULL.

**Idempotencia logica, no persistencia:** entradas/corte/versiones iguales producen igual resultado y clave, incluso sin modelos. Un nuevo corte, revision de datos, mapeo, recurso o politica produce otra clave. No existe aun una tabla de predicciones, deduplicacion durable de lotes, exposicion al usuario o seguimiento de decisiones. ML-10/11 deberan persistir usando esta identidad y su contrato transaccional; no usar una cache de estas salidas para omitir revalidacion actual.

## Validacion realizada

**388 pruebas distintas aprobadas:** 371 puras (48 nuevas ML-09 y 323 regresiones ML-02 a ML-08) y 17 PostgreSQL (4 nuevas de lectura y 13 regresiones ML-03). Ruff completo y revision del diff pasan.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_recommendation.py tests/test_ml_artifacts.py tests/test_ml_model_evaluation.py tests/test_ml_evaluation.py tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml09-regressions -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Las pruebas PostgreSQL se ejecutaron solo en `crm_ml_registry_test`, con configuracion sintetica de proveedores y la guarda *_test existente. Para repetir, resolver primero TEST_DATABASE_URL/configuracion efectiva a una base descartable aislada: conftest recrea public y aplica migraciones. Nunca apuntarla a QA/original ni copiar una URL real a documentacion.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_core_reader.py tests/test_ml_annotations.py --basetemp=.local/pytest-ml09-db -q
~~~

PostgreSQL comprueba lectura por cuenta, pago sin cargo, enlaces de otra cuenta/nulos, necesidad de readonly y snapshot consistente, rechazo real de UPDATE por PostgreSQL y estado sin cambios. Las puras cubren conflictos, falta/antigüedad de cobertura, restricciones desconocidas, estado terminal aun con score alto, prohibicion de simular implicitamente, identidad sin modelo, zonas equivalentes, ausencia de PII e importacion sin runtime ML/configuracion DB.

No hay migracion nueva. QA y original no se tocaron; las migraciones existentes solo se aplicaron al recrear la base descartable. Sin benchmarks, cifras reales de precision, pruebas de carga o simulacro de modelos ajustados.

## Validacion pendiente del socio y siguiente frontera

1. Auditar vocabularios por cuenta y recurso, relojes reales, cobertura, origen del contexto ML-03 y relaciones; entregar solo hallazgos/agregados saneados.
2. Acordar conciliacion de pagos completos/parciales/reversos y controles de mandatos/limites antes de habilitar snapshots aptos para gestion.
3. Completar ML-06/07 con datos/modelos legitimos, calibracion y criterios revisados. No entrenar o reutilizar test desde este motor.
4. Autorizar por separado carga/inferencia confiable con aislamiento, limites de latencia/memoria y manejo de errores, y persistencia/lotes/API/permisos ML-10/11. La entrega actual prueba ausencia de modelos y salidas sinteticas, no certifica esa futura inferencia.

ML-09 queda **preparado en sombra**, con reglas/abstencion y contrato del motor probados. No se declara listo para usuarios ni se inicia ML-10 automaticamente. Rama local, sin skills incluidas ni publicacion en GitHub.
