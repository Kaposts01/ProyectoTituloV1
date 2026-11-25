# Guía para descargar y validar el trabajo de modelos de SynkmetriX

Fecha: 25 de noviembre de 2026. Terminal: **PowerShell en Windows**. Ejecuta los comandos desde la raíz del repositorio, salvo el primer paso de descarga.

La rama publicada es `codex/actualizacion-20261118`; el commit de referencia de ML-14 es `3008900392a4dc0b8e9f51112eb373dbc1d29a0c`. Contiene preparación técnica y pruebas sintéticas, **no modelos entrenados ni certificados con datos reales**. Esta guía no incluye ni necesita skills personales, claves o bases del otro integrante.

## 1. Qué está listo y qué falta

| Parte | Disponible | Pendiente antes del uso real |
|---|---|---|
| P1: motivo del rechazo | Taxonomía, reglas con abstención, revisiones y receta TF-IDF/regresión logística. | Revisar motivos por proveedor, etiquetar con criterio humano independiente y entrenar/evaluar si los datos son aptos. |
| P2: pago completo a 30 días | Contrato temporal, variables y recetas de regresión logística/HistGradientBoosting. | Demostrar enlace rechazo-pago de la misma obligación, fechas/cobertura y resultados maduros; entrenar y calibrar. |
| Datos | Exportación privada desde snapshot JSON revisado; auditor de agregados QA en solo lectura. | Extracción SQL completa hacia el snapshot y adaptación al entorno del socio. El lector Core existente no sustituye un extractor temporal auditado. |
| Evaluación | Particiones temporales, evaluador de predicciones externas, selección y apertura de prueba final registrada. | Ejecutor de entrenamiento/calibración/predicción, predicciones reales y criterios de aceptación acordados. |
| Integración | Registro, lotes, API y piloto TCH preparados para pruebas sintéticas, apagados. | Cargador/inferencia seguros y conexión operativa, validación de permisos, carga y experiencia con ejecutivos. |
| Monitoreo/seguimiento | Informes descriptivos y registro prospectivo preparados. | Captura futura autenticada, datos reales, responsables y diseño de comparación. |

La evidencia de la entrega ML-14 registra **658 pruebas distintas aprobadas**, incluidas 46 nuevas; no representa exactitud del modelo ni certificación de producción. La decisión de arquitectura ML-01/ADR-002 sigue propuesta. Permanece la deuda frontend QA-ML12-01: diez fallos en la corrida global documentada, varios reproducidos en una versión anterior y otros sensibles a ejecución conjunta.

## 2. Descargar la rama

Necesitas Git, acceso al repositorio y Python 3.14. La preparación científica se comprobó en CPython 3.14.7, Windows AMD64; otro entorno debe revisarse antes de usar su lock.

### Opción recomendada: una carpeta nueva

Abre PowerShell en una carpeta de trabajo de tu elección. El nombre de destino debe estar libre:

```powershell
git clone --branch codex/actualizacion-20261118 --single-branch https://github.com/Kaposts01/ProyectoTituloV1.git SynkmetriX-validacion
if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar el repositorio. Revisa acceso y carpeta de destino.' }
Set-Location SynkmetriX-validacion
git branch --show-current
git log -1 --oneline
git status --short
git merge-base --is-ancestor 3008900392a4dc0b8e9f51112eb373dbc1d29a0c HEAD
if ($LASTEXITCODE -ne 0) { throw 'Esta copia no contiene la entrega ML-14 indicada.' }
```

`clone --branch` descarga y selecciona la rama; `--single-branch` limita las referencias descargadas. Los siguientes comandos comprueban rama, versión y cambios locales. La comprobación de ancestro admite una versión posterior que contenga ML-14. Si el repositorio solicita autenticación, usa el mecanismo de GitHub/Git Credential Manager; no insertes un token en la URL.

### Alternativa: ya tienes el repositorio

Desde su raíz y con el árbol limpio:

```powershell
git status --short
if (git status --porcelain) { throw 'Hay cambios locales. Conserva tu trabajo antes de cambiar de rama.' }
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar la información de GitHub.' }
git switch codex/actualizacion-20261118
if ($LASTEXITCODE -ne 0) { throw 'No se pudo seleccionar la rama; revisa si existe su referencia remota.' }
git pull --ff-only origin codex/actualizacion-20261118
if ($LASTEXITCODE -ne 0) { throw 'Las ramas difieren; revisa la historia antes de integrarlas.' }
git log -1 --oneline
```

`fetch` consulta GitHub; `switch` selecciona la rama y puede crear el seguimiento de la remota si no existe localmente; `pull --ff-only` avanza solo si no requiere mezclar historias. No uses `reset --hard`, limpieza forzada ni sobrescribas archivos para resolver diferencias.

## 3. Preparar el entorno y comprobar el código sin conectar bases

En la copia nueva, crea un entorno propio; no reutilices ni reemplaces el del CRM operativo:

```powershell
py -3.14 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Revisa la instalación de Python 3.14.' }
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'No continúes: falló la instalación de dependencias.' }
.\.venv\Scripts\python.exe -m ruff check app tests alembic scripts
if ($LASTEXITCODE -ne 0) { throw 'Revisa los errores del control estático.' }
```

Si no tienes el lanzador `py`, usa la ruta del ejecutable CPython 3.14 instalado. Los comandos posteriores usan el ejecutable del entorno directamente; no necesitan activar PowerShell ni cambiar su política de ejecución.

Pruebas puras de preparación ML, **sin conexión, migraciones ni entrenamiento**:

```powershell
$pruebasML = @(
  'tests/test_ml_taxonomy.py',
  'tests/test_ml_annotation_contract.py',
  'tests/test_ml_temporal_dataset.py',
  'tests/test_ml_dataset_export.py',
  'tests/test_ml_evaluation.py',
  'tests/test_ml_model_evaluation.py',
  'tests/test_ml_artifacts.py',
  'tests/test_ml_recommendation.py',
  'tests/test_ml_batch_contract.py',
  'tests/test_ml_monitoring.py',
  'tests/test_ml_prospective.py',
  'tests/test_toku_rejection_codes.py',
  'tests/test_rejection_format.py',
  'scripts/ml/tests/test_audit_readiness.py'
)
.\.venv\Scripts\python.exe -m pytest @pruebasML --noconftest --basetemp=.local/pytest-socio-puras -q
if ($LASTEXITCODE -ne 0) { throw 'Conserva el fallo saneado y corrige antes de continuar.' }
```

Para la versión de referencia son **459 pruebas**. `--noconftest` evita el inicializador general que recrea el esquema de pruebas. No ejecutes la suite completa contra una base con datos reales: las pruebas PostgreSQL necesitan una base descartable separada, guardas de `tests/conftest.py` y configuración sintética revisada. Las migraciones 0083–0087 se probaron únicamente en ese tipo de base; descargar la rama no las aplica.

Opcional, para comprobar constructores sin entrenar, en Windows AMD64 compatible:

```powershell
.\.venv\Scripts\python.exe -m venv .local/ml-env
.\.local\ml-env\Scripts\python.exe -m pip --isolated install --require-hashes -r requirements-ml.lock
if ($LASTEXITCODE -ne 0) { throw 'Revisa compatibilidad; no retires los hashes del lock.' }
.\.local\ml-env\Scripts\python.exe -m pytest scripts/ml/check_pipeline_construction.py --noconftest --basetemp=.local/pytest-socio-constructores -q
```

Mantén separado ese entorno científico. Construir un pipeline no lo entrena ni produce predicciones.

## 4. Auditar tus datos completos

Trabaja sobre una **copia controlada y aislada**, con respaldo y acceso limitado. No arranques el backend, scheduler, sincronizaciones o migraciones contra tu base original para hacer esta auditoría. No necesitas compartir tu base ni credenciales con el otro integrante.

Entrega un inventario por `virtualpos1`, `virtualpos2`, Toku, Payku y TCH: fechas observables, rechazos/obligaciones, pagos, glosas distintas, campos ausentes, enlaces y exclusiones. Comprueba disponibilidad histórica; `updated_at` actual no demuestra cuándo se conocía un dato.

| Objetivo | Comprobación necesaria | Si falta |
|---|---|---|
| P1 | Motivos saneados, contexto por proveedor y etiquetas humanas revisadas; cubrir desconocidos, conflictos y clases raras. | Revisar/anotar antes de entrenar. Miles de repeticiones de pocas glosas no prueban generalización. |
| P2 | Rechazo y pago neto completo de la misma obligación/cuenta, fechas útiles y seguimiento verificable de 30 días. | Excluir y contabilizar; no transformar ausencia de información en impago. |
| Ambos | Variables disponibles al cálculo, unidades de agrupación, privacidad, representatividad y criterios previos. | Documentar el bloqueo; no llenar valores para superar controles. |

P1 puede avanzar sin P2. Un reporte mensual TCH puede no demostrar un plazo exacto de treinta días. No emparejes personas solo por RUT/correo ni asignes cualquier pago de una suscripción a un rechazo.

El auditor existente admite **solo** una copia QA revisada en loopback, puerto 5433 y nombre `crm_qa_*`; no es un conector universal. Si tu entorno no coincide, detenerse y adaptar/revisar el acceso en una tarea separada. No renombres la base operativa para superar la guarda.

Para un destino ya verificado, el responsable configura privadamente `ML_AUDIT_DATABASE_URL` en el proceso, sin imprimirla ni escribirla en el comando. Sustituye el nombre QA por el destino real autorizado:

```powershell
if (-not $env:ML_AUDIT_DATABASE_URL) { throw 'Falta configurar privadamente la conexión a la copia QA autorizada.' }
$baseQAModelos = 'crm_qa_copia_socio'
$corteModelos = (Get-Date).ToUniversalTime().ToString('o')
try {
  .\.venv\Scripts\python.exe -m scripts.ml.audit_readiness --expected-database $baseQAModelos --as-of $corteModelos --out .local/auditoria-socio/agregados.json
  if ($LASTEXITCODE -ne 0) { throw 'Auditoría incompleta: revisar destino, permisos o esquema.' }
} finally {
  Remove-Item Env:ML_AUDIT_DATABASE_URL -ErrorAction SilentlyContinue
}
```

La transacción es de solo lectura y se revierte. El informe contiene agregados, pero su directorio solo está ignorado por Git: el auditor no aplica las ACL del exportador. Usa una carpeta de trabajo con permisos restringidos, revisa celdas pequeñas y no compartas automáticamente el JSON. No certifica conciliación ni anonimización. Si necesitas un corte anterior, fíjalo explícitamente con zona horaria.

## 5. Preparar dataset y protocolo, tras revisar la viabilidad

**Punto de detención:** falta implementar/auditar la extracción real hacia el snapshot ML-04/05. No existe un comando que transforme automáticamente tu base completa en un dataset apto. Revisar primero [definiciones](DEFINICIONES.md), [dataset temporal](ML-04-DATASET-TEMPORAL.md) y [exportación](ML-05-EXPORTACION.md).

Los siguientes son comandos existentes, **condicionados** a tener un snapshot real revisado, código local confirmado sin modificaciones y custodia privada. No ejecutan entrenamiento. Nombres de estudio/rutas son ejemplos y deben ser nuevos, relativos a `.local/ml-private`.

```powershell
git check-ignore .local/ml-private/
.\.venv\Scripts\python.exe -m scripts.ml.export_dataset init-key
```

Crear la clave solo una vez para un estudio nuevo; no reemplazar ni regenerar una clave existente. El exportador comprueba permisos privados del sistema y no sobrescribe archivos. Depositar mediante un flujo privado el snapshot revisado en `snapshot-revisado.json`, dentro de ese directorio; no copiar filas a documentación, GitHub o chat.

```powershell
.\.venv\Scripts\python.exe -m scripts.ml.export_dataset export --snapshot snapshot-revisado.json --destination exports/estudio-p2 --scope estudio-rechazos-v1 --allow-reviewed-real
if ($LASTEXITCODE -ne 0) { throw 'Exportación rechazada: no continúes.' }
.\.venv\Scripts\python.exe -m scripts.ml.export_dataset verify --destination exports/estudio-p2
if ($LASTEXITCODE -ne 0) { throw 'Paquete no verificado.' }
.\.venv\Scripts\python.exe -m scripts.ml.prepare_evaluation init-protocol --task p2 --destination protocols/estudio-p2.json
```

Completa la plantilla **antes de evaluar**: fechas, fuentes, agrupación, mínimos, costos/margen práctico y revisión humana. Sus fechas iniciales no son válidas y sus criterios nacen en borrador. Mantén separadas las particiones cronológicas de entrenamiento, calibración, selección y test; purga ventanas solapadas y exige madurez de etiquetas. No fijes criterios mirando el test.

```powershell
.\.venv\Scripts\python.exe -m scripts.ml.prepare_evaluation plan --bundle exports/estudio-p2 --protocol protocols/estudio-p2.json --destination plans/estudio-p2.json
if ($LASTEXITCODE -ne 0) { throw 'Plan rechazado o con bloqueos: revisar antes de seguir.' }
.\.venv\Scripts\python.exe -m scripts.ml.prepare_evaluation verify-plan --document plans/estudio-p2.json
```

El plan devuelve código 3 si guarda bloqueos; no es aprobación estadística. Para P1 prepara otro estudio con su propio snapshot, `--task p1` y nombres distintos. No mezcles resultados de proveedores o tareas como si todos tuvieran igual cobertura.

## 6. Entrenamiento y evaluación real

**Falta el ejecutor completo de entrenamiento/calibración/predicción. No hay un comando `train` que puedas ejecutar en esta rama.** Debemos implementarlo o integrar uno externo confiable y auditar su procedencia antes de avanzar. Esta guía no autoriza entrenar, cargar modelos o activar operaciones por sí sola.

Cuando esa pieza exista y el experimento esté autorizado: ajustar vocabulario/imputación/escalas/modelo solo con entrenamiento, calibrar en su partición, generar predicciones de selección con hashes auténticos y compararlas con las referencias. P1: reglas frente a TF-IDF/logística; P2: prevalencia de entrenamiento, logística y HistGradientBoosting. Conservar semilla, entorno, filas y artefactos privados.

El evaluador ya existente consume esas predicciones externas; sus plantillas vacías no las generan. Flujo detallado y comandos: [ML-07](ML-07-EVALUAR-MODELOS.md). Ayudas disponibles sin acceder a datos:

```powershell
.\.venv\Scripts\python.exe -m scripts.ml.evaluate_models prediction-template --help
.\.venv\Scripts\python.exe -m scripts.ml.evaluate_models selection --help
.\.venv\Scripts\python.exe -m scripts.ml.evaluate_models freeze --help
.\.venv\Scripts\python.exe -m scripts.ml.evaluate_models test --help
```

Acordar criterios → evaluar selección → justificar candidato → congelar versiones → abrir test reservado **una sola vez**, mediante `--open-test`, por su custodio. No borrar el registro para repetir una apertura fallida. Si usas el test para corregir algo, pasa a desarrollo y necesitas otro test reservado.

P1: F1 macro, precisión/recall por clase, cobertura, abstención y glosas no vistas. P2: Brier/calibración, PR-AUC/AUROC, cobertura e incertidumbre por canal, comparando sobre los mismos casos. Código 0 o una métrica favorable aislada no significan aprobación. [Pipelines/registro ML-08](ML-08-PIPELINES-ARTEFACTOS.md) explica custodia, compatibilidad y rechazo de payloads no confiables.

## 7. Piloto, seguimiento y aceptación

Después de una revisión conjunta, preparar integración real y probar con ejecutivos, permisos, datos incompletos, fallback, rendimiento y rollback. Los componentes que hoy exigen `synthetic` y base `*_test` **no se habilitan sobre datos reales cambiando etiquetas o el nombre de la base**. El piloto TCH no enlaza automáticamente resultados sintéticos con fichas reales.

Para [ML-14](ML-14-MEDICION-PROSPECTIVA.md), acordar e instrumentar captura futura autenticada: inscribir antes de conocer resultados, incluir no expuestos y registrar exposición, decisión y resultado por separado. Su horizonte es 30 días desde inscripción; el objetivo predictivo P2 usa el primer rechazo verificable de la obligación, según su contrato. No confundir los dos relojes.

Una recuperación observada no demuestra impacto causal. Si quieren medir impacto, acordar previamente control/asignación, población, seguimiento y análisis. Tener el histórico completo no reemplaza esa observación futura. No hay activación automática, reentrenamiento o cobros autorizados.

## 8. Qué devolver al otro integrante

Compartir un informe saneado con:

- Commit, sistema/Python/dependencias y versiones de esquema/reglas/modelos.
- Fechas y conteos por proveedor/cuenta: obligaciones, unidades, clases, exclusiones, resultados maduros y desconocidos; estado P1 y P2 por separado.
- Criterios acordados, períodos de cada partición y conclusión cumple/no cumple/bloqueado.
- Métricas reales frente a las referencias, incertidumbre, cobertura y limitaciones; si todavía no se entrenó, indicarlo expresamente.
- Fallos saneados, tiempos/recursos, pruebas de permisos/fallback/rollback y correcciones requeridas.

No compartir claves, URLs de conexión, nombres/RUT/contactos/glosas individuales, bases, archivos de predicciones o artefactos sin revisión. Revisar y agrupar celdas pequeñas. Los datos completos permanecen bajo custodia del socio. La aceptación y activación son decisiones posteriores conjuntas.

Orden recomendado inmediato: **descargar → pruebas puras → inventario/auditoría → decisión P1/P2 por cuenta → completar extracción y ejecutor → evaluación real → piloto futuro**. El estado oficial del plan está en [docs/tasks.md](../../tasks.md), no en el número de pruebas aprobadas.
