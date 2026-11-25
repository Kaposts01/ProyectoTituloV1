# ML-04: variables y dataset temporal

Fecha: 2026-11-25. **Contratos y preparación pura implementados; validación con datos completos a cargo del socio.** No se extrajeron datos, exportaron datasets, entrenaron modelos ni midieron resultados estadísticos. ADR-002 sigue Proposed.

## Alcance y política experimental

`app/ml/temporal_dataset.py` define dos datasets separados e inmutables. No importa configuración, ORM, Pandas o librerías de entrenamiento; no abre archivos, conexiones o proveedores. No cambia Core, API, ETL, UI, migraciones o indicadores.

Versiones: `rejection-dataset-v1-draft` y `first-rejection-one-obligation-v1-draft`. La política es una **propuesta experimental conservadora**, no una definición financiera aprobada: un episodio por obligación/fuente-cuenta, iniciado en su primer rechazo verificable; no reabre episodios después de recuperación. Cambiar horizonte, población, variables, normalización o tratamiento de pagos exige nueva versión y revisión antes del experimento real.

La lista de fuentes coincide con ML-03: `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch`. Si el socio tiene otras cuentas sin espacio de nombres separado, debe ampliar/versionar el contrato antes de combinarlas. Nunca reutilizar un identificador externo sin su cuenta/fuente para fabricar UUID internos.

## Diccionario de variables permitido

Solo `model_features()` produce las entradas candidatas al modelo; no convertir toda la fila con `asdict()` para entrenar. No hay transformadores ajustados ni imputación en esta entrega.

| Dataset / variable | Tipo, fuente y fórmula | Disponibilidad y nulos |
|---|---|---|
| P1 `source` | Categoría: cuenta/fuente de la evidencia, VP1/VP2 separadas | Disponible al observar el rechazo; obligatoria. |
| P1 `resource_type` | Cargo, pago, transacción o estado de suscripción del contexto ML-03 | Obligatoria; no equiparar unidades entre fuentes. |
| P1 `processor` | Identificador controlado del banco/procesador, no dato de una persona | Contexto verificado; conservar su espacio de nombres. |
| P1 `code` / `processor_code` | Código estructurado y código entre corchetes separados | Cadena vacía significa ausente; no completar usando otra fuente. |
| P1 `normalized_text` | Evidencia saneada, con normalizador y taxonomía ML-03 versionados | Revisión humana de privacidad previa; no glosa cruda. Si no se puede preservar fielmente la evidencia, excluirla. |
| P2 `source` | Cuenta/fuente del primer rechazo | Obligatoria; no representa identidad personal. |
| P2 `amount` | Decimal positivo del importe de la obligación, en el snapshot del primer rechazo | Obligatorio; sin usar el saldo actualizado después. Acotado al rango Numeric(18,2). |
| P2 `currency` | Moneda declarada en ese mismo snapshot | V1 admite solo CLP enteros para formar filas; otras monedas se excluyen, sin convertir ni mezclar. |
| P2 `elapsed_days` | `(calculated_at - t0)` en segundos UTC / 86.400 | Conocida al calcular; cero es válido. Horizonte restante: `30 - elapsed_days`. |
| P2 `days_from_due` | `(calculated_at - due_at)` en segundos UTC / 86.400 | Solo si la fecha de vencimiento era conocida al calcular. Si falta fecha/disponibilidad: `None`, nunca cero inventado. Puede ser negativo. |

P1 predice **categoría humana aprobada**, no probabilidad de recuperación. Gravedad y submotivos no se convierten en nuevas etiquetas supervisadas sin su propio protocolo. P2 predice pago completo confirmado de esa obligación dentro del horizonte, bajo gestión observada; no estima el efecto de contactar ni el éxito causal de un reintento.

**No admitidos en V1:** nombres, RUT, contactos, direcciones, credenciales, datos de tarjetas, identificadores externos o internos como predictores, textos libres para P2, estado final, fecha/importe del pago futuro, recuperación final o cantidad de reintentos posteriores. Tampoco familia humana revisada después del cálculo como predictor P2. Familia disponible en ese instante, antigüedad de suscripción y conteos históricos de 30/90 días quedan como candidatos futuros: requieren snapshots, cobertura histórica y pruebas propias antes de ampliar la lista blanca.

## P1: observaciones y revisión humana

`P1Observation` conserva contexto ML-03, UUID interno y relojes de evento/disponibilidad. El adaptador futuro debe aportar observaciones reales del flujo, no inventar una fecha de tráfico usando la creación de una etiqueta. `P1Review` representa revisiones ML-03, no resultados de reglas o predicciones.

`build_p1(..., as_of=..., review_history_complete=True)` exige historial íntegro, consecutivo y con relojes coherentes. Verifica aprobación posterior a propuesta de igual categoría y por otro actor. Selecciona la última revisión hasta el corte: propuesta corregida, abstención, rechazo o retiro invalidan la aprobación anterior. El adaptador debe leer el historial auténtico ML-03, incluyendo sus controles de gravedad/permisos; la función no autentica autores ni sustituye ese servicio.

La revisión puede ocurrir después del rechazo: es etiqueta, no predictor. Se conserva `label_available_at`; un futuro entrenamiento no podrá usarla antes de esa fecha. Repeticiones del mismo UUID se deduplican, versiones contradictorias fallan. Distintos eventos con la misma glosa se conservan como tráfico real; **no son ejemplos semánticamente independientes**. El contexto completo permite evaluar glosas no vistas aparte del tráfico temporal. Los excluidos se cuentan por observación: futura al corte, sin etiqueta o última revisión no aprobada.

## P2: episodios, relojes y etiqueta

Los adaptadores futuros deben producir `EvidenceEvent` inmutables y vinculados: rechazo, pago completo confirmado, parcial, reverso o ambiguo. `FULL_PAYMENT` significa obligación totalmente pagada y confirmada; no solicitud aceptada, liquidación estimada ni estado actual sin fecha. Se requieren UUID internos, cuenta/fuente y vínculo verificable a la misma obligación. Igual monto/fecha o misma suscripción no demuestran ese vínculo.

1. `t0` es el primer rechazo verificable. `calculated_at` es su primera disponibilidad comprobable: esta versión estudia solo el momento de primera detección. Si otro rechazo posterior se conoció antes, o hay empate ambiguo entre primeros rechazos, se excluye. No se usa `updated_at` como disponibilidad histórica ni se asigna medianoche a una fecha mensual.
2. El límite es `t0 + 30 × 24 horas` en UTC, inclusivo. El retraso de detección no reinicia el plazo. Detecciones al límite o posteriores no entran. Todos los instantes requieren zona y se normalizan a UTC; fechas sin precisión suficiente se representan como desconocidas y se excluyen.
3. Tanto positivos como negativos requieren horizonte completo al corte, origen del primer rechazo comprobado y una prueba `Coverage` por obligación/cuenta: intervalo continuo, fuentes completas, conciliación y disponibilidad de esa prueba antes del corte. Una sincronización exitosa o la máxima fecha de pago no constituye esa prueba.
4. **1:** un único pago completo confirmado, posterior al cálculo y hasta el límite, enlazado a la misma obligación y con igual importe/moneda. **0:** ventana completamente observable y conciliada sin ese pago. Pagos posteriores al límite no cambian el cero del objetivo a 30 días. La ausencia de datos no es cero.
5. Inmadurez, falta de cobertura/origen, reloj o vínculo, evidencia tardía, pagos parciales/reversos/ambiguos conocidos al corte, importes contradictorios, pagos completos múltiples o suscripciones incompatibles quedan excluidos. No se suman abonos ni se decide una política de neteo no aprobada. Para esta versión conservadora, parciales/reversos conocidos al corte excluyen la obligación incluso si fueron posteriores al horizonte; debe declararse al comparar cohortes y revisarse con negocio.
6. Pago ocurrido antes o al cálculo, aunque se detecte después, se excluye como población resuelta/ambigua; nunca se convierte en negativo. Esta selección retrospectiva limita extrapolar a todos los rechazos mostrados en vivo y debe cuantificarse antes de aceptar P2.

`label_available_at` es el máximo entre fin de horizonte, disponibilidad de cobertura y de hechos de esa ventana. Cada fuente/cuenta-obligación produce a lo sumo una fila. UUID de evento repetido se deduplica; contenido contradictorio o pruebas de cobertura incompatibles fallan en lugar de elegir la última fila. Un pago no se comparte entre episodios por coincidencia de suscripción. Las exclusiones cuentan **obligaciones**, no intentos; una obligación recibe un motivo primario según el orden de controles del módulo, no una lista exhaustiva de defectos.

Los indicadores de cobertura son declaraciones verificadas por el adaptador y el socio, no pruebas generadas por esta función. No marcar `complete`, `reconciled` o `history_complete` para superar un bloqueo sin evidencia independiente.

## Metadatos restringidos y separación temporal

UUID internos de observación, obligación, rechazo, suscripción, cobertura y autores; fuente; revisiones/versiones; `t0`, cálculo, límite y disponibilidad de etiqueta son metadatos de trazabilidad/agrupación. **No son anónimos ni entradas al modelo.** No se exportan en esta entrega; retención, permisos y seudonimización corresponden a ML-05. No agrupar personas por RUT/email ni inferir identidades entre proveedores.

`eligible_for_fit(row, fit_at=...)` comprueba únicamente cálculo anterior al ajuste y etiqueta disponible al ajustar. No entrena ni crea folds. ML-06 deberá separar entrenamiento/calibración/test por tiempo de cálculo, purgar ventanas solapadas por sus fechas reales y garantizar madurez/disponibilidad de etiquetas en cada corte. Transformadores, vocabulario, imputación y umbrales se ajustan solo en entrenamiento. Evaluar glosas no vistas para P1; para generalización a nuevas suscripciones, añadir grupos disjuntos cuando exista identidad verificable. No afirmar generalización a personas nuevas con ese agrupamiento.

## Correspondencia con datos actuales y entrega al socio

Core `charge_id`/identidades verificadas podrán sostener enlaces; `CoreCharge.latest_rejection_*` es estado más reciente, no historial de intentos. `CorePayment.occurred_at` requiere verificar su significado y precisión; `created_at`/`updated_at` no certifican disponibilidad histórica. `source_record_observations` puede ayudar a reconstruir captura, pero por sí solo no prueba cobertura completa ni cada intento. `charge_recoveries` usa una ventana operativa de cuatro días y no demuestra este objetivo a 30 días. Una fila mensual TCH puede no tener precisión suficiente. No hay adaptador aprobado que convierta automáticamente esas tablas a este contrato.

El socio debe, en su copia controlada:

1. Auditar por proveedor/cuenta/recurso la procedencia y precisión de los relojes, los vínculos y la cobertura. Distinguir estudio retrospectivo limitado de validación operativa punto en el tiempo.
2. Revisar política de primer episodio, población de primera detección, CLP, pagos completos/parciales/reversos y pagos previos al cálculo; aceptar o versionar cambios antes de usar los datos para seleccionar modelos.
3. Para P1, aportar historial ML-03 completo y observaciones saneadas. Para P2, aportar snapshots/eventos y pruebas reales de cobertura. No reconstruirlos de estados finales ni copiar datos personales aquí.
4. Ejecutar las pruebas funcionales de abajo y, tras implementar/autorizarse ML-05, preparar su dataset restringido con manifiesto de corte, versión, consulta, coberturas y exclusiones. Todavía no existen runners de extracción/exportación/entrenamiento para estos contratos; no se dan comandos ficticios.
5. Devolver agregados saneados por fuente/cuenta: observaciones/contextos, obligaciones/episodios, aprobadas/abstenciones, positivos/negativos maduros y exclusiones, retraso de detección/etiqueta, nulos y rangos temporales. Suprimir celdas pequeñas identificables; no compartir UUID/glosas individuales. Estos conteos no son métricas de precisión ni aprobación del modelo.

Para desglosar exclusiones por fuente/cuenta, invocar el constructor con el subconjunto de esa fuente; los resultados incluyen conteos agregados por motivo, no filas rechazadas con identificadores.

## Validación local

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_temporal_dataset.py tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml04 -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

Resultado: **236 pruebas puras pasan (40 nuevas de ML-04)**; Ruff completo sin errores. Cobertura funcional de fronteras temporales, disponibilidad, deduplicación, enlaces entre cuentas/obligaciones, madurez simétrica, nulos, monedas, pagos ambiguos, revisiones retiradas, listas blancas y entrada sin PII. `--noconftest` evita inicializadores de DB de la suite general: no se migró ni consultó QA/original. Las pruebas PostgreSQL de ML-03 no se repiten porque no cambió su persistencia. Sin frontend modificado, no procede build.

La muestra sintética prueba contratos, no viabilidad estadística, calidad del ETL ni representatividad. **Pendientes:** aceptación de política y datos reales por el socio, adaptadores/manifiesto/exportación ML-05, particiones y evaluación ML-06/07. Ningún modelo entrenado o activado. Trabajo solo local, sin skills ni publicación.
