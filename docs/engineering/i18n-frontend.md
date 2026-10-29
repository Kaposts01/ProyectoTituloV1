# Textos en español del frontend (i18n)

Regla del usuario: TODO lo que ve el usuario va en español: títulos, descripciones, rótulos, mensajes y también los VALORES que llegan de la API o del proveedor (`Paid` se ve «Pagado», `FAILED` «Fallido», `ACTIVE` «Activa», `True` «Sí»). Origen del trabajo: auditoría `audit_i18n_frontend.md` (pasos 0 a 12 de texto; los pasos 13 a 19, que renombran identificadores, esperan las decisiones D32 a D36 del usuario y no están hechos).

## 1. Catálogo y función `label`

- `frontend/src/i18n/es.ts`: catálogo por dominio (solo datos). Dominios: `status`, `tchStatus`, `secondaryStatus`, `runStatus`, `phase`, `channel`, `resource`, `resourcePlural`, `field`, `recurringField`, `boolean`, `cardType`, `cardBrand`, `paymentMethodType`, `severity`, `documentType`, `frequency`, `personType`, `currency`.
- `frontend/src/i18n/label.ts`:
  - `label(domain, valor)`: texto en español. Ausente (`null`, `undefined`, `""`) da «Sin dato»; conocido da su traducción; **desconocido da «Desconocido (valor)»** y, solo en desarrollo y pruebas, un `console.warn` (una vez por dominio y valor, sin datos personales: los valores son estados y códigos).
  - `tryLabel(domain, valor)`: `undefined` si no se conoce (sin aviso). `labelOr(domain, valor, vacío)`: otro texto para el ausente. `normalizeKey`: sin tildes, minúsculas, `_` y `-` como espacio (misma normalización que `statusColors`).
- Claves: en los dominios de valores ya están normalizadas (`label.test.ts` lo exige), de modo que `ACTIVE`, `Active` y `active` comparten entrada. Los dominios de identificadores (`resource`, `resourcePlural`, `field`, `recurringField`) usan la clave de la API en minúsculas (`payment_method`).
- `billing/billingLabels.ts` y `billingErrors.ts` se conservan como dominio propio (el texto nunca viene del servidor); solo su fallback pasa a «Desconocido (valor)» (paso 10).
- El color de un estado sigue saliendo de `statusColors.ts` con el valor crudo; `label` solo traduce el texto. `STATUS_KEYWORDS` (antes privado) se exporta para que un test exija que cada raíz que colorea tenga entrada en el catálogo.

## 2. Excepciones documentadas

1. `technicalCode` de billing (etiquetas como `RuntimeError`) se muestra CRUDO bajo el rótulo «Código técnico».
2. `rejection_reason` (motivo de rechazo del proveedor) y los mensajes `msg` de las corridas (SSE) son texto libre del proveedor o del backend: se muestran sin traducir bajo el rótulo «Texto del proveedor».
3. Los elementos que muestran esos textos llevan el atributo `data-raw-text`; el guardián no los inspecciona.

Fuera de `label`: nombres propios y datos libres (nombre de rol, de plan, de cliente), marcas y siglas (VirtualPOS, Toku, Payku, TCH, RUT, CLP, UF, ETL).

## 3. Guardián

`frontend/src/i18n/catalog.guard.test.tsx` monta las vistas de caracterización con datos crudos en inglés y falla si en el texto visible aparece una palabra de `FORBIDDEN_EN` (`ACTIVE`, `PAID`, `FAILED`, `PENDING`, `True`, `False`, `Status`, `Email`…) como palabra completa, salvo dentro de `[data-raw-text]`. Las vistas se registran en `GUARDED_VIEWS` a medida que cada paso las traduce. `label.test.ts` comprueba que todo texto del catálogo está en español, que cada código conocido se traduce, que lo desconocido da «Desconocido (X)» y que cada raíz de `statusColors` tiene entrada.

## 4. Progreso por paso

| Paso | Contenido | Estado |
|---|---|---|
| 0 | `i18n/es.ts`, `label.ts`, tests y guardián | hecho |
| 1 | Rótulos estáticos en inglés: «Status» y «ID Sub» (fichas de cliente y plan), «Email» y «Mail» a «Correo electrónico» (columnas, filtros, formularios, ficha TCH), `renewalText` a Sí/No, opciones del cambio de estado de Toku («Activa — Activar»…). El valor que se envía a Toku (`ACTIVE`, `PAUSED`, `CANCELLED`) no cambia. | hecho |
| 10 | Billing: `statusLabel`, `typeLabel`, `eventLabel`, `platformLabel` (nueva, reemplaza `PLATFORM_LABELS[x] ?? x` en 4 vistas), `renewalStatusLabel` y `renewalPriorityLabel` devuelven «Desconocido (valor)» ante un código nuevo; el estado dentro del motivo de cierre de renovación pasa por `label("status")`; la etiqueta técnica («Código técnico: X») queda cruda y marcada con `data-raw-text`. | hecho |
| 4 | Barras de estado (`StatusBars`: leyenda y `title`) y leyendas de los gráficos apilados (`pivotByStatus`): `label("status")`. La clave de datos y el color siguen saliendo del valor crudo (`statusColor(raw)`), así que dos valores crudos que se traducen igual (p. ej. `ACTIVA` y `active`) aparecen como dos leyendas con el mismo texto. Se agrega «Sin estado» al catálogo (es el agrupador de estados nulos). | hecho |
| 5 | Estados en listas y fichas de VirtualPOS, Toku y Payku (~25 columnas «Estado», «Estado sec.», fichas de cliente, plan, suscripción y cargo, diálogo «Estado actual» de Toku, opciones del filtro de estado, listas consolidadas de clientes y suscripciones): `label("status")` y `label("secondaryStatus")`, vía `features/shared/display.ts` (`fieldValue`) en las fichas. Nuevo dominio `paymentType` VACÍO a propósito (ver «Valores sin significado conocido»). | hecho |
| 6 | Detalle de proveedor: `fieldValue` traduce booleanos (true/false/T/F, cualquier campo si es booleano de JSON), `frequency_type`, `currency`, `card_type`, `card_brand`, `payment_type_code` y `gateway`; `TokuPaymentMethodProfile` traduce tipo de medio, estado, pasarela, marca y tipo de tarjeta; tipo de persona del cliente de VirtualPOS (`Persona`/`Empresa`); `fieldLabel` de una clave sin rótulo devuelve «Campo (clave)» (antes `clave con espacios`). Se agregan ~25 rótulos de campo a `es.field` (los usados por `fieldLabel` como respaldo). Dominios `paymentType` y `gateway` VACÍOS a propósito. | hecho |
| 8 | TCH: `estado` de suscripciones y transacciones (`tchStatus`: Vigente, Eliminada, Aceptada, Rechazada), estado secundario (`secondaryStatus`) y estado del último ETL (`runStatus`) en lista, fichas y resumen. Las clases CSS siguen decidiéndose por el valor crudo (`=== "VIGENTE"`). Los campos de texto del Excel (tipo de mandato, origen, motivo de baja) son español del proveedor y no se tocan. | hecho |
| 7 | ETL, programador y sincronización: `EtlPanel` (estado, fase y botón «Sincronización de Toku…»), tarjetas por canal del dashboard general (estado de la última carga con `runStatus`, canal con `channel`, recursos con `resourcePlural`), `SchedulerPanel` (estados sin texto propio con `runStatus`, p. ej. «En cola», «Programado»; fase con `phaseText`; tipo de corrida con canales traducidos). El registro en vivo ahora es el componente `SseLogEntry`: fase y recurso traducidos y el `msg` va CRUDO bajo «Texto del proveedor» (`data-raw-text`); el mensaje de error de una corrida (`error_message`) recibe el mismo trato. Los cuatro estados habituales del programador conservan su vocabulario compacto (OK, Error, En curso, Parcial). Nuevos módulos `admin/schedulerLabels.ts` y `admin/SseLogEntry.tsx` (las funciones salen del panel para no sumar advertencias de lint). Las cifras del registro en vivo usan el formato `es-CL`. | hecho |
| 9 | Alertas y recuperador: la severidad de las alertas se ve «Alta», «Media», «Baja» (la clase CSS sigue usando el valor normalizado); el detalle de una alerta traduce el estado y el estado del último cobro; la tabla del recuperador traduce la cuenta (canal) y el resultado de la conciliación (nuevo dominio `reconcileResult`); el motivo de rechazo del proveedor va crudo, marcado con `data-raw-text` y la columna se titula «Motivo de rechazo (Texto del proveedor)». `rejection_code` es un código (p. ej. 51), no una palabra, y se muestra tal cual. `tipo`, `canal` y `detalle` de las alertas los redacta el backend en español y no se traducen. | hecho |
| 2 | Rótulo desacoplado de la lógica de filtro y orden: `TableColumn` gana `key` (identificador estable). `vpColumnFields` y la nueva tabla `columnFields` (Toku y Payku, que antes se buscaba comparando el rótulo con el de las opciones de filtro) se consultan por clave, y `StagingRecordsList` decide por `column.key`. Las claves conservan el texto que tenía el rótulo antes de traducir («Telefono», «F. Cancelacion», «Email», «Mail») porque `?orden=` de la URL las guarda; así los enlaces guardados siguen valiendo y la URL no cambia. Tests: tabla dorada capturada con el comportamiento anterior, relabelado de todas las columnas y un test estático que prohíbe `column.label` en la lógica. | hecho |
| 3 | Tildes y «Suscripción»: `fieldLabel`, `virtualPosClientFieldLabels`, `recurringFieldLabels`, `statusResourceLabels`, `resourceTitle` y `cardTypeText` salen ahora de `es.ts` (se eliminaron las tablas duplicadas; sus llamadores no cambian). Rótulos de columnas, filtros, fichas, métricas, menú y diálogos con tilde («Teléfono», «Renovación», «F. Cancelación», «Fecha límite», «Navegación principal»…) y «Suscripción/Suscripciones» en lugar de «Subscripción/Subscripciones». `cardTypeText` ahora dice «Tarjeta de crédito/débito/prepago». Las CLAVES de columna (`key`) no cambian. Guardián de ortografía: `i18n/spelling.guard.test.ts`. | hecho |
| 11 | Errores de red y de la API (`api.ts`): el `detail` en inglés que el backend ya emite (71 textos exactos, más 4 patrones con datos variables) se traduce con el dominio `apiDetail` y `i18n/apiErrors.ts`; los errores de validación de pydantic (422) se muestran por su `type` («Monto: es obligatorio») con el campo en español; `ApiError.code` expone el `detail.code` de los detalles estructurados y `apiDetailIs()` reemplaza la comparación del texto mostrado (antes `message === "Invalid RUT"`); 409 y 502 tienen texto genérico; `LoginScreen` y `AutomaticReport` dejan de mostrar el texto del servidor / `statusText` en inglés; una respuesta que no es JSON se ve en español. **Decisión de alcance:** un `detail` que NO está en el catálogo se muestra tal cual (el backend casi siempre lo redacta en español: «Suscripción no encontrada»), en vez de ocultarlo tras un texto genérico, que habría empeorado los mensajes útiles; los casos nuevos en inglés se agregan al catálogo. Pendiente de decisión del usuario si prefiere ocultar todo `detail` no catalogado. | hecho |
| 12 | Permisos: se confirmó que las descripciones del backend (`PERMISSIONS` en `app/services/rbac.py`) están TODAS en español y un test las vigila (lee el archivo del backend, sin tocarlo); `PermCheckboxes` muestra «Permiso (código)» si una descripción llega vacía; test de `groupPermissions` (nombres de grupo en español y orden). No hizo falta un dominio `permission`. | hecho |

## 5. Balance (pasos de texto 0 a 12)

Hechos los 13 pasos (0, 1, 10, 4, 5, 6, 8, 7, 9, 2, 3, 11, 12), un commit cada uno. Pendientes: pasos 13 a 19 (renombrar identificadores), en espera de las decisiones D32 a D36 del usuario; no se tocó ningún identificador.

### Valores crudos que no se pudieron mapear sin conocer su significado (el usuario los define)

- `payment_type_code` de VirtualPOS (p. ej. `VN`): dominio `paymentType` vacío; se ve «Desconocido (VN)».
- `gateway` de Toku: dominio `gateway` vacío; se ve «Desconocido (valor)».
- Claves de campo de payloads sin rótulo: se ven «Campo (clave)».
- Marcas de tarjeta, tipos de medio de pago y estados fuera del catálogo: «Desconocido (valor)».
- Los detalles de abonos (`deposits`) se muestran como JSON con claves en inglés.
- Expresiones cron sin traducción en el programador se muestran tal cual.
- `detail` del backend que no está en el catálogo se muestra tal cual (paso 11).
- `error_message` de una corrida recibe el mismo trato que `msg` (rótulo «Texto del proveedor»).
