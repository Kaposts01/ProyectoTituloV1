# Motor de rechazos asistido: plan revisado

Fecha: 2026-11-24. Alcance: propuesta de integracion sobre `codex/actualizacion-20261118`, revisada desde el documento aportado `PLAN_ML_RECHAZOS.md`. Su original en Downloads no se modifica. Estados, responsables y criterios de tareas: [docs/tasks.md, familia ML](../../tasks.md#417-motor-de-rechazos-definiciones-y-viabilidad-2026-11-24). Decision arquitectonica: [ADR-002, propuesta](../../decisions/ADR-002-motor-rechazos-asistido.md).

**ML-00 termino en definiciones y auditoria QA. ML-02, autorizado el 2026-11-24, implementa solo taxonomia y reglas puras aisladas ([contrato y pruebas](ML-02-TAXONOMIA.md)). No se entrena, compara algoritmos, migra, materializa Core ni consulta proveedores; no hay integracion operativa del motor.**

Actualizacion 2026-11-25: ML-03 incorporo anotacion e historial con migracion probada solo en una base descartable ([contrato](ML-03-ANOTACION.md)). ML-04 añade contratos puros y dataset temporal sintetico separados P1/P2 ([diccionario y politica experimental](ML-04-DATASET-TEMPORAL.md)), sin nuevas migraciones ni acceso a datos. La politica y datos reales requieren validacion del socio; no hay entrenamiento o activacion. Estado vigente exclusivamente en docs/tasks.md.

ML-05, autorizado el 2026-11-25: [exportacion offline restringida](ML-05-EXPORTACION.md) desde snapshot JSON revisado, manifiesto reproducible, seudonimizacion e integridad, CLI y ACL Windows probados con datos sinteticos. No se extrajeron datos reales ni se implemento una consulta SQL que invente disponibilidad/cobertura: ese mapeo depende de la auditoria del entorno del socio. Sin entrenamiento, migraciones o activacion; ML-06/07 no se ejecutan automaticamente.

## 1. Resultado de revisar la propuesta

Separar tres responsabilidades: **explicar el rechazo (P1)**, **estimar un resultado financiero a 30 dias (P2)** y **evaluar una accion permitida (politica)**. Ninguna necesita que un LLM decida o ejecute operaciones. CPU es la direccion propuesta; el presupuesto de recursos se mide despues, sin prometer rendimiento ni ahorro monetario no comprobado.

La matriz teorica del documento es una hipotesis de seleccion, no un resultado experimental. No se validaron las cifras de GPU ni las comparaciones bibliograficas contra este problema. No atribuir a una ley la eleccion obligatoria de un algoritmo ni presentar interpretabilidad como certificacion de cumplimiento.

La [auditoria QA](QA-2026-11-24.md) limita las conclusiones locales: no hay datos Core, transacciones Toku/Payku, detalles de rechazo ni historial de recuperaciones en esta copia. TCH tiene glosas pero apenas 10 combinaciones normalizadas y sin etiquetas revisadas. El usuario aclara que su socio conserva practicamente todos los datos de proveedores y realizara las pruebas con ellos. Esto permite desarrollar aqui contratos, pipelines y pruebas funcionales; la representatividad, trazabilidad y evaluacion estadistica se verificaran en el entorno del socio, sin exigir trasladar su base a este equipo.

## 2. Arquitectura y fronteras

Se conserva `Fuentes -> Connectors -> STG/Raw -> ETL -> PostgreSQL Core -> API -> CRM`.

- El motor productivo leera Core, detalles de rechazo e historial vinculados de forma verificable. Inspeccionar staging para auditar o reconciliar cobertura no lo convierte en una nueva fuente productiva paralela.
- `app/ml/`: contratos puros, preparacion reproducible, pipelines, evaluacion y registro. `app/services/rejection_engine.py`: coordinacion de inferencia y politica; sin clientes HTTP de proveedores. Scripts offline separados de rutas HTTP.
- Inferencia con modelos precargados y limites de tamaño/tiempo; entrenamiento en proceso independiente, con CPU, memoria e hilos limitados. Sin entrenar durante una peticion ni bloquear la sincronizacion si ML falla.
- Clasificacion posterior a confirmacion exitosa de ETL Core; sync exitosa sola no basta. TCH requiere su propio punto posterior a carga/ETL. Trabajo reanudable por lotes e idempotente; registrar fallos ML aparte de `sync_runs`/`write_runs` sin falsear sus resultados.
- Si faltan modelo, cobertura, variables o compatibilidad, devolver reglas/revision y probabilidad ausente, nunca cero inventado.

## 3. Contratos funcionales

Definiciones operativas completas en [DEFINICIONES.md](DEFINICIONES.md). Son propuestas para revision del dominio, no nuevas reglas financieras desplegadas.

**P1:** clasificacion de una evidencia de rechazo por fuente/cuenta y recurso. Prioridad: evidencia estructurada verificada, correccion humana auditada y reglas versionadas. El clasificador estadistico solo cubre casos no resueltos; una contradiccion entre codigo y texto activa revision, no una sustitucion silenciosa. Deben distinguirse `rule`, `ml`, `manual`, `unmapped`, dato ausente y conflicto.

Mantener las ocho familias iniciales como vocabulario candidato, con submotivo y gravedad independientes:

| Familia | Interpretacion y restriccion |
|---|---|
| FUNDS | Fondos insuficientes; no promete recuperacion ni autoriza un nuevo intento. |
| LIMIT | Limite de monto o frecuencia; distinguir de limite de reintentos, que puede bloquear toda accion. |
| TECH | Falla tecnica; revisar politica y estado antes de recomendar esperar. |
| EXPIRED | Vencimiento informado; actualizacion solo mediante flujo existente autorizado. |
| BLOCKED | Bloqueo temporal/permanente, cuenta cerrada o mandato revocado son submotivos distintos. No equiparar revocacion a tarjeta desactualizada. |
| INVALID | Datos o instrumento invalidos; no solicitar ni almacenar datos de tarjeta en el CRM. |
| FRAUD | Señal de seguridad; etiqueta interna orientativa y revision humana, sin acusar al socio. |
| ISSUER | Rechazo generico del emisor expresamente informado. **No es el contenedor de todo desconocido.** |

Cuando falte evidencia o no encaje: `category=null` y estado explicito, no una novena causa inventada. No exigir que todos los codigos oficiales tengan una accion o una categoria forzada. Validar la taxonomia con negocio antes del mapeo definitivo.

**P2:** probabilidad de pago confirmado de la misma obligacion dentro de 30 dias desde el primer rechazo verificable del episodio, bajo el proceso de gestion observado. No es probabilidad causal de exito de un reintento ni una prediccion de fecha optima. Solo calcular para poblaciones y canales validados; el resto queda sin estimacion.

**Politica:** permisos, estado actual, mandato, restricciones y limites del proveedor prevalecen sobre ambos modelos. Sin fecha sugerida hasta disponer de una politica sustentada. No crear links de pago, mensajes ni solicitudes a proveedor. La aprobacion del ejecutivo tampoco sustituye permisos y banderas WR existentes.

## 4. Datos, privacidad y anotacion

- Lista blanca inicial candidata: canal, codigo/gravedad de procesador, texto de motivo saneado para P1; familia validada, monto/moneda, edad de obligacion y conteos historicos verificables anteriores al corte para P2. No agregar una variable sin justificar disponibilidad, riesgo y prueba temporal.
- Excluir RUT, nombres, correo, telefono, direcciones, identificadores de medios de pago, PAN, CVV, credenciales y IDs externos como predictores. Unirse por claves verificadas dentro de la base; no inferir identidad por RUT o por monto/fecha similares.
- Las glosas son texto libre: sanear antes de exportar/anotar y bloquear contenido dudoso. Los regex de auditoria no certifican ausencia de datos personales. Ni quitar columnas ni aplicar hash equivale a anonimizar.
- Identificadores auxiliares para agrupacion/particiones, si se requieren, solo en metadatos restringidos con seudonimizacion y clave protegida; nunca variables del modelo ni archivos publicos. Evaluar retencion y acceso tambien para artefactos, vocabulario TF-IDF y explicaciones.
- Etiquetas por fuente, codigo y texto normalizado versionado, con procedencia, autor, fecha y revisiones. La misma frase puede tener sentidos distintos por canal. Revisar conflictos y clases raras con un segundo criterio humano; no evaluar contra etiquetas generadas por las propias reglas como si fueran verdad independiente.
- Medir casos y glosas independientes, distribucion por clase y canal, cobertura y sesgo de seleccion. Miles de repeticiones de diez textos no prueban generalizacion.

## 5. Evaluacion futura y seleccion

No hay algoritmos ganadores todavia. Propuesta: reglas solas primero; P1 TF-IDF de caracteres + regresion logistica y candidatos simples. P2 regresion logistica frente a HistGradientBoosting; LightGBM/CatBoost solo si una necesidad medida justifica probarlos en entorno experimental aislado. Scikit-learn puede seguir siendo necesario para P1/preprocesamiento aunque otro algoritmo gane P2.

- Validar compatibilidad con Python 3.14 y el lock del proyecto antes de instalar. Mantener dependencias experimentales fuera del runtime; fijar las que realmente use la solucion seleccionada.
- Entrenamiento, calibracion y test cronologicos separados. Las etiquetas del entrenamiento deben haber madurado antes del corte de entrenamiento; lo mismo para calibracion antes del test. Purgar episodios con ventanas solapadas por fechas reales, no asumir que un `gap` de filas son 30 dias.
- Particiones y transformaciones reproducibles: ajustar vectorizador, imputacion, escalado y modelo solo con entrenamiento. Conservar manifiesto con consulta, corte, cobertura, esquema, versiones, semilla y fingerprint del dataset restringido.
- P1: F1 macro, precision/recall por familia, abstencion, cobertura y errores peligrosos; medir tanto trafico temporal real como glosas no vistas. P2: Brier y calibracion para probabilidades, PR-AUC/discriminacion y AUROC complementaria; comparar con prevalencia y reglas. Informar intervalos de incertidumbre y resultados por canal.
- Eliminar la ambigüedad entre margenes 0,02/0,03: **antes de abrir el test**, acordar costo de error, cobertura util y margen practico. Preferir el modelo mas simple no inferior bajo ese protocolo. Sin margen acordado o datos suficientes, no declarar ganador automaticamente.
- 0,70 y 0,20 quedan como valores de investigacion del borrador, no umbrales operativos. Ajustarlos en validacion segun tarea y riesgo. Mantener separados confianza P1 y probabilidad P2; una regla no recibe un 100 % estadistico ficticio.
- Explicaciones por factores presentes al corte y limitaciones; contribuciones predictivas no demuestran causalidad. No introducir SHAP u otra dependencia antes de justificarla.

Referencias tecnicas: [fuga de datos](https://scikit-learn.org/stable/common_pitfalls.html), [calibracion](https://scikit-learn.org/stable/modules/calibration.html), [validacion temporal](https://scikit-learn.org/stable/modules/cross_validation.html).

## 6. Persistencia, seguridad y operacion propuestas

Esquema aun no aplicado; no imponer una migracion por tabla si una revision coherente facilita integridad. Siempre nuevas revisiones, imports Alembic y pruebas PostgreSQL aisladas.

| Concepto | Ajuste respecto al borrador |
|---|---|
| Etiquetas y revisiones | Clave contextual, version de normalizacion y taxonomia; correcciones append-only, sin sobrescribir silenciosamente. |
| Registro de modelos | Tipos P1/P2 y alcance/poblacion, dataset/feature schema, metrica, entorno, hash y aprobacion. Una version activa por tipo/alcance con restriccion y activacion transaccional. |
| Predicciones | Evento/episodio y recursos tipados; admitir rechazo asociado solo a pago. Conservar cuenta VP1/VP2 y enlaces a evidencia. Versiones P1, P2, reglas y politica independientes. |
| Idempotencia y vigencia | Clave no nula por evidencia/episodio, corte/fingerprint y bundle de versiones; funciona sin modelo. Misma evidencia produce una sola corrida logica; cambios de datos/version crean nueva prediccion trazable. No sugerir accion sobre un cobro ya pagado/cancelado. |
| Revisiones y corridas | Autor, razon y antes/despues; lotes, duracion, errores saneados, cobertura y rollback. No mezclar evaluacion de ML con resultados de operaciones a proveedores. |

No existe un indice universal `source + charge_external_id + model_version_id`: pierde intentos/pagos, confunde P1/P2 y permite duplicados con NULL.

Permisos ML sumados a permisos del canal/recurso, nunca sustituyendolos. CSRF y auditoria para etiquetado/activacion; inferencia GET no entrena ni cambia modelos. No aceptar uploads `joblib` arbitrarios ni rutas de artefactos controladas por cliente. Hash no autentica origen: directorio restringido, procedencia confiable y entorno compatible son obligatorios ([persistencia segura](https://scikit-learn.org/stable/model_persistence.html)).

`ML_REJECTIONS_ENABLED` y `ML_RETRAIN_ENABLED` nacen apagadas. Activacion, rollback y retencion se prueban antes del piloto. Reentrenar no equivale a promover: primer campeon/retador con aprobacion manual, evitando reutilizar indefinidamente el mismo test. Monitorear cobertura, clases nuevas, antigüedad de fuentes, calibracion tras madurar resultados y cambios de poblacion.

## 7. Entregas y condiciones de avance

| Entrega | Salida y condicion |
|---|---|
| ML-00: esta entrega | Definiciones, ADR propuesto, auditoria segura y diagnostico por canal. |
| Datos del socio, antes de evaluar | El socio audita una copia controlada de su entorno completo; no asumir cobertura o enlaces por tener mas filas. No es requisito copiar sus datos al equipo del usuario. Materializacion o importaciones, si hacen falta, siguen siendo tareas separadas autorizadas. |
| ML-02/03 | Reglas y anotacion saneada. TCH disponible para revisar, sin prometer un clasificador entrenado. |
| ML-04/05 | Dataset temporal: admitir P1 y P2 por separado solo tras controles de trazabilidad, privacidad y poblacion. Si P2 falla, continuar P1 sin porcentajes. |
| ML-06/07 | Preparar localmente un runner reproducible; el socio ejecuta entrenamiento/calibracion y benchmark con particiones de sus datos aptos. Sin usar el test para ajustar modelos ni afirmar resultados a partir de muestras sinteticas. |
| ML-08/09/11 | Registro, motor y API con fallback y permisos, inicialmente en sombra. Validar carga, archivos confiables, idempotencia, latencia y rollback antes de mostrar resultados. |
| ML-12 | Un piloto en Recuperador con ejecutivos: estado, corte, fuente, explicacion y revision humana. Registrar exposicion y decisiones para medir despues. |
| ML-10/13/14 | Lotes tras ETL confirmado, candidato mensual sin promocion automatica inicial y medicion prospectiva. Diferenciar tasa observada de efecto causal; no atribuir mejora por comparar grupos seleccionados por el modelo. |

El estado real vive solo en `docs/tasks.md`. No ejecutar toda la secuencia con una aprobacion del plan. Esta solicitud no autoriza PR, Git Flow, cambio a develop ni publicacion; se conserva rama local y skills excluidas.

## 8. Trabajo entre ambos integrantes

El usuario trabaja en experiencia de usuario, diseño de modelos y otras partes del proyecto. En este checkout se desarrollaran las implementaciones y pruebas de contratos, privacidad, permisos, serializacion, fallback e integracion, con datos sinteticos o parciales. Su socio, con datos mas completos, ejecutara las pruebas de datos y de desempeño estadistico. Este reparto no elimina la necesidad de probar localmente el codigo ni transfiere por si solo la aprobacion de negocio.

**Crear el codigo de un modelo no equivale a entregar un modelo entrenado y validado.** Si no existe un artefacto entrenado legitimo, el socio debera ejecutar tambien entrenamiento y calibracion sobre sus particiones de desarrollo, antes de la evaluacion reservada. No entrenar con el conjunto de prueba. La seleccion definitiva, umbrales y activacion quedan pendientes de esa evidencia.

La entrega al socio incluira codigo/version, dependencias reproducibles, esquema de variables y objetivo, runner y comandos que existan y hayan sido probados, protocolo temporal, comprobaciones previas, criterios de aceptacion y plantilla de resultados. No incluir datos personales, credenciales ni skills. Se reciben agregados y fallos saneados; los datasets permanecen en su entorno. Detalle: [protocolo de validacion con el socio](VALIDACION-SOCIO.md).

Se mantiene la restriccion vigente: **en esta fase no entrenar modelos ni ejecutar nuevos benchmarks**. Este ajuste organiza el trabajo futuro, no autoriza ejecutarlo, publicar cambios o contactar al socio.
