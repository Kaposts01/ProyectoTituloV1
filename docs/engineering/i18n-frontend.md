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
