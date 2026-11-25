# ML-07: evaluación de predicciones congeladas

Fecha: 2026-11-25. **Evaluador preparado; ejecución con modelos/datos reales y decisión por el socio pendientes.** Solo se usaron predicciones sintéticas escritas a mano para comprobar fórmulas y controles. Ningún modelo se entrenó, cargó, calibró o activó; no hay ganador real y ADR-002 sigue Proposed.

## Alcance y precondiciones

El evaluador es independiente del entrenamiento: recibe decisiones P1 o probabilidades P2 emitidas por pipelines externos confiables y congelados. No importa sklearn/Pandas/joblib, no abre pesos ni ejecuta código de un modelo. No implementa los entrenadores TF-IDF/logística/HistGradientBoosting ni un adaptador `predict` a esos pipelines. El socio deberá disponer de esas piezas o desarrollarlas en una tarea separada y autorizada; las plantillas no producen un modelo entrenado.

Entradas: paquete autenticado ML-05, protocolo y plan firmados ML-06 con `structural_preflight_passed`, criterios estadísticos revisados y predicciones con procedencia. Se vuelve a construir el plan para comprobar que cortes, grupos, purga, filas y criterios corresponden al paquete. Se mantienen las limitaciones de disponibilidad histórica, fuente/cuenta y cobertura de ML-04/06; no se consultan bases ni se inventa extracción SQL. No trasladar datos completos o credenciales a este equipo.

## Criterios estadísticos y archivos de predicciones

`init-criteria` crea una plantilla privada que debe completar el socio antes de abrir el test. `version=frozen-evaluation-v1` y `agreement_sha256` deben coincidir con la referencia humana del plan. Definir clases evaluables, mínimo por clase y fuente, mínimo de unidades de incertidumbre, entre 200 y 2.000 réplicas bootstrap, bins de calibración entre 2 y 20, unidad de remuestreo y regla de comparación. Los mínimos nacen sin completar; no inventar valores para superar bloqueos. El margen y la cobertura mínima se toman del protocolo ML-06. La referencia/hash es una declaración auditada por el socio, no prueba automática de su aprobación.

Las clases deben estar predeclaradas: P1 usa familias de la taxonomía; P2 exactamente `[0,1]`. Una etiqueta o predicción fuera de ellas falla, sin descartar filas para mejorar el score. No cambiar clases o población mirando el test. Si un canal carece de soporte suficiente, el informe queda sin elegibilidad; un mínimo mecánico no sustituye un análisis de potencia.

Cada JSON de predicciones exige exactamente:

- `version`, `task`, `package_id`, `plan_id`, `phase` (`selection`/`test`), `candidate_id`, `artifacts`, `rows`.
- `artifacts`: hashes SHA-256 de modelo o descripción de la referencia (`model_sha256`), preprocesamiento (`pipeline_sha256`), política de decisión/abstención (`decision_policy_sha256`), código y entorno de ajuste (`fit_code_sha256`, `fit_environment_sha256`); `calibrator_sha256` puede ser `null`.
- `training_rows_sha256`: huella de las claves de entrenamiento previstas, excepto reglas ML-02, que no se entrenan. `calibration_rows_sha256` debe coincidir con calibración si hay calibrador; si no, debe ser `null`. Las referencias no admiten calibrador.
- `rows`: una fila por cada clave de la etapa prevista, con `row_key` y `prediction`. No se permiten duplicados, faltantes o filas de otra partición. Una abstención es `null` explícito. P1 admite una clase predeclarada; P2 un número finito en `[0,1]`, nunca un booleano o una fecha.

La plantilla calcula la huella de filas esperadas, no certifica que tu pipeline se haya ajustado con ellas. **No copiar esa declaración si se usaron otras filas.** Los hashes de artefactos tampoco prueban qué datos entrenaron el modelo o quién generó las predicciones: el socio debe auditar su pipeline real, transformadores, calibrador, umbrales y entorno. El evaluador nunca deserializa esos artefactos. No incluir rutas ejecutables, cuerpos de proveedor, identificadores personales o glosas en el archivo de predicciones.

## Selección, referencias y métricas

La selección exige todos los comparadores preinscritos: P1 `ml02_rules` y `char_tfidf_logistic`; P2 `train_prevalence`, `logistic`, `hist_gradient_boosting`. No eliminar un candidato después de ver sus resultados sin registrar un protocolo nuevo antes del test.

Las referencias se auditan, no se aceptan ciegamente. P2 debe usar una probabilidad constante igual a la prevalencia de **solo entrenamiento**, sin calibrador; verificar esa media es un conteo de referencia, no ajustar un estimador. P1 debe coincidir con ML-02 vigente: solo emite familia cuando la clasificación está resuelta y no requiere revisión; en otros casos se abstiene. No asignarle confianza del 100 %. Las etiquetas humanas de referencia permanecen independientes de las reglas.

Lectura selectiva: se verifican hashes de todos los archivos, pero se interpretan etiquetas solo de selección y, para auditar prevalencia P2, entrenamiento. Fuera de esas particiones se inspecciona exclusivamente la cabecera de clave de la fila determinista ML-05; no se decodifica su valor `target`. Para reglas P1 se leen entradas de las filas seleccionadas. En el test sucede lo mismo, **después** de registrar su apertura.

| Tarea | Informe agregado, global y por fuente |
|---|---|
| P1 | F1 macro de extremo a extremo, soporte, precisión/recall por clase, confusión incluyendo abstención, cobertura y exactitud condicional/global. Abstenerse cuenta como falso negativo de la clase real. Clase ausente no se rellena con cero: macro no evaluable y elegibilidad bloqueada. V1 recibe decisiones, no vectores de confianza; no valida calibración de probabilidades P1. |
| P2 | Brier binario, AUROC, average precision, cobertura y bins de fiabilidad con frecuencia observada/predicción media y ECE. AUROC/AP son `null` si falta una clase en las predicciones cubiertas. Brier puede ser descriptivo con una clase, pero no habilita comparación/congelación sin soporte. |

Brier es la media de `(probabilidad - etiqueta)^2`; las abstenciones no se reemplazan por cero. Los scores individuales P2 se calculan sobre sus predicciones cubiertas. **La comparación se hace pareada sobre el mismo subconjunto común**, no restando Brier global de la referencia y Brier de un modelo que omitió casos difíciles. Se exige cobertura mínima global/por fuente y soporte de ambas clases en ese subconjunto. Informar siempre cuántas filas quedaron fuera. En P1 la comparación de F1 incluye todas las abstenciones del universo de esa etapa.

Las fórmulas se contrastaron con las definiciones oficiales de [métricas](https://scikit-learn.org/stable/modules/model_evaluation.html), [Brier](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html) y [average precision](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html). AP usa incrementos de recall ponderados por precisión y agrupa empates; no se presenta como área trapezoidal PR. No se instaló ni ejecutó scikit-learn para estas métricas.

## Incertidumbre y revisión manual

Se implementa bootstrap pareado por grupos: `context` para P1 o `subscription` para P2; alternativamente `time_week` (semana ISO en UTC) en ambos, según criterio preinscrito. Repetir una persona/texto no convierte sus filas en observaciones independientes. La conveniencia de cada unidad y las dependencias entre grupos requieren revisión del socio; elegirla porque produce un intervalo favorable invalida la evaluación.

Se remuestrean grupos con reemplazo, conservando juntas sus filas y las mismas réplicas para ambos comparadores. Beneficio positivo favorece al candidato: F1 candidato menos referencia o Brier referencia menos candidato. Se usa intervalo percentil bilateral del 95 %, semilla registrada y al menos 90 % de réplicas evaluables. Si faltan grupos/clases, la unidad es desconocida o se supera el presupuesto de dos millones de extracciones de grupos por comparación, el intervalo es `null`: no fabricar certeza ni elegir ganador. P2 usa sumas de errores por grupo para evitar reconstruir todas las filas en cada réplica.

`non_inferiority` requiere límite inferior del beneficio al menos `-margen`; `practical_superiority` exige que supere `margen`. Además deben pasar soporte, cobertura y unidades globales y por fuente. `eligible_for_manual_freeze` solo indica esos controles en selección: no aprueba negocio, potencia, causalidad o producción. No se selecciona automáticamente el mayor score; ante no inferioridad, justificar complejidad/costo frente a la referencia más simple en la aprobación humana. Después del test se informa `meets_frozen_checks`, nunca una nueva elección.

Los intervalos son aproximaciones bajo la unidad/criterios elegidos, no una garantía para datos reales. Las pruebas con predicciones perfectas artificiales solo verifican implementación; no estiman precisión de SynkmetriX. El informe permanece privado: puede contener celdas pequeñas o clases sensibles. Compartir únicamente agregados revisados/suprimidos por el socio, no el archivo completo ni IDs de grupos.

## Congelación y apertura única del test

`freeze` exige informe de selección firmado del mismo paquete, plan y criterios, candidato que pase los controles y una referencia privada de aprobación no vacía. Conserva sus hashes, los de la referencia, informe de selección, huella del evaluador, hora UTC local y hash de aprobación. Los informes registran revisión Git, árbol modificado, Python/sistema y huella del lock; se exige el mismo código/entorno de evaluación entre selección, congelación y test. No carga modelos ni acredita identidad jurídica del firmante; HMAC acredita integridad bajo la custodia de la clave. Cambiar código, modelo, transformadores, calibrador o política después invalida el test de esa congelación.

`test` exige `--open-test` y únicamente las predicciones de referencia y candidato congelado. Antes de interpretar una etiqueta del test escribe, de forma exclusiva, `receipts/<package_id>/test.json`, con congelación, hashes de predicciones, destino y hora UTC del sistema. Una reapertura del mismo paquete se rechaza, incluso si se pide otra ruta de informe o congelación. Un fallo posterior deja el registro consumido: **no borrarlo para reintentar silenciosamente**; documentar incidencia y revisar custodia/nuevo test. El informe final enlaza congelación y registro de apertura.

Es una barrera de flujo local, no una bóveda contra quien controla archivos y clave. El propietario puede borrar registros o crear otro paquete: el socio debe impedir reutilizar casos ya vistos mediante custodia y trazabilidad del estudio, también entre reexportaciones. El reloj local no es sellado de tiempo confiable. No ajustar modelos/umbrales viendo el test y seguir llamándolo reservado. `winner=null`, `training_executed=false` y `activation_authorized=false` se conservan en todos los informes.

## Ejecución por el socio, cuando tenga predicciones reales aptas

Precondiciones: mapeo SQL y cobertura auditados, paquete ML-05 y plan ML-06 auténticos, código local confirmado y sus modelos/pipelines preparados en un entorno experimental confiable. Datos reales se rechazan con árbol Git modificado. Predicciones sintéticas deben marcarse como tales en el paquete y no usarse como prueba de calidad real. Las rutas siguientes son ejemplos relativos a `.local/ml-private`; elegir nombres que correspondan al estudio propio y destinos nuevos.

```powershell
.venv/Scripts/python.exe -m scripts.ml.evaluate_models init-criteria --plan plans/estudio-p2.json --destination criteria/estudio-p2.json

$evaluacionML = @('--bundle', 'exports/corte-20261125-p2', '--plan', 'plans/estudio-p2.json', '--protocol', 'protocols/estudio-p2.json', '--criteria', 'criteria/estudio-p2.json')

foreach ($candidatoML in @('train_prevalence', 'logistic', 'hist_gradient_boosting')) {
    .venv/Scripts/python.exe -m scripts.ml.evaluate_models prediction-template @evaluacionML --candidate $candidatoML --phase selection --destination "predictions/selection-$candidatoML.json"
}
```

Completar criterios antes de evaluar y rellenar las plantillas con **predicciones externas reales y procedencia verificada**. Las plantillas tienen `null` y no son artefactos de modelo. Si hay calibrador, aportar la huella de las filas de calibración previstas. Luego:

```powershell
.venv/Scripts/python.exe -m scripts.ml.evaluate_models selection @evaluacionML --prediction predictions/selection-train_prevalence.json --prediction predictions/selection-logistic.json --prediction predictions/selection-hist_gradient_boosting.json --destination reports/seleccion-p2.json
```

Revisar métricas, cobertura, exclusiones previas, dependencia, soporte, intervalos y costos. No congelar un candidato solo porque exista el archivo. Si logística es la elección humana justificada —ejemplo de comando, no recomendación de ganador— registrar aprobación privada y congelar:

```powershell
.venv/Scripts/python.exe -m scripts.ml.evaluate_models freeze @evaluacionML --selection-report reports/seleccion-p2.json --candidate logistic --approval-reference approvals/decision-p2.txt --destination freezes/p2.json
```

Preparar predicciones de test para referencia y candidato con los mismos hashes. `prediction-template --phase test` permite generar las claves sin abrir etiquetas. **Solo el custodio, tras la revisión y congelación**, ejecutará la apertura final explícita:

```powershell
.venv/Scripts/python.exe -m scripts.ml.evaluate_models test @evaluacionML --freeze freezes/p2.json --prediction predictions/test-train_prevalence.json --prediction predictions/test-logistic.json --destination reports/test-p2.json --open-test
.venv/Scripts/python.exe -m scripts.ml.evaluate_models verify --kind report --document reports/test-p2.json
```

P1 usa sus dos candidatos preinscritos y clases P1, conservando el mismo flujo. `--key-file` permite la clave privada relativa del estudio. El CLI imprime solo estado genérico, nunca probabilidades, etiquetas, claves o glosas. Código 2 indica rechazo; un informe con falta de soporte puede guardarse correctamente con elegibilidad falsa, por lo que código 0 **no** significa que un modelo gane. `verify` admite también `--kind freeze` y `--kind receipt` para comprobar integridad, sin autorizar activación.

## Evidencia y límites locales

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_model_evaluation.py tests/test_ml_evaluation.py tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml07-final -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

**309 pruebas pasan, 19 nuevas de ML-07; Ruff completo sin errores.** Fórmulas con resultados conocidos, empates/AUC/AP, abstención, clases ausentes, intervalos reproducibles, soportes insuficientes, filas/procedencia/predicciones inválidas, lectura selectiva, referencias auditadas, cambios de pipeline, apertura explícita, fallo posterior y reapertura bloqueada. Regresiones ML-02 a ML-06 incluidas. Se movió la firma de planes a una función compartida preservando el formato ML-06, sin cambiar modelos de datos o migraciones.

Además se ejecutó el CLI real de Windows con claves/ACL privadas, paquete y predicciones fabricadas: selección, congelación, test sintético registrado y segundo intento rechazado. No se entrenó ni cargó un modelo. Los artefactos de humo y claves permanecen ignorados/restringidos, fuera de Git. No se midió rendimiento sobre volúmenes reales ni validez estadística del bootstrap con datos del socio. Sin DB/QA/original, nuevas dependencias, cambios API/ETL/frontend, skills incluidas o push. **Entrenamiento/calibración externa, auditoría de procedencia, evaluación real y aceptación/activación siguen pendientes del socio y revisión conjunta.**
