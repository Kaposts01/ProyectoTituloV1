# ML-03: anotación contextual y revisiones

Entrega local del 2026-11-24. **Implementación funcional con datos sintéticos; anotación y validación de dominio con el socio pendientes.** No hay modelo entrenado, nuevas rutas API, pantallas, ejecución automática ni cambios en indicadores. ADR-002 conserva estado Proposed.

## Qué se conserva y por qué

`rejection_reason_labels` representa un contexto de vocabulario, no un rechazo individual ni una persona. Su clave única incluye fuente/cuenta (VirtualPOS 1 y 2 separadas), recurso, procesador/banco, código informado, código entre corchetes, texto normalizado y versiones de normalización/taxonomía. Todos esos campos son no nulos; ausencia de código se representa con cadena vacía. Igual texto en otro banco, cuenta, recurso o código no comparte etiqueta automáticamente.

Se admiten `charge`, `payment`, `transaction` y `subscription_state`. `processor` es un identificador controlado de hasta 40 caracteres, por ejemplo `bank-12`, `psp` o `unresolved`; estos ejemplos no definen equivalencias entre proveedores. Antes de anotar datos reales, el socio debe acordar el registro de identificadores de procesador con el contrato de cada fuente. `unresolved` admite propuestas pero bloquea aprobaciones. Resolverlo crea un contexto nuevo, sin cambiar el anterior. No se fusionan cuentas o procesadores por intuición.

El contexto es inmutable. Cada decisión agrega una fila a `rejection_reason_label_revisions`, con autor activo, hora UTC, UUID de solicitud, número consecutivo, decisión, categoría, gravedad y motivo controlado. La base impide actualizar/eliminar ambas tablas y bloquea huecos de revisión, autoaprobaciones y motivos incompatibles. Un administrador con privilegios para desactivar triggers o truncar tablas sigue pudiendo alterar la base: esto no es un archivo invulnerable al propietario de PostgreSQL.

La normalización conserva mayúsculas, acentos y puntuación; no realiza equivalencias semánticas. CSV exige texto ya normalizado y códigos separados. Cambiar el normalizador exige revisar/incrementar su versión y probar compatibilidad, conservando los contextos anteriores.

No se modifica Core, staging, catálogos de proveedor o ML-02. No se almacenan identificadores de socios/cobros ni glosas originales.

## Flujo de revisión

1. Sanea y revisa privadamente una glosa genérica, confirma privacidad y registra una propuesta (`draft`). Una propuesta puede quedar sin categoría; las reglas ML-02 nunca se convierten por sí solas en verdad de entrenamiento.
2. Una segunda persona puede aprobar exactamente categoría/gravedad propuestas (`approved`), rechazar por conflicto (`rejected`) o abstenerse por evidencia insuficiente/conflictiva (`abstained`). Rechazo y abstención conservan categoría nula y gravedad desconocida.
3. Para cambiar una etiqueta, agrega otra propuesta; requiere nueva aprobación independiente. Una revisión no puede aprobar directamente una categoría distinta de la propuesta.
4. Retira una propuesta o aprobación mediante `withdrawn`. El estado vigente es **la última revisión**, nunca la última aprobación histórica. Reabrir un caso retirado, rechazado o con abstención exige nueva propuesta.

Las categorías y gravedad usan las versiones actuales de ML-02. Una aprobación humana bajo taxonomía borrador no acepta esa taxonomía para producción ni autoriza acciones sobre pagos. Versiones nuevas requieren adaptar explícitamente el contrato; no se reetiquetan registros históricos en silencio.

## Privacidad y archivos CSV

`prepare_context()` elimina fechas/horas y separa el código entre corchetes con el normalizador existente. **Esto no anonimiza.** Antes de llamarlo, una persona debe eliminar nombres y cualquier dato personal o de pago. Se exige `privacy_reviewed=True`; el sistema conserva quién registra esa revisión. Controles conservadores bloquean correos, URL, dígitos residuales, controles invisibles, credenciales con valor y prefijos de fórmulas; un código separado puede ser numérico acotado. La detección automática no reconoce todos los nombres o secretos: nunca importar glosas crudas por haber pasado una expresión regular.

`write_requests_csv()` y `read_requests_csv()` exportan/importan **solicitudes de revisión**, con cabecera fija, contexto completo, versiones, UUID, revisión esperada, decisión y motivo. Límite: 1.000 filas y 1 MB de entrada UTF-8. Se valida todo el archivo antes de escribir. Los errores no copian los valores. Un archivo de propuestas y otro de revisión se aplican con autores diferentes.

El archivo no contiene autor ni puede suplantarlo: `apply_review_batch(session, actor_id=..., requests=...)` recibe un usuario confiable del llamador. No es un respaldo del historial ni restaura autoría entre entornos. No basta editar una columna para inventar un segundo revisor. No guardar CSV de datos reales en Git, logs o documentación.

El servicio no hace `commit`: la transacción pertenece al llamador. Cada lote usa un savepoint y exige sesión sin cambios ORM pendientes. Cualquier conflicto revierte el lote; no confirma trabajo ajeno. La revisión esperada evita sobrescribir decisiones recientes; repetir el mismo UUID/payload/autor devuelve el evento original, incluso después de nuevas revisiones. Reutilizarlo con otro contenido falla. Bloqueo por contexto y restricciones protegen carreras. Lotes concurrentes solapados deben mantener orden consistente o reintentar la transacción completa ante deadlock; no se promete ausencia de deadlocks ni se reintenta automáticamente.

## Integración y validación

Código: `app/ml/annotation_contract.py`, `app/models/rejection_annotation.py` y `app/services/rejection_annotations.py`. Migración nueva `20261124_0083`, importada en metadata Alembic, crea dos tablas y triggers. No cambia migraciones aplicadas. Downgrade con cualquier contexto existente se bloquea para conservar el historial.

**La migración solo se aplicó a `crm_ml_annotations_test` en loopback:5433**, mediante la guarda de pruebas. QA permanece en `20261118_0082`; original sin cambios. No ejecutar upgrade sobre ellas como parte de esta entrega. En ML-11 se deberán vincular autor y permisos a la sesión autenticada, autorizar contexto/canal y proteger mutaciones; esta biblioteca interna no sustituye esos controles y no expone importaciones por HTTP/CLI.

Pruebas reproducibles, desde la raíz:

```powershell
# Contratos y regresiones puras: no inicializan base ni app.
.venv/Scripts/python.exe -m pytest tests/test_ml_annotation_contract.py tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml03-pure -q

# Solo con TEST_DATABASE_URL apuntando a una base PostgreSQL DESCARTABLE *_test,
# nunca QA/original. conftest elimina public y aplica toda la cadena de migraciones.
# El entorno de pruebas debe resolver esa misma URL, con scheduler/escrituras apagados.
.venv/Scripts/python.exe -m pytest tests/test_ml_annotations.py --basetemp=.local/pytest-ml03-db -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

Resultado conjunto: **209 pruebas pasan**, incluidos contratos, CSV, privacidad, regresiones ML-02, migración completa, comparación de metadata afectada, restricciones PostgreSQL, rollback, replay, downgrade protegido y carrera entre revisores. Se emplearon credenciales ficticias de proveedores, sin llamar a sus API. No se requiere build frontend porque no cambió.

El socio revisará glosas reales saneadas en su entorno: cobertura por cuenta/procesador/recurso, desacuerdos, abstenciones, versiones y consistencia de severidad. Empezar por combinaciones distintas, sin asumir que diez textos normalizados TCH sean diez contextos ni fijar una cuota de 450 etiquetas. No se anotaron glosas reales de QA ni se midió precisión estadística. Los datos permanecen con el socio; se comparten únicamente agregados saneados según [el protocolo](VALIDACION-SOCIO.md). ML-04 y activación operativa quedan para solicitudes posteriores.
