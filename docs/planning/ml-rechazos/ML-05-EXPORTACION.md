# ML-05: exportación restringida y reproducible

Fecha: 2026-11-25. Exportador offline implementado y probado con datos sintéticos. **No se exportaron datos reales, consultaron bases, entrenaron modelos o activaron funciones del CRM.** El socio validará la procedencia y los contratos con sus datos completos. ADR-002 sigue Proposed.

## Alcance y límite de extracción

La entrada es un snapshot JSON revisado que expresa los contratos de ML-04. `prepare_snapshot()` valida el archivo entero y vuelve a construir P1/P2 con sus reglas temporales; no acepta filas de entrenamiento ya etiquetadas arbitrariamente. `build_bundle()` serializa el resultado; `export_files` protege el destino y verifica integridad. El CLI es `python -m scripts.ml.export_dataset` desde la raíz.

**No hay extractor SQL automático.** Core conserva estados actuales y no demuestra por sí solo el historial, la primera disponibilidad o la cobertura exigida. El adaptador JSON está listo; la consulta y el mapeo Core/historial -> snapshot del socio siguen condicionados a auditar sus tablas/relojes/enlaces y aprobar la política experimental ML-04. No inventar campos temporales ni usar staging como fuente productiva paralela. Esta condición limita la preparación real, no las pruebas locales del exportador.

## Entrada estricta `rejection-snapshot-v1`

UTF-8, hasta 32 MiB y 100.000 registros por colección. Se rechazan claves duplicadas, columnas extra, tipos incorrectos, infinitos/NaN, versiones incompatibles, fechas sin zona y glosas no revisadas. Los errores del CLI no muestran valores, claves, glosas o trazas. Los importes se reciben como **texto decimal**, sin convertir dinero a `float`.

| Parte | Campos obligatorios |
|---|---|
| Común | `schema_version`, `task` (`p1`/`p2`), `purpose` (`synthetic`/`reviewed-real`), `as_of` ISO con zona, `privacy_reviewed`, `policy_reviewed`, `provenance`. Las dos revisiones deben ser `true`. |
| Procedencia | `adapter_version` identificador sin PII; `query_sha256`, `source_snapshot_sha256`, `dependencies_sha256` (64 hex); `code_revision` (40 hex); `study_mode`: `retrospective-limited` o `point-in-time`. |
| P1 | `observations`, `reviews`, `review_history_complete=true`. |
| Observación P1 | `observation_id`, `context`, `occurred_at`, `available_at`. |
| Revisión P1 | `context`, `revision`, `decision`, `category`, `reviewed_at`, `actor_id`. Historial auténtico completo ML-03, no etiquetas de reglas. |
| Contexto P1 | `source`, `resource_type`, `processor`, `code`, `processor_code`, `normalized_text`, `normalization_version`, `taxonomy_version`, `privacy_reviewed=true`; todos explícitos. |
| P2 | `events`, `coverages`. |
| Evento P2 | `event_id`, `source`, `obligation_id`, `kind`, `occurred_at`, `available_at`, `amount`, `currency`, `link_verified`, `subscription_id`, `due_at`, `due_available_at`. |
| Cobertura P2 | `evidence_id`, `source`, `obligation_id`, `observed_from`, `observed_through`, `available_at`, `complete`, `reconciled`, `history_complete`. |

Los campos que admiten ausencia deben existir con `null`, sin eliminarlos. UUID son claves internas verificadas, no RUT/email o identificadores externos convertidos por semejanza. `kind` usa `rejection`, `confirmed_full_payment`, `partial_payment`, `reversal`, `ambiguous`. Contextos, nulos, estados, monedas, enlaces y cobertura mantienen las restricciones de [ML-04](ML-04-DATASET-TEMPORAL.md). Una bandera de revisión no prueba por sí sola privacidad o calidad: exige verificación humana real.

Los hashes de procedencia de entrada son declaraciones del adaptador. El socio debe conservar privadamente la consulta parametrizada, sus parámetros/corte, versión de mapeo y originales que permitan reproducirlos; no poner SQL con valores personales, credenciales o paths privados en el manifiesto. El exportador calcula además el hash exacto del snapshot recibido. Tener un hash no acredita que una fuente esté completa.

## Paquete y separación de responsabilidades

Cada destino nuevo contiene únicamente:

- `features.jsonl`: `row_key` y objeto `features` de la lista blanca ML-04.
- `targets.jsonl`: `row_key` y `target`. No incluirlo en predictores.
- `metadata.jsonl`: `row_key`, agrupaciones/referencias seudonimizadas, relojes, revisiones y versiones para trazabilidad y futura partición temporal.
- `manifest.json`: versiones, tarea/corte, finalidad, procedencia de entrada y exportador, huellas de código/lock, Python/sistema, esquema, filas, clases, exclusiones por motivo, conteos por fuente y declaraciones de cobertura, tamaños/hashes y autenticación del paquete.

Las tres salidas se enlazan con `row_key`; **este campo es auxiliar, nunca predictor**. El futuro entrenamiento debe leer únicamente `features` y la etiqueta enlazada, manteniendo metadatos fuera de la matriz. CLP se serializa como texto entero exacto; nulos como JSON `null`, sin imputación. No hay asignación de folds ni transformadores entrenados en ML-05.

La seudonimización usa HMAC-SHA256 con clave aleatoria privada de 32 bytes, alcance explícito y dominios distintos para fila, obligación, suscripción, contexto y evidencia. No se exportan UUID originales, autores o la clave. Un mismo contexto P1 conserva su grupo; una suscripción P2 verificada conserva el suyo dentro de fuente/cuenta. **Seudonimización no es anonimización**: texto saneado, fechas, importes y grupos aún pueden permitir vinculación. Todo el paquete, incluido manifiesto, sigue restringido. No compartir celdas pequeñas ni manifiestos completos como si fueran resúmenes públicos.

Para agrupar entre cortes, conservar clave/alcance coherentes. Rotarlos cambia grupos y filas; no mezclar resultados sin una estrategia revisada porque podría falsear la evaluación por grupos. La clave no se entrega junto al paquete ni se publica. El socio conserva sus datos y claves en su entorno; aquí solo se esperan agregados saneados.

## Reproducibilidad, autenticación y publicación local

Mismo snapshot exacto, clave, alcance, código/lock, runtime y opciones producen los mismos bytes. No se agregan hora actual, rutas personales o UUID aleatorios de exportación. Orden, JSON y relojes UTC son estables. Cambiar orden/bytes del snapshot cambia su fingerprint aunque represente hechos equivalentes; otro runtime/sistema/código también puede cambiar el manifiesto. No se promete igualdad de paquetes entre entornos distintos.

El fingerprint SHA-256 identifica el contenido y el MAC HMAC-SHA256 autentica el manifiesto y los hashes de archivos para quien protege la clave. Detectan modificaciones/cambio de clave; no certifican veracidad del proveedor, consentimiento, cobertura, rendimiento estadístico ni autorización para entrenar. El código de exportación guarda su revisión Git, hash de los archivos fuente realmente usados, huella de `requirements.lock`, runtime y si el árbol estaba modificado. Datos reales requieren árbol limpio; la finalidad sintética permite cambios locales y los registra.

El directorio se crea de forma exclusiva: no sobrescribe claves ni paquetes existentes. Se escribe el manifiesto al final y se sincronizan los archivos; un error revierte solo archivos creados por esa operación. Un cierre abrupto puede dejar una carpeta privada incompleta: `verify` la rechaza. No se hace borrado recursivo de destinos. Esto es publicación local por marcador de finalización, **no** un rename atómico de toda la carpeta; consumidores futuros deben verificarla antes de usarla.

## Almacenamiento y uso desde terminal

El CLI limita entradas, claves y salidas a `.local/ml-private/`, verifica que Git la ignore, bloquea rutas absolutas/traversales, nombres reservados, enlaces y puntos de redirección. Ignorar en Git no da privacidad: primero comprueba los permisos del sistema. En Windows crea directorios sin herencia pública y con acceso para el usuario actual y SYSTEM; valida propietario y permisos al leer/escribir. Se usan las API oficiales de [aplicación de ACL](https://learn.microsoft.com/en-us/dotnet/api/system.io.directory.setaccesscontrol?view=netframework-4.8.1) y [lectura de ACL](https://learn.microsoft.com/en-us/dotnet/api/system.io.directory.getaccesscontrol?view=netframework-4.8.1), desde Windows PowerShell, probadas en este equipo. Si no puede garantizar ese destino, falla sin exportar datos. No relajar permisos para saltar un rechazo. Hay una rama POSIX por propietario/modo, todavía no validada en otro sistema.

No es cifrado: administradores con privilegios y otros procesos del mismo usuario quedan fuera de ese aislamiento. La retención no se automatiza: usar un corte nuevo solo cuando sea necesario, conservar clave/originales según la política acordada del socio y retirar copias bajo su control sin publicar ni trasladar bases aquí.

Desde la raíz del repositorio, crear una vez la clave (nunca imprime su contenido):

```powershell
.venv/Scripts/python.exe -m scripts.ml.export_dataset init-key
```

Después de preparar y revisar el snapshot, depositarlo como `.local/ml-private/snapshot-revisado.json`. **No hay comando de extracción SQL todavía**. Un archivo real solo debe marcarse `reviewed-real` tras privacidad, política y procedencia verificadas; tener más filas no basta. Ejecutar con código local confirmado y destino nuevo:

```powershell
.venv/Scripts/python.exe -m scripts.ml.export_dataset export --snapshot snapshot-revisado.json --destination exports/corte-20261125-p2 --scope estudio-rechazos-v1 --allow-reviewed-real
.venv/Scripts/python.exe -m scripts.ml.export_dataset verify --destination exports/corte-20261125-p2
```

Para un snapshot sintético, mantener `purpose=synthetic` y omitir `--allow-reviewed-real`. Para P1 cambia el contenido de entrada según el esquema, no el algoritmo del CLI. `--key-file` permite una ruta privada relativa alternativa. No regenerar la clave para verificar un paquete anterior: se necesita la original. El CLI imprime solo éxito/error genérico; no enviar paquetes o claves a GitHub, ni usar `git add -f` sobre `.local`.

## Evidencia local y validación del socio

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_dataset_export.py tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml05-final -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

**264 pruebas pasan, 28 nuevas de ML-05; Ruff completo sin errores.** Se probaron separación/ausencia de UUID y claves, versiones/privacidad/tipos/tamaños, snapshots vacíos/excluidos, reproducibilidad, rotación de clave/alcance, alteraciones, manifiestos inválidos, fallos intermedios, no sobrescritura, rutas, permisos nativos y CLI sin valores sensibles. Algunas pruebas de contenido/lifecycle simulan el control de permisos; una prueba separada valida ACL/clave/escritura/verificación reales. Además se ejecutó el CLI real de Windows con clave aleatoria y dos paquetes sintéticos idénticos byte a byte, verificados. Los artefactos y claves de humo permanecen ignorados/restringidos bajo `.local`; no se incluyen en Git.

El socio validará el mapeo real a snapshot, primera disponibilidad, enlaces, cobertura, privacidad, política P2 y compatibilidad del entorno. Debe reconciliar incluidos/excluidos por fuente con su extracción, comprobar hashes/procedencia y repetir la exportación con la misma configuración antes de ML-06. Devolver únicamente agregados saneados; las declaraciones de cobertura del manifiesto no sustituyen esa auditoría. No se probó SQL, carga/volumen real ni otro sistema operativo. **No hubo acceso a QA/original, nuevas migraciones, cambios API/ETL/frontend, entrenamiento, skills incluidas o push.**
