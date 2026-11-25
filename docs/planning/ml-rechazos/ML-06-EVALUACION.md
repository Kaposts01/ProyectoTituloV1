# ML-06: protocolo de evaluación y comparación aislada

Fecha: 2026-11-25. **Protocolo y planificador offline implementados con pruebas sintéticas; ningún modelo entrenado, predicción producida o benchmark ejecutado.** El socio validará datos completos, criterios y entorno. ML-07 sigue pendiente y ADR-002 conserva estado Proposed.

## Qué entrega la herramienta

`app/ml/evaluation_protocol.py` valida la preinscripción y asigna filas; `evaluation_package.py` verifica un paquete ML-05 y sus metadatos; `scripts/ml/prepare_evaluation.py` crea plantillas, guarda planes privados y verifica su integridad. No hay conexión a DB/proveedores, carga de modelos, instalación de dependencias o llamada a `fit`.

El plan contiene cuatro particiones disjuntas, filas seudonimizadas, cortes UTC, conteos por fuente, exclusiones, bloqueos, candidatos/métrica propuestos, límites para un futuro proceso experimental y fingerprints de protocolo/paquete/código. Se autentica con HMAC y no sobrescribe documentos. Reutiliza el almacenamiento privado ML-05; no guarda glosas, variables, probabilidades, etiquetas o una matriz de confusión en el plan. `winner=null`, `benchmark_status=not_run` y `training_executed=false` son explícitos.

La verificación calcula hashes de los archivos completos, incluido `targets.jsonl`, pero **no interpreta sus etiquetas**. El planificador lee semánticamente metadatos; solo el modo P1 de textos no vistos lee además texto saneado para agruparlo sin etiquetas. El manifiesto ML-05 ya contiene agregados de clases: se autentican, pero no se usan para ajustar cortes o informar distribución del test. No confundir lectura de bytes para integridad con apertura estadística del test.

`structural_preflight_passed` significa únicamente que pasaron los controles de este plan. Soporte por clase, potencia, calidad de etiquetas/cobertura, calibración, incertidumbre y aceptación de negocio siguen pendientes. Ni siquiera un fichero de etiquetas malformado, pero firmado por un productor de confianza, se interpreta aquí: el futuro ejecutor deberá validar sus tipos/alineación antes de usarlas. El planificador no reemplaza esa validación.

## Cortes y prevención de fugas

Definir, sin consultar resultados del test, cinco instantes con zona:

| Intervalo por `calculated_at` | Uso permitido futuro | Disponibilidad de etiquetas exigida |
|---|---|---|
| `[train_start, train_end)` | Ajustar variables derivadas, vocabulario, imputación, escalado y modelos. Afinación interna solo dentro de entrenamiento, con folds temporales propios. | Hasta `train_end`. |
| `[train_end, calibration_end)` | Ajustar calibrador de probabilidades, con modelo/preprocesamiento ya congelados. | Hasta `calibration_end`. |
| `[calibration_end, selection_end)` | Comparar candidatos, definir abstención/umbrales y congelar la elección según criterios preinscritos. | Hasta `selection_end`. |
| `[selection_end, test_end)` | Una evaluación final reservada, después de congelar modelo, calibrador y umbrales. | Hasta el corte autenticado `as_of` del paquete. |

Los intervalos son cerrados a izquierda y abiertos a derecha. El final de test no puede superar `as_of`. P2 exige además, conservadoramente, `test_end + 30 días <= as_of` para que el período nominal sea observable completo, evitando comparar solo los casos recientes ya resueltos.

En las tres primeras etapas, un resultado P2 que termine **en o después** del siguiente corte se purga: sus ventanas son inclusivas y podrían solaparse. No se reemplaza por un número fijo de filas. Una etiqueta que llegó después del corte de su etapa también se excluye, aunque esté en el snapshot final. Empates exactos de disponibilidad en el corte se permiten si no hay solapamiento de ventana. Relojes, política P2 a 720 horas y versiones deben coincidir con ML-04/05.

Esto conserva una restricción real: etiquetas humanas creadas hoy para eventos antiguos pueden dejar entrenamiento sin filas bajo cortes históricos. **No retroceder `reviewed_at` ni falsear disponibilidad para hacerlo pasar.** Un estudio retrospectivo con anotación posterior necesitaría un protocolo de etiquetado ciego específico, revisión de sus límites y otra versión; el plan actual mantiene la puerta estricta. La declaración `retrospective-limited` no la desactiva ni convierte el estudio en validación operativa punto en el tiempo.

La separación y el ajuste de transformadores antes del test se apoyan en la [guía oficial de fugas de datos](https://scikit-learn.org/stable/common_pitfalls.html). La [documentación de calibración](https://scikit-learn.org/stable/modules/calibration.html) orienta la etapa separada de calibrador. `TimeSeriesSplit` expresa su [gap en muestras](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html); por eso aquí la purga usa relojes y horizontes reales. No se instaló ni ejecutó scikit-learn; su compatibilidad/lock experimental siguen por verificar antes de ML-07.

## Tráfico temporal y poblaciones no vistas

Elegir una política por protocolo y registrar planes distintos para análisis distintos:

- `temporal`: tráfico cronológico real; admite textos/suscripciones ya observados. No demuestra generalización a entidades nuevas.
- P1 `unseen_context`: contexto ML-03 completo nunca observado en una etapa anterior del paquete. Diferente código/procesador puede constituir otro contexto aunque el texto coincida; no llamarlo automáticamente “glosa nueva”.
- P1 `unseen_text`: agrupación global entre fuentes por texto saneado, normalizando mayúsculas, acentos, espacios, puntuación y guiones bajos (`wording-v1`). Se genera HMAC sin exponer el texto. Evita considerar nueva una variante como “SÍN FONDOS!” frente a “Sin fondos”. No reconoce sinónimos ni demuestra novedad semántica. Texto ausente/código solo se excluye de este análisis.
- P2 `unseen_subscription`: grupos de suscripción verificados y disjuntos entre etapas. Una clave ausente se excluye; no sustituir por UUID de obligación ni RUT. “Nueva” significa no observada antes en este paquete, no nueva para toda la organización ni persona nueva.

Cada grupo pertenece a su primer intervalo nominal, incluyendo historia anterior al inicio del estudio; sus apariciones en etapas posteriores se excluyen. No se elimina entrenamiento mirando qué grupos aparecerán en el test. El agrupamiento P1 de texto usa únicamente entradas para una regla ciega predefinida, nunca etiquetas ni un vocabulario aprendido. No inspeccionar manualmente esos textos para modificar candidatos tras planificar. Un único paquete con clave/alcance coherentes evita mezclar seudónimos incompatibles; combinación de múltiples paquetes todavía no implementada.

## Criterios y comparación a congelar antes del test

La configuración exige tarea, fuentes esperadas, cortes, agrupación y mínimo de filas **por fuente y etapa**, no solo un total que pueda ocultar un canal vacío. `criteria_status=agreed` exige margen práctico, cobertura mínima de predicciones y hash de la referencia privada de criterios. Una cadena/hash no certifica aprobación humana: el socio debe conservar la revisión auténtica y contrastarla. Sin esos datos el plan queda `blocked`; no se inventan 0,70/0,20 ni márgenes 0,02/0,03 operativos.

La plantilla usa mínimos y presupuestos pequeños exclusivamente para pruebas de humo; deben revisarse con el socio. Un mínimo de una fila no acredita potencia o representatividad. Antes del experimento se debe fijar soporte mínimo por clase/canal, clases evaluables, costo de errores, política de abstención, margen de no inferioridad y regla para preferir el modelo más simple. Estas condiciones detalladas viven en la referencia privada versionada, no en decisiones tomadas después de ver el test.

| Tarea | Comparadores predefinidos, aún no ejecutados | Evaluación futura |
|---|---|---|
| P1 | Reglas ML-02 frente a TF-IDF de caracteres + regresión logística. | Primaria `macro_f1_end_to_end` a maximizar, incluyendo abstenciones como fallos de cobertura. Además precisión/recall por clase, errores peligrosos, cobertura/abstención y desempeño condicional sobre clasificados. Las reglas no reciben probabilidades ficticias; las etiquetas de referencia son humanas independientes. |
| P2 | Prevalencia calculada solo con entrenamiento; regresión logística; HistGradientBoosting. | Primaria Brier a minimizar; calibración con fiabilidad por rangos, PR-AUC y AUROC complementaria. Comprobar ambas clases; métricas indefinidas se informan como no evaluables, no como cero. No atribuir efecto causal de un reintento. |

Comparar los mismos eventos/episodios y cortes, informando cobertura del universo elegible y del subconjunto común de predicciones; no ocultar abstenciones eliminando filas. Clases ausentes o soporte insuficiente requieren resultado inconcluso contra el protocolo, no cambiar clases o fechas mirando el test. Registrar desconocidos, glosas/contextos independientes y múltiples observaciones por suscripción; repeticiones no son muestras independientes.

Propuesta de incertidumbre a acordar antes de ML-07: comparación pareada y remuestreo por bloques temporales/grupos verificables, no filas tratadas como independientes; intervalo del 95 %, unidad, repeticiones y semilla documentados. La conveniencia de ese procedimiento depende del volumen y dependencia reales. No implementado ni validado estadísticamente aquí. Sin evidencia suficiente no seleccionar ganador. Las diferencias y su incertidumbre deben contrastarse con el margen práctico acordado, no solo con el mejor valor puntual.

## Aislamiento y presupuesto futuro

No hay imports de sklearn/Pandas, procesos de entrenamiento, API o scheduler. `seed`, `max_trials`, `max_fit_seconds`, `max_memory_mb` y `max_threads` solo registran presupuestos para el futuro ejecutor: **no se afirma que este planificador limite un entrenamiento que todavía no existe**. El ejecutor de ML-07 deberá funcionar en proceso separado, dependencias experimentales reproducibles, límites de memoria/CPU/tiempo comprobados y sin acceso de escritura a proveedores o bases operativas. No cargar `pickle/joblib` de orígenes no confiables. Ningún algoritmo, librería adicional o GPU se habilita por haber escrito este protocolo.

El test está reservado por procedimiento, no por una barrera criptográfica contra el propietario del dataset. El operador con acceso a archivos/clave puede abrirlo manualmente. El socio debe designar custodia, documentar la congelación y registrar una única apertura final. Si se usa el test para corregir variables, modelos, calibración o umbrales, pasa a desarrollo y hace falta otro test reservado. Este CLI no tiene una orden para abrirlo o evaluarlo.

## Comandos existentes para el socio

Precondición: paquete ML-05 revisado/autenticado en `.local/ml-private`, clave original y datos/criterios locales; [exportación y límites SQL](ML-05-EXPORTACION.md). No hace falta trasladar su base aquí. Preparar una plantilla privada nueva:

```powershell
.venv/Scripts/python.exe -m scripts.ml.prepare_evaluation init-protocol --task p2 --destination protocols/estudio-p2.json
```

Editar ese archivo en su equipo: cinco fechas ISO con zona verificadas por cobertura (por ejemplo, formato `2025-01-01T00:00:00Z`, no un corte recomendado), fuentes, identificador sin PII, agrupación, mínimos, criterios/referencia y presupuestos. Las fechas de plantilla son deliberadamente inválidas hasta editarlas y los criterios nacen en borrador. No publicar configuración con referencia a casos individuales. Después:

```powershell
.venv/Scripts/python.exe -m scripts.ml.prepare_evaluation plan --bundle exports/corte-20261125-p2 --protocol protocols/estudio-p2.json --destination plans/estudio-p2.json
.venv/Scripts/python.exe -m scripts.ml.prepare_evaluation verify-plan --document plans/estudio-p2.json
```

Las rutas son relativas al directorio privado; se mantiene exclusión Git y ACL ML-05, sin sobrescritura. `--key-file` selecciona otra clave privada relativa cuando corresponda. Código 0: plantilla/verificación o controles estructurales pasados; 2: esquema/integridad/permisos/destino inválidos; 3: plan privado guardado con bloqueos que deben revisarse. Los resultados individuales/seudónimos quedan privados; el terminal no muestra glosas, etiquetas o claves. Datos reales requieren código local confirmado; propósito sintético permite árbol modificado y lo registra.

El plan guarda protocolo/hash, identidad y corte del paquete, estado de estudio declarado, versión/huella del ejecutor, lock, particiones/exclusiones y MAC. Cambiar protocolo/paquete/código genera otro plan; no reutilizar un documento previo como si avalara nuevos datos. `verify-plan` acredita integridad, no aceptación estadística ni entrenamiento autorizado. No hay todavía comandos de entrenamiento, calibración o benchmark: no sustituirlos por instrucciones ficticias.

## Evidencia local y condiciones de ML-07

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_evaluation.py tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml06-all -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

**290 pruebas pasan, 26 nuevas de ML-06; Ruff completo sin errores.** Casos de cortes exactos, purga por ventana real, disponibilidad de etiquetas por etapa, grupos observados antes del estudio, palabras normalizadas, fuentes/criterios/madurez insuficientes, duplicados, firmas/paquetes alterados, tareas incompatibles, test no interpretado y CLI sin entrenamiento/valores sensibles. Regresiones ML-02/03 puras, ML-04 y ML-05 incluidas; ACL nativa cubierta por ML-05. Además CLI real de Windows: paquete sintético autenticado, cuatro particiones y plan privado firmado/verificado, sin métricas de modelos. No se repiten pruebas PostgreSQL porque no cambió persistencia. No se consultó/migró QA u original; no cambian frontend, API, ETL o dependencias.

El socio deberá confirmar: mapeo SQL y procedencia del snapshot, relojes/enlaces/cobertura y política ML-04, criterios aprobados, intervalos/soporte/potencia, custodia del test y compatibilidad del entorno experimental. Compartirá solo agregados saneados, versiones/fingerprints y fallos revisados, suprimiendo celdas pequeñas identificables. El entrenamiento/calibración y evaluación reales de ML-07 requieren su autorización correspondiente y ejecutar desarrollo separado del test. **Sin ganador elegido, probabilidades validadas, modelos entrenados/activados, skills incluidas o push.**
