# ML-08: pipelines sin ajustar y registro de artefactos

Fecha: 2026-11-25. **Preparación implementada; sin entrenamiento, carga de modelos o activación del CRM.** El socio validará datos/modelos completos. ADR-002 sigue Proposed.

## Pipelines preparados

app/ml/pipelines.py expone fábricas reales sin ajustar. Importar el módulo no importa sklearn. recipe() describe semilla/versión y huella del esquema; feature_matrix() valida la lista blanca ML-04 antes de ordenar columnas. Rechaza campos extra (incluidos IDs/PII), fuentes desconocidas, montos no CLP enteros, numéricos no finitos y cálculos fuera de 30 días. Vencimiento desconocido pasa a NaN, nunca a cero inventado; su imputación se aprenderá solo de entrenamiento. Convertir a float es exclusivamente para ML, sin modificar importes de Core.

| Candidato | Construcción sin ajustar |
|---|---|
| P1 char_tfidf_logistic | TF-IDF de caracteres 3–5, máximo 50.000 features; contexto one-hot con categorías desconocidas ignoradas; regresión logística C=1 y máximo 1.000 iteraciones. |
| P2 logistic | Mediana/indicadores de ausencia, conservación de columnas totalmente vacías, escalado numérico, one-hot y regresión logística C=1, máximo 1.000 iteraciones. |
| P2 hist_gradient_boosting | Imputación/indicadores y one-hot denso; 100 iteraciones, profundidad 3, máximo 15 hojas, mínimo 20 muestras por hoja. Early stopping desactivado para no crear validación interna aleatoria. |

Son configuraciones iniciales versionadas, no hiperparámetros seleccionados por resultados. Las referencias ML-02/prevalencia siguen en ML-07, sin pesos inventados. Toda afinación necesita el protocolo temporal y ejecución autorizada aparte. No hay llamada a fit/transform/predict ni comando de entrenamiento.

Usar feature_matrix(), no serializar una fila completa o construir otra matriz con distinto orden. La API genérica de sklearn no autentica el origen de una lista que un llamador arme por su cuenta. P1 exige revisión humana de privacidad previa: validar patrones no elimina todos los nombres de un texto.

build_calibrator() exige pipeline ya ajustado y construye un calibrador sigmoid sobre FrozenEstimator. No lo ajusta ni vuelve a entrenar la base. Las pruebas rechazan entradas sin ajustar. Entrenamiento, calibración y selección de umbrales siguen separados; nunca aprender vocabulario/medianas/escalas con el test.

Context7 no estaba disponible; se consultaron las fuentes oficiales de [pipelines](https://scikit-learn.org/stable/modules/compose.html), [TF-IDF](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html), [OneHotEncoder](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html), [HGB](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html) y [FrozenEstimator](https://scikit-learn.org/stable/modules/generated/sklearn.frozen.FrozenEstimator.html). Se comprobaron constructores reales, sin entrenar.

## Entorno experimental separado

requirements-ml.lock fija 16 paquetes y hashes de wheels para **CPython 3.14 / Windows AMD64**, probados en Python 3.14.7. Incluye sklearn 1.9.1, scipy 1.18.1, numpy 2.5.3, skops 0.16.0, dependencias y pytest. Versiones contrastadas con los metadatos públicos de [sklearn](https://pypi.org/pypi/scikit-learn/json), [scipy](https://pypi.org/pypi/scipy/json) y [skops](https://pypi.org/pypi/skops/json). requirements.lock y el entorno del CRM permanecen intactos.

~~~powershell
.venv/Scripts/python.exe -m venv .local/ml08-env
.local/ml08-env/Scripts/python.exe -m pip --isolated install --require-hashes --disable-pip-version-check -r requirements-ml.lock
~~~

Se verificaron hashes mediante descarga de wheels y resolución dry-run offline desde el wheelhouse. No publicar entorno, caches o wheels. Otro sistema/arquitectura necesita lock revisado; no retirar hashes para instalar. La fábrica rechaza versiones científicas distintas. Compatibilidad de artefactos exige igualdad de Python, implementación, sistema, arquitectura y versiones declaradas; no promete portabilidad entre versiones.

## Manifiestos y seguridad de artefactos

app/ml/artifacts.py verifica manifiestos HMAC del dominio ml-artifact-v1. La identidad SHA-256 abarca tarea P1/P2, fuente/cuenta, candidato, pipeline/esquema/receta/semilla, entorno, dataset/plan, filas de ajuste/calibración y hashes de código, política, pipeline/calibrador. Cambiar alguno crea otra versión.

El payload queda en almacenamiento privado ML-05, nunca Core o Git. Se comprueban tamaño y SHA. Formatos:

- skops: hasta 64 MiB, expansión ZIP hasta 128 MiB y 10.000 entradas, sin rutas de escape. get_untrusted_types inspecciona tipos sin cargar; cualquier tipo no confiable se rechaza, sin aprobarlo automáticamente ni llamar a load/loads.
- fixture-json: únicamente versión sintética, indicador untrained=true y serie numérica. No puede declararse modelo real; permite probar transacciones sin generar pesos.

Pickle/joblib como payload se rechazan. Que sklearn dependa de joblib no autoriza deserializar esos archivos. Véase [persistencia oficial y riesgos](https://scikit-learn.org/stable/model_persistence.html). La inspección no certifica archivos hostiles: no hay endpoint de uploads, cargador o proceso aislado de inferencia. Exigir origen confiable y custodia.

El descriptor exige provenance_reviewed=true y estado fixture, unfitted o externally-trained. Un artefacto reviewed-real exige entrenamiento externo declarado; esa declaración y los hashes no prueban que se haya entrenado ni la equivalencia semántica de sus pesos/política. El socio debe auditar su pipeline real.

Si se aportan referencias ML-07, se comprueban firmas/versiones, paquete/plan, candidato/ámbito, criterios, bytes del modelo y hashes frente a informe de test y congelación. Se verifica también el registro de apertura y el hash de predicciones correspondiente. Un archivo llamado “test” no basta. Evaluación verificada y entorno compatible son necesarios para aprobar registros reales; no autorizan promoción.

Todo sigue restringido aunque esté firmado: vocabulario/parámetros reales pueden retener información. HMAC acredita integridad bajo la clave, no anonimización o identidad jurídica. Rutas relativas a .local/ml-private; sin claves, binarios, vocabulario o manifiestos reales en Git. No se ejecutan instrucciones de un payload.

## Registro PostgreSQL y simulación

Nueva migración **20261125_0084**, posterior a 0083, importada en metadata Alembic:

| Tabla | Responsabilidad |
|---|---|
| ml_artifacts | Descriptor/versiones inmutables, ruta privada, hash y registrante; sin bytes. |
| ml_artifact_releases | Una fila por tarea/fuente-cuenta, puntero de versión y revisión. FK compuesta impide apuntar a otro tipo/canal. |
| ml_artifact_events | Eventos consecutivos de registro/aprobación/promoción/rollback/deshabilitación, actor, aprobación y puntero resultante. Append-only. |

Artefactos/eventos no admiten UPDATE/DELETE; el estado exige auditoría coincidente al confirmar la transacción. El servicio bloquea el ámbito y comprueba expected_revision: ante carreras, un cambio gana y el otro debe recargar. Registro del mismo contenido es idempotente. Copia/verifica identidad del descriptor para detectar mutaciones posteriores a su comprobación.

Aprobar exige otro usuario activo distinto del registrante, referencia de aprobación y compatibilidad reevaluada. Estas funciones son internas: no implementan RBAC de canal/sesión HTTP/CSRF, que corresponden a ML-11. No exponerlas directamente ni aceptar un UUID/hash como prueba suficiente de autorización. El llamador debe verificar nuevamente archivos/evidencia antes de aprobar.

simulate_release() exige simulation=true y **solo artefactos sintéticos aprobados**. Promoción, vuelta a versión previamente promovida y deshabilitación se probaron con un solo puntero e historial consistente. La promoción real se rechaza y el CRM no consume el puntero. Carga/revalidación de bytes, caché, rollback operativo y permisos quedan para ML-09/11 y su autorización.

Cada operación usa savepoint, exige sesión sin cambios ORM pendientes y no hace commit ajeno. El llamador controla commit/rollback. Archivos y PostgreSQL no forman una transacción distribuida: preparar primero archivos privados/inmutables; si falla DB pueden quedar candidatos sin registrar. No borrar paquetes automáticamente al revertir. Retención y revisión de huérfanos necesitan política acordada.

**0084 solo se aplicó a crm_ml_registry_test. QA conserva 20261118_0082 sin estas tablas; original intacta.** No ejecutar upgrade contra .env original ni migrar QA copiando estos comandos. Habilitar registro en otro entorno requiere revisión específica. Un administrador puede desactivar protecciones o cambiar archivos: no es una auditoría invulnerable a su propietario.

## Comandos de preparación para el socio

Precondiciones: repositorio local, entorno experimental compatible y clave privada existente de ML-05; no regenerar una clave en uso. --key-file permite seleccionar otra relativa.

~~~powershell
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts pipeline --candidate char_tfidf_logistic --construct-unfitted --destination pipelines/p1-sin-ajustar.json
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts pipeline --candidate logistic --construct-unfitted --destination pipelines/p2-logistica-sin-ajustar.json
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts pipeline --candidate hist_gradient_boosting --construct-unfitted --destination pipelines/p2-hgb-sin-ajustar.json
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts environment --destination environments/ml08.json
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts template --candidate logistic --source virtualpos1 --destination descriptors/p2.json
~~~

Completar privadamente solo cuando existan bytes/procedencia auténticos. Las plantillas nacen sin revisión y con hashes faltantes; no fingir entrenamiento/evidencias para hacerlas pasar. Pesos reales deberán venir del proceso externo autorizado y evaluado según ML-06/07; aquí no hay una orden de entrenamiento. Para describir recetas sin construirlas puede usarse .venv omitiendo --construct-unfitted.

~~~powershell
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts seal --descriptor descriptors/p2.json --destination artifacts/p2-manifest.json
.local/ml08-env/Scripts/python.exe -m scripts.ml.prepare_artifacts verify --manifest artifacts/p2-manifest.json
~~~

Seal valida payload/esquema/referencias antes de publicar. Verify exige además entorno actual compatible. Destinos nuevos, sin sobrescritura/rutas arbitrarias. El terminal no muestra pesos, claves o glosas. Código 2 indica rechazo; 0 no significa modelo entrenado, registrado, aprobado o activo. El CLI no escribe DB: no hay comando que pueda usar accidentalmente la base original.

## Evidencia

**353 pruebas distintas** en tres grupos:

1. **323 puras**, incluidas 14 nuevas de contratos/artefactos y regresiones ML-02 a ML-07:

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_artifacts.py tests/test_ml_model_evaluation.py tests/test_ml_evaluation.py tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml08-all -q
~~~

2. **21 PostgreSQL**, ocho nuevas y trece regresiones ML-03, en crm_ml_registry_test. Para repetir, TEST_DATABASE_URL/configuración efectiva deben señalar una base **descartable** *_test; la guarda recrea public y migra toda la cadena. Nunca usar una copia operativa; no se publican URLs, claves o wrapper local.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_artifact_registry.py tests/test_ml_annotations.py --basetemp=.local/pytest-ml08-db-final -q
~~~

3. **9 de construcción reales**: fit prohibido, ausencia de estado ajustado, calibración rechazada sin base ajustada e inspección skops de objetos sin ajustar con load/loads prohibidos. Se invocan expresamente en el entorno experimental, no se omiten para fingir compatibilidad:

~~~powershell
.local/ml08-env/Scripts/python.exe -m pytest scripts/ml/check_pipeline_construction.py --noconftest --basetemp=.local/pytest-ml08-construct-final -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Ruff completo pasa. La comprobación de cabeza ML-03 ahora usa el head vigente, conservando verificación de esquema/downgrade; 0083 aplicada no cambió. SQL prueba idempotencia, aprobación independiente, aislamiento tipo/canal, historial, rollback del llamador, auditoría diferida, downgrade protegido y promociones concurrentes con un ganador.

Además pasó CLI nativo Windows: tres pipelines construidos sin ajustar, skops de objeto sin ajustar y manifiesto firmado/inspeccionado, sin load/entrenamiento. QA se verificó en solo lectura. El socio validará mapeo/datos completos, entrenamiento/calibración externos, pesos reales, distribución de variables, entorno destino, custodia y resultados ML-07. No se midieron latencia/carga o calidad con datos reales. Fixtures, claves, entorno y wheelhouse permanecen ignorados/locales. **Sin modelos entrenados/cargados, activación del CRM, exportación real, skills incluidas o push.**
