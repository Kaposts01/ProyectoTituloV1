# ML-14: medición prospectiva

2026-11-25. **Preparación implementada exclusivamente con datos sintéticos, apagada por defecto.** No hay medición operativa real, entrenamiento, carga de modelos ni estimación causal. El socio validará con sus datos completos; ADR-002 sigue Proposed.

## Qué se entrega

- `app/ml/prospective.py`: protocolo estricto, reconstrucción temporal y agregados descriptivos.
- `app/services/ml_prospective.py`: registro interno transaccional de protocolo y eventos sintéticos en PostgreSQL, usando sesiones propias. No es una API de autenticación.
- `app/models/ml_prospective.py` y nueva migración `20261125_0087`: dos tablas independientes del Core, protocolo inmutable e historial ordenado que solo admite agregar eventos. Las migraciones anteriores no se modifican.
- `scripts/ml/measure_prospective.py`: plantilla e informe privado firmado, offline y sin conexión a bases.

No se instrumenta automáticamente el Recuperador, no se agregan rutas HTTP, permisos, cron, banderas globales o cambios visuales. No se ejecutan gestiones ni se cambia el registro activo de artefactos. La persistencia es preparación técnica, no un piloto operativo habilitado.

## Registrar antes de observar resultados

Un estudio fija una cuenta concreta (`virtualpos1`, `virtualpos2`, `toku`, `payku` o `tch`), recurso (`charge`, `payment` o `transaction`), cierre de inscripción, horizonte fijo de **30 días** y criterios de soporte/cobertura. No se mezclan canales ni recursos. El propósito admitido es `synthetic`; diseño `observational_process_pilot`.

El protocolo se registra antes de inscribir casos. Incluye referencia `capture_frame_sha256` al marco de captura: población, fuentes, exclusiones, calendario y responsable. Se deben registrar todos los casos examinados, elegibles o no, incluidos los que nunca reciben recomendación. El sistema detecta duplicación de caso/obligación dentro del estudio; **no demuestra que se haya capturado toda la población**. El socio debe conciliarla con una fuente independiente y documentar omisiones. No deduplicar personas por RUT, correo o teléfono ni asumir identidad centralizada resuelta.

Inscripción: estado rechazado, mandato activo, límite de reintento no alcanzado, enlaces y conciliación verificados, comprobación vigente. Un dato desconocido o no vigente conserva el caso como no elegible. Las comprobaciones no ejecutan ni autorizan reintentos. Los estados fuera del vocabulario se deben mapear mediante revisión, sin inventar equivalencias.

`registered_at` y `recorded_at` proceden del reloj de PostgreSQL. `occurred_at` declara cuándo ocurrió el hecho; nunca puede ser posterior al registro del evento o anterior al protocolo. La inscripción debe registrarse dentro del presupuesto de captura (`maximum_state_age_seconds`, borrador 3.600 s). Así no se admite cargar retrospectivamente casos tras conocer sus resultados y llamarlo captura prospectiva. Eventos posteriores pueden llegar tarde: solo aparecerán en informes cuyo corte alcance su registro efectivo.

Los valores iniciales (30 resultados maduros verificados, 20 unidades, cobertura 80 %, vigencia 3.600 s) son **borradores de ingeniería**, no tamaño muestral calculado ni metas de negocio. Antes de un estudio real, acordar criterios/costos con el responsable. `criteria_status=agreed` exige referencia a revisión; un hash no prueba por sí solo aprobación auténtica. El protocolo no cambia: nuevas reglas requieren otro estudio y marco explícito para evitar reinscribir selectivamente las mismas obligaciones.

## Hechos separados

| Evento | Qué significa | Qué no acredita |
|---|---|---|
| `enrolled` | Caso examinado, obligación/unidad seudonimizadas y comprobaciones de ingreso. | Persona única o población completa. |
| `exposed` | Presentación de recomendación: IDs de recomendación, entrada, bundle, contenido, corte y display. | Que el ejecutivo la entendió, aceptó o actuó. |
| `decision` | Derivar a flujo existente, diferir, descartar o pedir revisión; vínculo opcional a exposición del mismo caso. | Ejecución o permiso de cobrar. |
| `outcome` | Evaluación de la misma obligación: pago neto completo, impago, parcial, reversa o desconocido. | Resultado causado por la recomendación. |

No registrar exposición al calcular, precargar o simplemente descargar resultados. La futura interfaz deberá confirmar presentación efectiva y generar un `display_id` estable para esa presentación; repetirlo se rechaza, otra presentación cuenta como otra impresión del mismo caso. No hay enlace automático a filas reales del piloto: el socio debe demostrar trazabilidad Core y cuenta/recurso.

Cada decisión vuelve a comprobar estado y restricciones. Derivar exige elegibilidad inicial y actual; pago, baja, estado desconocido o conciliación no verificada impiden esa decisión. Los mecanismos WR existentes seguirían siendo responsables de autorización y ejecución. Aquí `workflow_execution_confirmed=false` y `execution_authorized=false` siempre.

Decisiones y resultados se corrigen agregando un evento con `supersedes` apuntando a su última revisión. Nunca se reemplaza evidencia. Una reversa posterior al horizonte no cambia por sí sola el resultado a 30 días; corregirlo solo si demuestra que la evaluación original a ese horizonte era incorrecta. Los hashes de evidencia remiten a respaldo privado que debe auditar el socio.

## Horizonte y denominadores

El reloj comienza en la inscripción, **no en la exposición o aceptación**, para no favorecer casos que debieron permanecer disponibles hasta recibir recomendación. Todos los elegibles, expuestos o no, integran el denominador de seguimiento.

- Casos examinados, elegibles/no elegibles, expuestos distintos, impresiones y eventos de decisión se informan por separado. `latest_decisions` cuenta la última decisión de todos los examinados; las coberturas de exposición/decisión usan solo elegibles.
- Casos elegibles con menos de 30 días permanecen inmaduros, incluso si ya pagaron. No entran como positivos tempranos ni como negativos.
- A 30 días, exigir evaluación exactamente al horizonte, evidencia y enlace verificados y cobertura completa. Un negativo no puede cerrarse antes. Pago positivo exige fecha dentro del horizonte y estado de pago neto completo de esa obligación.
- Seguimiento ausente, evaluación incompleta, parcial, reversa o desconocido quedan como exclusiones explicadas, nunca impagos implícitos. No se calcula recuperación monetaria: este contrato mide obligaciones, no pesos.
- `observed_recovery_rate = pagos verificados / resultados maduros verificados`; su denominador explícito es `verified_mature_outcomes`. `followup_coverage = verificados / elegibles maduros` evita ocultar datos faltantes. Se muestran conteos de toda la cohorte y unidades distintas entre maduros y verificados.
- `mature_recovery_bounds` muestra sensibilidad extrema entre elegibles maduros: límite inferior suponiendo ningún pago en casos no verificables y superior suponiendo pago en todos. **No es un intervalo de confianza** ni corrige sesgo de selección.

Falta de soporte, unidades verificadas o cobertura produce `insufficient_followup`; criterios no acordados, `criteria_pending`; en otro caso, `descriptive_only`. Ninguno significa eficacia o modelo validado. Una unidad repetida no equivale a observaciones independientes; el significado del seudónimo de unidad requiere auditoría.

No se compara expuestos contra no expuestos como si fueran grupos intercambiables. `causal_effect=null` y `causal_comparison=null`: no hay lift, prueba de significancia, ROI, control aleatorio ni inferencia causal. Para medir impacto, acordar antes población/unidad de asignación, control o despliegue escalonado, contaminación entre ejecutivos, potencia/tamaño, pérdidas de seguimiento, ética y plan de análisis. Los históricos completos del socio sirven para viabilidad; el impacto necesita observación futura bajo ese diseño.

## Integridad, privacidad y límites

Registro ordenado por estudio, bloqueo de fila y revisión esperada evitan dos ganadores concurrentes. `request_id` permite repetir exactamente una solicitud sin duplicarla; reutilización con otro contenido se rechaza. Cada evento enlaza hash anterior y protocolo. Evento, cabecera y auditoría constituyen el mismo registro transaccional: un fallo revierte todo.

Triggers PostgreSQL rechazan UPDATE/DELETE de eventos/protocolo, inconsistencias de columnas/envelope y cabeceras sin historial completo. Downgrade rechaza estudios existentes. Esto no protege frente a un administrador capaz de deshabilitar triggers o TRUNCATE: los permisos mínimos y custodia operativa se revisarán antes de producción. Hashes no son firmas de identidad; las validaciones semánticas pertenecen al servicio y se repiten al reconstruir informes.

Servicios desactivados con `enabled=False`. Para pruebas exigen `enabled=True`, `synthetic=True`, base descartable `*_test` y usuario activo. `fixture_clock` existe solo detrás de esas guardas para simular el paso de treinta días. **No es un parámetro HTTP ni se debe exponer a usuarios.** Un futuro adaptador debe derivar actor de sesión autenticada y aplicar permisos de estudio/cuenta/recurso; no confiar en IDs enviados por el cliente. No se ofrece ingestión operativa en esta entrega.

Límite de 2.000 eventos por estudio y 8 MB por entrada CLI; es un piloto acotado, no una prueba de carga. Al alcanzar el límite detener captura y revisar capacidad, sin fraccionar selectivamente la cohorte para lograr soporte. Exportación interna `{protocol, events}` mediante `export_study` debe guardarse con las protecciones ML-05. Contiene UUID de actores y tokens seudonimizados, por lo que sigue siendo restringida. No incluir nombres, RUT, contactos, glosas, PAN, CVV o claves; no usar SHA simple de identificadores personales como anonimización.

El informe solo contiene agregados y referencias, sin listas de casos/actores. HMAC con dominio propio verifica integridad bajo custodia de clave, no veracidad del dato o identidad de revisor. Conserva hash/revisión del ledger exportado y corte; una exportación posterior puede cambiar el hash aunque los agregados históricos sigan iguales. Guardar la revisión privada original para reproducción exacta. Retención, respaldo, control multiusuario y celdas pequeñas deben definirse antes de uso real.

## Uso y comprobación

Precondiciones: directorio privado ML-05 excluido y clave existente custodiada; no regenerar una clave en uso. Rutas relativas a `.local/ml-private`. La plantilla está incompleta: **no inscribe un estudio ni fabrica registros reales**. La entrada se exporta desde el arnés sintético mediante el servicio interno; no se aceptan conexiones a QA/original desde el CLI.

~~~powershell
.venv/Scripts/python.exe -m scripts.ml.measure_prospective template --destination prospective/protocol-draft.json
.venv/Scripts/python.exe -m scripts.ml.measure_prospective report --synthetic --input prospective/ledger.json --destination prospective/report.json --as-of 2026-11-25T12:00:00Z
.venv/Scripts/python.exe -m scripts.ml.measure_prospective verify --report prospective/report.json
~~~

`--key-file` selecciona una clave relativa privada alternativa. No sobrescribe archivos ni admite cortes futuros; mensajes fijos sin datos/secretos, código 2 en rechazo. `verify` autentica versión/firma/alcance; volver a ejecutar `report` desde el ledger original reproduce el contenido. Preparar un informe no registra una gestión.

Pruebas puras con eventos escritos a mano y PostgreSQL nativo en **crm_ml_registry_test**: madurez, denominador no expuesto, inscripciones tardías, cobertura, correcciones/cortes, referencias, firmas, idempotencia, concurrencia, rollback atómico, triggers, metadata y downgrade protegido. Nueva 0087 aplicada exclusivamente en esa base descartable; QA sigue en 0082 y original intacta. Ruff y CLI Windows con ACL privadas/HMAC/rechazo de sobrescritura. Sin cambios frontend; deuda QA-ML12-01 permanece, no se certifica la suite global ni producción.

Evidencia: **46 pruebas nuevas (31 puras y 15 PostgreSQL)**; con 428 regresiones puras y 184 PG/API/ETL/permisos previas, **658 pruebas distintas aprobadas**. Corrida amplia nativa: 198 aprobadas; tras ajustar idempotencia posterior al cierre y añadir concurrencia de la misma solicitud, corrida focalizada final: 15 aprobadas. Puras: 408 aprobadas y corrida final de 82, con 31 compartidas, para 459 distintas. Advertencia existente de Starlette/TestClient sobre HTTPX; no se cambian dependencias. No se construye ni carga un estimador para estas comprobaciones.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_prospective.py --noconftest --basetemp=.local/pytest-ml14-pure -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Para pruebas nativas, configurar el entorno de test según `tests/conftest.py` con destino descartable **crm_ml_registry_test** en loopback:5433 y configuración sintética; ejecutar `tests/test_ml_prospective_ledger.py` sin `--noconftest`. El inicializador aplica head y recrea solo la base guardada. No ejecutar migraciones con `.env` original ni adaptar estas guardas para apuntar a QA.

El socio debe validar completitud de captura, identidad de obligación/unidad, conciliación neta, relojes, revisiones y permisos con sus datos completos. Después corresponde acordar e instrumentar una captura futura autenticada, sin activar modelos o cobros de forma automática. Los resultados actuales son pruebas de ingeniería sintéticas, no resultados de negocio.
