# ML-02: taxonomia y reglas deterministas

Fecha: 2026-11-24. Implementacion local, sin entrenamiento ni cambios de comportamiento en el CRM.

## Alcance y contrato

[`app/ml/taxonomy.py`](../../../app/ml/taxonomy.py) expone:

```python
classify_rejection(source: str, code: str | None = None, reason: str | None = None) -> Classification
```

Funcion pura: no consulta base o red, no lee configuracion/secretos, no arranca scheduler, no carga artefactos ni importa dependencias de entrenamiento. `app/ml/__init__.py` no inicia nada. No se conecto a API, ETL, recuperadores o Dashboard; los catalogos y formatos actuales no se modifican.

Entradas: fuentes `virtualpos`, `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch`; conservar la cuenta en la salida, sin inferirla desde otra fuente. Texto o nulo para codigo/glosa. Limites de fuente/codigo/glosa: 32/64/200 caracteres; el ultimo coincide con el limite del normalizador existente, para no truncar evidencia contradictoria silenciosamente. Una glosa mayor requiere preparacion revisada, no recortarla automaticamente para superar la validacion. Tipos invalidos/entradas excesivas producen excepciones genericas sin valores personales.

Salida inmutable, determinista y serializable con `dataclasses.asdict` + JSON:

| Campo | Significado |
|---|---|
| `source` | Fuente/cuenta validada; nulo si no se reconoce, sin devolver una fuente arbitraria. |
| `category` | FUNDS, LIMIT, TECH, EXPIRED, BLOCKED, INVALID, FRAUD, ISSUER; nulo si falta soporte o hay conflicto. |
| `subreason` | Motivo tecnico especifico; no fusiona bloqueo temporal, cuenta cerrada y mandato eliminado/revocado. |
| `severity` | Gravedad sustentada por la regla: temporal, permanente o desconocida. |
| `reported_severity` | Prefijo TE/PE/UE de Toku, incluso si su detalle no tiene mapeo. Es distinto de una gravedad inferida. |
| `state` | `classified`, `unmapped`, `missing`, `conflict`, `not_rejection`, `unsupported_source`. |
| `method`, `matched_rules` | `rule` o `unmapped` y referencias a reglas estaticas; no devuelve la glosa ni codigos desconocidos. |
| `restrictions`, `review_reasons` | Resguardos y causas de revision; no son permisos ni ordenes de cobro. |
| `review_required` | Revision de la clasificacion o restricciones detectadas. Falso no significa autorizado para actuar. |
| `confidence` | Siempre nulo: una regla no aporta una probabilidad calibrada. |
| `taxonomy_version`, `rules_version` | `reason-taxonomy-v1-draft` / `reason-rules-v1-draft`. Cambios semanticos futuros requieren nueva version. |

No existen en esta salida `recovery_probability`, `recommended_action` ni `recommended_retry_date`. Esas capacidades pertenecen a P2/ML-09 y no se simulan aqui.

## Precedencia y abstencion

1. Interpretar un codigo solo dentro de su proveedor. VP1/VP2 usan el mismo catalogo conservando cuenta; no reutilizar un numero de VP en Payku/TCH.
2. Reutilizar `VP_REJECTION_LABELS`, `lookup_toku_code`, `parse_toku_response_code`, `normalize_processor_message`, `payku_rejection_category` y los estados documentados de suscripcion Payku. Las claves de categorias Payku preexistentes se distinguen de un codigo bancario desconocido.
3. Comparar codigo y texto cuando ambos son interpretables. Familia, gravedad incompatibles o submotivos sensibles diferentes de bloqueo/limite generan `conflict`, categoria nula y prohibicion de reintento automatico. Conservar la union de restricciones aunque haya conflicto.
4. Si el codigo es conocido pero el texto no se interpreta, conservar el soporte del codigo y exigir revision; no afirmar que se comprobo consistencia. Prefijos Toku contradictorios, incluso SU con glosa de rechazo, tampoco se ignoran.
5. Textos de catalogo ambiguos no identifican una causa especifica: «Tarjeta rechazada» de Toku no permite deducir por si sola tarjeta robada. No se usan coincidencias por palabras sueltas.
6. Las frases semanticas exactas, normalizadas en acentos/mayusculas/puntuacion y mediante el normalizador existente, son reglas de texto **provisionales**. Se marcan para revision; en TCH se añade validacion de dominio pendiente. No se invento un catalogo de codigos bancarios TCH ni un mapeo universal ISO 8583. Un `[51]` aislado no basta para clasificar.
7. Codigo desconocido con glosa exacta reconocida puede sostener una familia orientativa, pero conserva aviso `unmapped_code`. Ausencia, desconocido y exito quedan separados; `ISSUER` no es un fallback.

Un codigo reconocido puede no encajar en las ocho familias: VP -10/-1001/-1018, Toku 2106/9999 y varios mensajes Payku conservan submotivo/procedencia pero categoria nula. Los mensajes Payku de reintentar o error de tasa no dicen por si solos el motivo financiero. La referencia de exito Toku 0000 devuelve `not_rejection`, sin forzar revision humana si no hay otra contradiccion.

## Restricciones y privacidad

Los limites de reintento VP/Toku y el estado Payku `maximum attempt limit` conservan `retry_limit`; PAC eliminado/mandato revocado conserva `mandate_inactive`, y cuenta cerrada `account_closed`. Instrumento inutilizable, señales de seguridad y estado no pendiente tambien llevan resguardos. Los casos restringidos o sin clasificacion incluyen `no_automatic_retry`.

La familia tecnica FRAUD agrupa señales de seguridad/verificacion, **no acredita fraude de la persona**. Ninguna categoria o gravedad autoriza reintentos, actualizacion de tarjetas, contactos o links; el motor futuro debera verificar estado actual, permisos, mandato, restricciones y banderas WR.

La salida no copia codigo/glosa crudos, nombres, contactos o ejemplos individuales. Esta precaucion no reemplaza saneamiento de entradas, retencion o control de acceso de los datasets futuros. No se implementaron etiquetado manual, evaluacion de riesgo personal ni ejecucion de politicas de accion.

## Validacion y entrega al socio

Pruebas escritas antes del modulo: la primera corrida fallo por ausencia de `app.ml`. La implementacion se verifico con ejemplos sinteticos de las ocho familias y todos los codigos actuales VP/Toku, mensajes Payku, limites, mandatos, ambigüedad, contradicciones, tipos, privacidad, determinismo e importacion sin runtime/entrenamiento. Se añaden regresiones de catalogos/formatos actuales y del auditor.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_taxonomy.py tests/test_toku_rejection_codes.py tests/test_rejection_format.py scripts/ml/tests/test_audit_readiness.py --noconftest --basetemp=.local/pytest-ml02-repeat -q
.venv/Scripts/ruff.exe check app tests alembic scripts
```

Resultado: **169 pruebas en cuatro archivos pasan; Ruff completo sin errores.** `--noconftest` omite exclusivamente los inicializadores de DB/app de la suite general; estas pruebas son puras y no crean ni migran bases. No se consulta QA ni se requiere tener el historico completo para desarrollar ML-02. No procede compilar frontend porque no cambia.

El socio debera revisar los mapeos de negocio, frases reales, cobertura, conflictos y abstenciones en sus datos segun [VALIDACION-SOCIO.md](VALIDACION-SOCIO.md). Pasar pruebas sinteticas no demuestra precision sobre datos reales ni acepta ADR-002 o activa el motor. El siguiente lote es ML-03: anotacion contextual y revisiones, previa solicitud; no se ejecuta automaticamente.
