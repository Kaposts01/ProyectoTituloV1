# ML-13: monitoreo y solicitudes de candidatos

Fecha: 2026-11-25. **Preparacion offline implementada con datos sinteticos; sin entrenamiento, carga/inferencia o promocion.** El socio validara datos completos, criterios y operacion futura. ADR-002 sigue Proposed.

## Entrega y limites

- `app/ml/monitoring.py`: contratos estrictos, monitoreo descriptivo por tarea/cuenta y solicitud de candidato pendiente de revision.
- `scripts/ml/monitor_rejections.py`: comandos privados init-policy/monitor/candidate/verify. No conecta a PostgreSQL, Core, proveedores, API, scheduler o registro de versiones activo.
- Informes/solicitudes HMAC con dominios separados, IDs y escritura exclusiva en `.local/ml-private`, usando las protecciones ML-05. Sin migracion, dependencias nuevas o cambios frontend.

No hay job mensual, entrenamiento automatico, aprobador nuevo o activacion por una alerta. No se cambia la version publicada del modelo. Las fabricas ML-08 solo describen la receta; no se llama a fit/transform/predict o a deserializadores. Un candidato solicitado no es un modelo construido, entrenado o evaluado.

## Entrada sintetica

Cada snapshot lleva version, purpose=synthetic, una de cinco cuentas concretas, tarea P1/P2, corte con zona, dos ventanas no solapadas [inicio, fin), procedencia del esquema ML-08/protocolo anterior y declaraciones de cobertura/frescura. Las observaciones deben estar disponibles al momento de la prediccion; no se permite mezclar cuentas, eventos repetidos o relojes futuros de observacion/cobertura.

Maximo 5.000 filas por ventana; CLI limita bytes de entrada a 16 MB. Campos extra se rechazan: no entregar glosas, codigos crudos, nombres, RUT, contactos, credenciales o payloads. Las referencias event_id/unit_id son tokens de 64 hex; el socio debera usar seudonimos adecuados, no asumir que SHA de un RUT anonimiza. Una misma unidad puede aparecer varias veces: se reportan unidades distintas y no se llama a cada fila una observacion independiente.

| Campo por observacion | Uso |
|---|---|
| event_id, unit_id, source | Deduplicacion, cuenta y soporte por unidad declarada; no salen como listas en el informe. |
| predicted_at, available_at | Tiempo de calculo/disponibilidad, dentro de su ventana. |
| prediction | P1: familia o abstencion; P2: probabilidad ficticia entre 0 y 1 o abstencion. Rechaza NaN, infinito y booleanos. |
| label y label_available_at | Etiqueta revisada/resultado observado y reloj; ausencia nunca se transforma en cero. |
| label_origin/provenance | P1 exige revision humana independiente; P2 resultado verificado de la misma obligacion. Un hash es referencia, no prueba suficiente por si solo. |
| outcome_link_verified/outcome_verified_through | Verificacion de enlace/seguimiento P2; no inferirla del estado actual o updated_at. |
| input_missing/context_unseen/failed | Calidad de entrada, contexto nuevo y fallo; fallo y prediccion presente son incompatibles. |
| amount_clp, elapsed_days, days_from_due | Solo P2; tipos finitos/moneda CLP entera, bins fijos. P1 no acepta esas variables. |
| latency_ms | Latencia declarada acotada; las muestras ficticias no miden rendimiento del servidor. |

P1 puede monitorearse como rules_only sin artefacto ni probabilidades. P2 exige synthetic_predictions con referencia ficticia de artefacto: no se convierte una regla en probabilidad. Este campo declara el productor; aqui no se verifica un modelo real o un puntero activo del registro.

## Ventanas maduras y soporte

P2 exige treinta dias completos para positivos y negativos. Una recuperacion temprana no entra hasta completar el horizonte. Sin etiqueta, enlace o cobertura hasta el fin de la ventana se excluye el resultado, no se registra un impago. Un negativo informado antes de completar treinta dias se excluye como prematuro. Etiquetas disponibles despues del corte tampoco se usan. P1 admite revisiones anteriores a la prediccion, pero no usa una revision posterior al corte.

Se publican conteos elegibles, etiquetas verificadas, exclusiones por causa y coberturas separadas de prediccion/etiquetado. El soporte minimo incluye filas, unidades distintas y clases. P2 requiere soporte entre predicciones con resultados verificables; si faltan clases/soporte/cobertura de etiquetas en cualquiera de las ventanas, no se declara valida la comparacion de calibracion.

La frescura exige reloj de verificacion no futuro, al menos hasta el fin de la ventana corriente y dentro del presupuesto acordado. No sustituye cobertura: ambas condiciones se comprueban. La calidad depende de que el socio audite las declaraciones y su unidad de agrupacion. No hay extractor SQL/historico automatico ni garantia de independencia estadistica por tener muchas unidades.

## Indicadores y alertas

- Tasas de prediccion, datos ausentes, contexto no visto y fallos; cobertura de etiquetas y latencia media declarada. En P2, un campo numerico nulo cuenta como ausente aunque el flag diga lo contrario.
- Distancia descriptiva TVD: mitad de la suma de diferencias absolutas de proporciones. Compara las mismas categorias/bins, incluye missing y colas. Sin filas no inventa distancia cero. Para P2 compara deciles de prediccion y bins de monto/tiempo/vencimiento; no aprende cuantiles con la ventana corriente.
- Reutiliza metricas ML-07: P1 F1 macro/soporte/confusion, P2 Brier, AUROC/AP y fiabilidad/ECE de diez bins sobre resultados maduros. Los valores con soporte insuficiente son diagnosticos parciales, no evidencia de validez.
- Detecta descenso de F1 o aumento de Brier/ECE aun si la distribucion de predicciones no cambia. Cambiar una distribucion no demuestra peor modelo o causalidad.

Las alertas piden revisar fuente/cobertura, datos ausentes, contextos nuevos, calculos, distribuciones o clasificacion/calibracion. **No recomiendan cobrar ni reemplazar un modelo.** Son umbrales descriptivos configurables, no tests de significancia, intervalos de confianza o control de falsas alarmas por comparaciones repetidas. Estacionalidad, poblaciones y ventanas de distinta duracion requieren revision.

`init-policy` crea valores **draft** de ingenieria, incluidos bins; no son recomendaciones de negocio. Antes de usar alertas operativas el socio/responsable debe fijar soporte, cobertura y costos y referenciar la revision. Cambiar politica/bins cambia su hash e informe; no ajustar umbrales hasta obtener el resultado deseado. El codigo no prueba que un hash de revision corresponda a una aprobacion autentica o anterior a conocer los datos.

Estados: insufficient_data, criteria_pending, review_required o no_threshold_crossing. Este ultimo solo significa que ningun umbral revisado se cruzo en la muestra; no equivale a modelo sano, entrenamiento aprobado o permiso de activacion. Todos conservan training_authorized=false y promotion_authorized=false.

## Solicitud de un candidato

`candidate` autentica el informe y **recalcula** su contenido desde entrada/politica privadas antes de emitir la solicitud. Debe coincidir exactamente. Propone solo las fabricas ML-08 compatibles: P1 TF-IDF/logistica o P2 logistica/HGB. No introduce una libreria nueva ni escoge ganador por monitoreo.

Requiere protocolo ML-06 de la misma tarea y una sola cuenta, distinto del protocolo anterior, con comienzo del test no anterior al corte y fin futuro. Esto evita proponer reutilizar el test previo como nuevo holdout. Hay que reservar datos aun no vistos y cumplir su madurez; parsear el protocolo no ejecuta entrenamiento, test o evaluacion.

La solicitud queda blocked_data si faltan resultados/soporte verificable o hay problemas de cobertura/entrada/fallos; blocked_criteria si no estan revisados los criterios del monitoreo o acordado el protocolo ML-06; de lo contrario awaiting_human_review. Incluye receta/semilla/esquema, informe, protocolo y artefacto anterior declarado, sin pesos.

No existe transicion automatica a aprobado. El responsable debe revisar la solicitud, autorizar por separado entrenamiento/calibracion externos, ejecutar ML-07 con un nuevo test reservado y usar ML-08/11 para revision independiente y rollback. En esta entrega esos ultimos flujos solo se probaron con artefactos sinteticos. La solicitud no modifica el registro ni implementa aprobacion de un modelo real.

## Comandos privados

Precondiciones: clave ML-05 existente y destino privado excluido de Git; no regenerar una clave en uso. Rutas relativas a `.local/ml-private`. Las entradas/protocolos los prepara el arnes sintetico o el socio tras revision, nunca apuntando a una base operativa. El CLI no puede leer archivos arbitrarios fuera del directorio ni sobrescribir destinos existentes.

~~~powershell
.venv/Scripts/python.exe -m scripts.ml.monitor_rejections init-policy --destination monitoring/policy-draft.json
.venv/Scripts/python.exe -m scripts.ml.monitor_rejections monitor --synthetic --input monitoring/input.json --policy monitoring/policy-reviewed.json --destination monitoring/report.json
.venv/Scripts/python.exe -m scripts.ml.monitor_rejections candidate --synthetic --input monitoring/input.json --policy monitoring/policy-reviewed.json --report monitoring/report.json --protocol monitoring/new-protocol.json --candidate logistic --destination monitoring/candidate-request.json
.venv/Scripts/python.exe -m scripts.ml.monitor_rejections verify --kind report --record monitoring/report.json
.venv/Scripts/python.exe -m scripts.ml.monitor_rejections verify --kind candidate --record monitoring/candidate-request.json
~~~

`--key-file` permite seleccionar otra clave privada relativa. La politica borrador y el ejemplo de politica revisada son archivos distintos: no se crea/revisa el segundo automaticamente. Referencias a formatos ejecutables o payloads de modelos no se aceptan. Terminal: mensajes fijos sin filas, claves o paths sensibles; codigo 2 indica rechazo, 0 solo preparacion/verificacion, nunca aprobacion.

Los informes guardan agregados, hashes, versiones, cortes y cobertura. Firmas HMAC prueban integridad bajo custodia de la clave, no identidad del revisor, anonimato o calidad de los datos. `verify` autentica el registro; la recomputacion completa se hace al solicitar candidato. Versiones semanticas futuras requieren revision de formato. Los archivos privados forman evidencia por version, no una cola con permisos multiusuario, retencion o scheduler implementados.

## Evidencia y siguientes pasos

**43 pruebas nuevas**, con fixtures de scores/etiquetas escritos a mano: madurez simetrica, negativos prematuros, desconocidos, cobertura/soporte/clases, drift con bins fijos, empeoramiento sin drift, criterios pendientes, protocolos nuevos, firma/fingerprint/alcance, campos personales rechazados e identidad reproducible incluso entre procesos con distinto hash seed. No hay estimator fitting o carga de pesos.

Se ejecutan tambien las 385 regresiones puras ML-02 a ML-12 y las 184 PostgreSQL/API/ETL/permisos de la base descartable, incluidos aprobacion independiente/rollback simulados. CLI nativo Windows: politica, informe, candidato, firmas y rechazo de sobrescritura, con clave aleatoria nueva de prueba; todo ignorado/local. Ruff pasa. La suite global frontend con deuda QA-ML12-01 no se repite ni se declara resuelta: no cambia frontend.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_monitoring.py --noconftest --basetemp=.local/pytest-ml13-final -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

El socio debe validar denominadores/unidades, relojes, enlaces/neto de pagos y reversas, revisiones humanas, representatividad y criterios con sus datos completos. Adaptacion a datos reales, almacenamiento/retencion de monitoreo, permisos/alertas operativas y automatizacion requieren autorizacion posterior. No hay metricas reales de calidad o carga ni eficacia causal demostrada. ML-14 no se inicia automaticamente. Sin QA/original, migracion, proveedor, entrenamiento, skill publicada o push.
