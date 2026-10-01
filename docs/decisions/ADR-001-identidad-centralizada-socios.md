# ADR-001 — Identidad centralizada de socios

Date: 2026-09-30

Status: Accepted

## Context

VirtualPOS, Toku, Payku y TCH/Sheets/Excel pueden representar a una misma persona con identificadores y atributos personales incompletos o divergentes. El Core debe conservar la trazabilidad de cada fuente, evitar acoplarse a proveedores y permitir una ficha de socio transversal sin perder evidencia.

## Problem

RUT, email y telefono facilitan la comparacion, pero pueden estar ausentes, ser invalidos, cambiar, reutilizarse o compartirse. Usarlos como clave primaria o como regla de merge irreversible puede mezclar personas distintas. Mantener solamente registros aislados por proveedor impide una reporteria y analitica transversal confiable.

## Decision

CLIENTE tendra un identificador interno estable del proyecto, conceptualmente un UUID. RUT, email, telefono e identificadores de proveedores no son su clave primaria ni prueban por si solos un merge.

El modelo centralizado mantendra una relacion extensible de identidad externa entre CLIENTE, la fuente y el identificador externo de persona, con trazabilidad al registro de staging que la respalda. El nombre y esquema fisico de esa relacion se definiran durante el diseno tecnico; `EXTERNAL_IDENTITY` es solo un nombre conceptual.

La normalizacion, el matching, la deduplicacion y el merge son etapas diferentes. El sistema aplicara automaticamente solo normalizacion y la recuperacion de una identidad externa ya conocida. Toda vinculacion transversal nueva que dependa de atributos personales requerira revision manual durante la fase inicial.

## Identity model

- CLIENTE representa una persona o socio interno y usa un UUID estable.
- Una persona puede tener cero, una o varias identidades externas, incluso varias en un mismo proveedor.
- Una identidad externa de persona se identifica por `provider + external_id` dentro de su espacio de nombres. Si un proveedor reutiliza valores entre tipos de recurso, el tipo de identidad o recurso forma parte de ese espacio.
- Una identidad externa activa se vincula a un solo CLIENTE a la vez y conserva su `source_record`, fuente, identificador externo y evidencia de vinculacion.
- RUT, email y telefono son atributos personales y senales de comparacion; sus valores normalizados no sustituyen los valores observados ni son claves transversales unicas.
- SUSCRIPCION conserva su propio identificador externo y puede coexistir con varias suscripciones de la misma persona en una o varias plataformas.

## Matching policy

Normalizacion prepara comparaciones y no decide identidad:

- RUT: quitar separadores, normalizar digito verificador y validar su formato y checksum cuando corresponda.
- Email: recortar espacios y comparar sin distinguir mayusculas/minusculas; no modificar silenciosamente el valor de origen.
- Telefono: conservar valor de origen y producir una representacion normalizada con prefijo de pais cuando sea posible; la regla detallada para Chile queda para el diseno tecnico.

Niveles de evidencia:

- Nivel A, deterministico: una identidad externa `provider + external_id` ya vinculada al mismo registro de persona. Su reprocesamiento puede asociarse automaticamente al CLIENTE existente.
- Nivel B, fuerte: RUT valido e identico, o combinaciones coherentes como email y telefono normalizados. Genera una recomendacion de alta confianza, no un merge ni una vinculacion transversal automatica inicial.
- Nivel C, ambiguo: solo email, solo telefono, nombre similar o datos incompletos. Requiere revision manual.
- Nivel D, contradictorio o insuficiente: RUT distinto, identidad externa ya ligada a otro CLIENTE, senales incompatibles o falta de evidencia. No se vincula automaticamente y se registra para revision cuando corresponda.

Un RUT valido e identico con email distinto es evidencia fuerte, pero no autoriza por si solo un merge. RUT invalido o ausente no aporta evidencia deterministica. Email y telefono nunca son claves primarias ni reglas de merge automatico.

Los umbrales numericos, pesos de senales y cualquier scoring quedan `TBD` hasta contar con datos de calidad, muestras revisadas y una propuesta tecnica aprobada.

### Resolucion de casos requeridos

| Caso | Resolucion |
| --- | --- |
| 1. Mismo RUT valido, distinto email | Nivel B. Conservar ambos valores y enviar la asociacion entre fuentes a revision manual; no hacer merge automatico. |
| 2. Mismo email, RUT distinto | Nivel D. Tratar el conflicto de RUT como evidencia contradictoria y requerir revision manual. |
| 3. Mismo telefono, sin RUT ni email | Nivel C. No asociar automaticamente; el telefono puede compartirse o reasignarse. |
| 4. Mismo RUT y telefono, nombre diferente | Nivel B con atributo contradictorio. Requiere revision manual y conservar todos los valores observados. |
| 5. Sin RUT, mismo email y telefono | Nivel B. Recomendar revision, pero no hacer merge automatico en la politica inicial. |
| 6. Solo mismo nombre | Nivel C o evidencia insuficiente. No asociar automaticamente. |
| 7. Un CLIENTE tiene dos IDs de Toku | Permitido. Ambas identidades externas de Toku pueden vincularse al mismo CLIENTE tras evidencia deterministica o revision aprobada. |
| 8. Una persona tiene VirtualPOS, Payku y Toku con suscripciones simultaneas | Permitido. Las identidades confirmadas pueden vincularse a un CLIENTE; cada suscripcion de origen conserva independencia y trazabilidad. |
| 9. Un merge resulta incorrecto | Revertir el merge auditado, restaurar los vinculos de identidad previos y preservar la evidencia de merge y reversion. |

## Manual review

La arquitectura debe admitir una cola conceptual de revision de identidad. Una futura estructura, por ejemplo `IDENTITY_MATCH_REVIEW`, debe poder registrar los dos registros o candidatos, senales coincidentes y contradictorias, confianza o razon, estado, decision, fecha y actor humano o sistema.

Operadores autorizados pueden confirmar una vinculacion, rechazarla para impedir que se sugiera de nuevo, corregir una sugerencia automatica y solicitar o ejecutar la separacion de una consolidacion. Todas esas acciones requieren permisos y auditoria.

## Merge policy

Matching identifica una posible relacion; deduplicacion decide que hay evidencia suficiente para tratar dos representaciones como la misma entidad logica; merge consolida relaciones bajo una identidad operativa. Ninguna de estas definiciones implica borrar registros de staging ni sobrescribir los valores de origen.

No habra merge transversal automatico en la primera implementacion. Un merge requerira decision manual autorizada, evidencia registrada y una operacion reversible. La identidad externa y las suscripciones permanecen trazables a sus IDs y fuentes originales.

## Reversibility

Un merge debe registrar como minimo: identificadores de CLIENTE involucrados, identidades externas y relaciones afectadas antes y despues, razon y evidencia, decision de revision si existe, actor, fecha y estado. No se eliminaran fisicamente los CLIENTE, identidades externas ni source records al consolidar.

Revertir un merge debe restablecer las vinculaciones anteriores y conservar ambos eventos de auditoria. No se adopta event sourcing completo: un registro de evento de merge/reversion y el estado previo suficiente satisfacen este requisito conceptual.

## Source data conflicts

No se define una jerarquia fija entre Toku, VirtualPOS, Payku y TCH. La autoridad se evaluara por atributo, evidencia, fecha de actualizacion, validacion humana y contexto de la fuente.

Los valores divergentes de RUT, email, telefono, nombre u otros atributos no se reemplazan ni destruyen silenciosamente. El futuro modelo debe conservar el valor observado, su procedencia y fecha disponible; un valor centralizado actual, si se necesita, debe indicar su procedencia y poder corregirse mediante una accion auditada. El gobierno de retencion, rectificacion y exposicion de datos personales permanece `TBD`.

## Auditability

La trazabilidad existente de `source_records` se mantiene. Las futuras decisiones de matching, confirmacion, rechazo, merge, reversion y correccion manual deben registrar evidencia, origen, actor o sistema, fecha y resultado, sin almacenar secretos ni datos de tarjetas.

## Alternatives considered

### Alternative A: RUT as primary identifier

Simplifica cruces cuando el RUT existe y es valido, pero falla con ausencia, errores, personas juridicas, datos heredados y conflictos. No representa multiples IDs de proveedor ni permite resolver casos dudosos de forma reversible. Debilita la calidad de reporteria y analitica al convertir una senal en certeza.

### Alternative B: Email as primary identifier

Es facil de normalizar y esta disponible en algunas fuentes, pero puede cambiar, compartirse, reciclarse o faltar. No resuelve proveedores que no lo entregan y aumenta el riesgo de mezclar personas. Tiene baja reversibilidad si se usa como identidad base.

### Alternative C: Internal UUID plus external identities and matching

Separa la identidad interna de las senales y de las claves de proveedor, admite varias plataformas y suscripciones por persona, conserva trazabilidad y permite decisiones reversibles. Requiere una futura cola de revision, auditoria y trabajo de calidad de datos, pero protege la reporteria y las futuras predicciones de merges silenciosos.

### Alternative D: Record per provider without cross-platform identity

Preserva aislamiento y es simple de operar, pero duplica socios, impide una vista transversal fiable y limita reporteria, recuperacion y analitica. No resuelve el objetivo de centralizar personas provenientes de multiples plataformas.

## Consequences

- El Core futuro debe distinguir CLIENTE, identidad externa, atributos personales observados y decisiones de identidad.
- La clave idempotente actual de staging `(source, resource_type, external_id)` se conserva; no se reemplaza por RUT, email o telefono.
- La implementacion requerira un diseno fisico, migraciones nuevas, permisos para revision y pruebas de separacion/reversion antes de habilitar merges.
- Los reportes podran distinguir hechos por fuente de agregaciones por CLIENTE, evitando contar como certeza una sugerencia no confirmada.

## Risks

- Datos historicos incompletos o inconsistentes pueden producir muchas revisiones manuales.
- Un error de normalizacion o una regla demasiado permisiva puede aumentar falsos positivos.
- La exposicion de atributos personales exige minimizacion, permisos, retencion y rectificacion definidos antes de implementar interfaces de revision.
- Los historiales incompletos de VirtualPOS y Payku limitan la evidencia disponible para algunos casos.

## Open questions

- Definir el esquema fisico, nombres, restricciones y migracion de CLIENTE e identidades externas.
- Definir normalizacion tecnica de telefonos, manejo de RUT excepcionales y politica de calidad de datos.
- Definir umbrales, metricas y gobierno para evolucionar el matching asistido.
- Definir retencion, rectificacion, acceso y autoridad por atributo para datos personales.
- Definir la UX, permisos y procedimiento operativo de revision, merge y reversion.
