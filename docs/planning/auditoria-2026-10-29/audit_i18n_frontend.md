# Auditoría i18n del frontend (solo lectura) - CRM SynkmetriX

Alcance: `frontend/src` (162 archivos; ~13.800 líneas no-test). Método: lectura de `billingLabels.ts`, `statusColors.ts`, `kpis.ts`, `constants.ts`, `virtualpos/constants.ts`, `columns.ts`, `exportMapping.ts`, `utils.ts`, `billingErrors.ts`, vistas de dashboard/TCH/proveedor, más escáneres en el scratchpad (`scan_en.py`, `tokens.py`, `es_ids.py`, `classify.py`; salidas `en_candidates.txt`, `es_ids_by_file.json`). Los conteos son por heurística (cota razonable, no exacta); se indica dónde hay ruido.

## Hallazgo general
El texto estático ya es casi todo español: 0 `aria-label`/`title`/`placeholder`/`alt` en inglés (96 atributos revisados). El problema está en (1) VALORES crudos de la API/proveedor que se pintan tal cual, (2) un puñado de rótulos en inglés, (3) acentos faltantes y ortografía inconsistente, y (4) identificadores en español concentrados en TCH. Existe un modelo bueno que replicar: `billing/billingLabels.ts` + `billingErrors.ts` (tablas locales, el texto nunca viene del servidor).

---
## A. INVENTARIO DE TEXTO VISIBLE

### A.1 Rótulos estáticos en inglés (≈ 14 sitios reales)
| Archivo:línea | Texto | Corrección |
|---|---|---|
| `virtualpos/ClientDetailView.tsx:70` | columna «Status» | «Estado» |
| `virtualpos/PlanDetailView.tsx:57` | columna «Status» | «Estado» |
| `shared/utils.ts:159-160` (`renewalText`) | «True» / «False» (se muestra en detalle) | «Sí» / «No» |
| `provider/ProviderWriteDialogs.tsx:54-56` | `<option>` «ACTIVE — Activar», «PAUSED — Pausar», «CANCELLED — Cancelar» | «Activa», «Pausada», «Cancelada» (value sigue siendo el código de Toku) |
| `virtualpos/columns.ts:36,185`, `virtualpos/constants.ts:40,127,141`, `tch/TchContent.tsx:174` | «Email» (6) | «Correo electrónico» (ya se usa en otros 4 sitios; unificar) |
| `ClientDetailView` | «ID Sub» | «ID suscripción» |
| `StatusBars.tsx` / `ChannelChart.tsx:220` | «Total» (válido en español; sin cambio) | - |
Falsos positivos descartados del escáner (107 candidatos -> ~14 reales): nombres de clase CSS, «Roles», «No aplica», «Error», marcas (VirtualPOS, Toku, Payku, TCH, 3D Secure, Gateway).

### A.2 Ortografía/acentos en español (calidad; ≈ 70 sitios)
- Sin tilde en rótulos: `fieldLabels` en `shared/utils.ts` (~35: «Telefono», «Descripcion», «Genero», «Direccion», «Region», «Pais», «Codigo postal», «Renovacion», «Metodo de pago», «Dias de prueba», «Fecha limite»…), `virtualPosClientFieldLabels` y `recurringFieldLabels` (`virtualpos/constants.ts`: «Correo electronico», «Dia de cobro», «Maximo de facturas activas»…), `columns.ts` («Telefono», «Renovacion», «F. Cancelacion»), `cardTypeText` («Tarjeta Credito/Debito»).
- «Subscripción/Subscripciones» (anglicismo, 29 sitios visibles: `virtualpos/constants.ts`, `columns.ts`, `ClientDetailView`, filtros) frente a «Suscripción» (correcto, ya usado en 27+). Unificar a «Suscripción».
- ATENCIÓN (acoplamiento): `virtualpos/constants.ts` `vpColumnFields` y `filterFieldForColumn` usan el TEXTO del rótulo como clave de lógica («Telefono», «F. Cancelacion», «RUT cliente»). Cambiar rótulos (acentos) rompe filtros de columna si no se desacopla primero (usar `key` en `TableColumn`).

### A.3 VALORES CRUDOS renderizados sin traducir (sitios de renderizado)
Clave: valor -> dónde se pinta. «Cat.» = dominio de catálogo propuesto.
| # | Sitio | Valor crudo | Cat. |
|---|---|---|---|
| 1 | `dashboard/StatusBars.tsx:42,56` (leyenda y `title`) | `item.status` de cualquier canal (`ACTIVA`, `ACTIVE`, `active`, `PAID`, `success`, `pagado`…) | `status` |
| 2 | `components/chartRows.ts:40` (`statusStackedChart`, leyendas/tooltips de todos los gráficos apilados) | `label: s` = estado crudo | `status` |
| 3 | `virtualpos/columns.ts` (≈14 columnas «Estado»: 39,57,72,82,102,136,153,157,162,168,174,192,200,210), `ClientDetailView` 70/90/105/108, `PlanDetailView:57`, `SubscriptionDetailView` 119/136, Charge/PaymentDetailView | `text(payload.status)`, `order.status`, `payment_type_code` (`VN`), `secondary_status` | `status`, `paymentType` |
| 4 | `provider/ProviderWriteDialogs.tsx:47` | «Estado actual: ACTIVE/active» (Toku) | `status` |
| 5 | `provider/ProviderRecordDetailView.tsx:51-52,45` + `text()` genérico | todo campo del payload tal cual (booleanos, enums, `card_brand`, `frequency_type: monthly`, `currency`, `is_active: true`) | `field values` |
| 6 | `toku/TokuPaymentMethodProfile.tsx:21,28-33` | `method.type`, `method.status`, `gateway`, `card_brand`, `card_type` (`cardTypeText` solo cubre TC/TD/TP/TPE/PREPAGO) | `paymentMethod`, `cardType` |
| 7 | `dashboard/EtlPanel.tsx:33,36` | `lastEtlRun.status` (`completed/failed/running`), `phase` (`sync_virtualpos`…) | `runStatus`, `phase` |
| 8 | `dashboard/GeneralSummaryContent.tsx:110,111,119` | `source.toUpperCase()`, `lastSync.status`, claves de recursos `client: 12 · subscription: 3` | `channel`, `runStatus`, `resource` |
| 9 | `tch/TchContent.tsx:98,181,189,232,233,276` | `ultimo_etl.status`; `estado` TCH (`VIGENTE`, `ELIMINADA`, `ACEPTADA`, `RECHAZADA`); `secondary_status` (`cobrable/incobrable/inactiva/nunca_cobrado`) | `tchStatus`, `secondaryStatus`, `runStatus` |
| 10 | `dashboard/OperationalAlerts.tsx:24,106` | `sev` (alta/media/baja en minúscula), `item.status` | `severity`, `status` |
| 11 | `admin/SchedulerPanel.tsx:275` (`statusBadge` cae a `st`), `400` (`[phase] resource msg` de SSE), job.status | `partial`, `queued`, fases, `msg` libre del backend | `runStatus`, `phase` |
| 12 | `recovery/RecoveryTable.tsx:68-69,72` | `account` (`virtualpos1`), `rejection_code`, `rejection_reason` (texto del proveedor, puede venir en inglés), `result` | `channel`, `rejectionCode`, `reconcileResult` |
| 13 | `dashboard/GeneralSubscriptionsPanel`, `GeneralClientsPanel` | `status`, `secondary_status`, `platform`, `origins[]` crudos | `status`, `channel` |
| 14 | `billing/billingLabels.ts` `eventLabel` (`type.replace(/_/g," ")`), `statusLabel`, `typeLabel`; `PLATFORM_LABELS[...]` | fallback al valor crudo | `billingEvent`… |
| 15 | `api.ts:31-32` `httpErrorMessage` | `detail` del backend (cadena libre) se muestra tal cual en toasts/errores | `apiError` (traducir códigos, no texto) |
| 16 | `shared/utils.ts:277-` `fieldLabel` fallback `field.replaceAll("_"," ")` | claves de campo desconocidas salen como inglés («card brand») | `field` |
| 17 | `admin/PermCheckboxes.tsx:23` | `p.description` de permisos (viene del backend/seed) | `permission` |
| 18 | `billing` `technicalCode` | etiqueta técnica (`RuntimeError`, `StuckApplying`) deliberadamente cruda | excepción documentada; mostrar como «Código técnico: X» |
Total: 18 grupos de sitios, ≈ 55 puntos de renderizado individuales; ≈ 45 valores distintos conocidos a mapear (ver B-catálogo abajo).

### A.4 Mapas de rótulos existentes: qué cubren y qué no
| Mapa | Cubre | No cubre / riesgo |
|---|---|---|
| `billing/billingLabels.ts` (`STATUS_META`, `TYPE_LABELS`, `EVENT_LABELS`, `PLATFORM_LABELS`) + `billingErrors.ts` (`CODE_MESSAGES`, `POLICY_MESSAGES`, `STATUS_MESSAGES`) | Solicitudes de cambio de cobro: 10 estados, 4 tipos, 13 eventos, ~28 códigos de error. Referencia de buen diseño. | Fallback = valor crudo (`statusLabel/typeLabel` devuelven el código; `eventLabel` sustituye `_` por espacio). |
| `statusColors.ts` | Solo COLOR (heurística de palabras es/en). No traduce. | Es la fuente de verdad de equivalencias es/en (`paid/pagad`, `reject/rechaz`…); su `KEYWORDS` se puede reutilizar para validar el catálogo. |
| `shared/kpis.ts` | Notas fijas de canal (es). | Sin valores. `PAYKU_COVERAGE_NOTE` mezcla «success» (inglés técnico) en la nota Payku. |
| `shared/constants.ts` (`statusResourceLabels`) | Recursos: client/customer/subscription/charge/payment/transaction/plan/payment_method/invoice. | Fallback `?? resource` crudo; usa «Subscripciones». Duplicado de `resourceTitle()` en `utils.ts`. |
| `shared/utils.ts` (`resourceTitle`, `fieldLabels`, `cardTypeText`, `title`) | ~65 campos, 9 recursos, 4 tipos de tarjeta, nombres de canal. | Sin tildes; `title()` capitaliza lo desconocido; `cardTypeText` cae a `text(value)`. |
| `virtualpos/constants.ts` | Rótulos de formularios/filtros VP/Toku/Payku. | Mezcla rótulos con claves de lógica (A.2). |
| `dashboard/ChannelDashboardView.tsx` `CHANNEL_NAMES` | virtualpos/toku/payku. | Duplica `title()`. |
| `scheduler` `statusBadge` / `OperationalAlerts` `SevBadge` | Pocos estados, in situ. | Fallback crudo; SevBadge muestra `alta` sin capitalizar. |

### A.5 Dónde cae a crudo y cómo debería comportarse
Fallbacks a crudo identificados: `statusLabel`, `typeLabel`, `eventLabel`, `statusResourceLabels[r] ?? r`, `resourceTitle`, `fieldLabel`, `title()`, `cardTypeText`, `text()` (todo el detalle de proveedor), `statusBadge`, `StatusBars`, `chartRows` (series), `CHANNEL_NAMES ?? title()`.
Comportamiento propuesto: `label(domain, value)` -> mapa exacto (normalizado: trim, minúsculas, `_`/`-` -> espacio, sin tildes) -> si no existe, devolver **«Desconocido (valor)»** (conservando el valor para soporte) y emitir un `console.warn` en desarrollo/test. Excepciones: nombres propios/datos libres (nombres de rol, plan, cliente) no pasan por `label`. `null/""` -> «Sin dato» (ya existente).

---
## B. IDENTIFICADORES EN ESPAÑOL

Cifras (heurística; "simple" tiene ruido de ~50% por palabras sueltas del JSX):
| Categoría | Ids únicos | Pares archivo+id | Ocurrencias |
|---|---|---|---|
| (a) Claves snake_case españolas = CONTRATO API TCH/alertas | 42 | 85 | 138 |
| (b) Compuestos internos camel/Pascal (funciones, estado, hooks, tipos, componentes) | 49 | 89 | 322 |
| (c) Palabras sueltas (props/var: `estado`, `monto`, `canal`, `periodo`, `tipo`, `detalle`, `nombre`, `suscripciones`, `transacciones`…) | 125 (≈60 reales) | ≈330 (≈160 reales) | ≈610 |
| (d) Constantes MAYÚSCULAS | 2 (`ALTAS_COLOR`, `BAJAS_COLOR`) | 2 | 5 |
| Nombres de ARCHIVO en español | 0 | - | - |
(Archivos ya en inglés: todos. Hay 1 hook `useTch`, 1 componente `TchContent`: siglas del canal TCH, aceptables.)

### B.1 (a) Contrato con la API (renombrar exige adaptador o cambio coordinado con backend)
Confirmado en backend `app/api/v1/routes/tch.py` y `staging.py`:
- TCH `TchSuscripcion`: `numero_ficha, numero_mandato, cliente_rut, banco_nombre, tipo_mandato, tipo_cuenta, origen, centro_costo, captador, monto, fecha_activacion, equivalente_pesos, fecha_rechazo, fecha_eliminacion, fecha_fin, razon_baja, estado`.
- `TchTransaccion`: `periodo, numero_cuota, total_cuotas, monto, fecha_cargo, tipo_transaccion, estado, entidad_recaudadora, razon_rechazo, archivo_origen`.
- `TchCliente`: `nombre, apellido, fecha_nacimiento, profesion, tipo_persona, tipo_socio, telefono, direccion, comuna, ciudad`.
- `TchSummary`: `suscripciones{vigentes,eliminadas,total,monto_*}`, `transacciones{total,aceptadas,rechazadas,tasa_rechazo_pct,monto}`, `transacciones_mensuales, transacciones_fuente, activaciones_mensuales, bajas_mensuales, ultimo_etl`, `recaudo_mensual`.
- Alertas: `DashboardAlert{sev,tipo,canal,detalle,periodo}`, `AlertDetailItem{ultimo_cobro,ultimo_estado,intentos}`; `GeneralClientDetail.id_cliente/id_cargo/id_transaccion`; `cobrable_subs_monthly, cobrable_subscription_count`, `monto, monto_vigente, nunca_cobrado, sin_cambio, requiere_conciliacion, no_ejecutable` (valores/claves de recuperador y billing).
- Contrato de exportación (docs/data/exports.md): entidades `clientes|suscripciones|cobros|pagos`, parámetro `canal`; permisos `tch.clientes.view`, `tch.suscripciones.view`, `tch.transacciones.view`. Rutas URL españolas (`/tch/clientes`, `/virtualpos/recuperador-socios`, `/general/cambios-de-cobro`): son contrato con el usuario (enlaces guardados); NO tocar.
- Cadenas de rutas internas (`RouteState.view: "clientes"|"suscripciones"|"transacciones"|"usuarios"|"sincronizacion"`, `numeroFicha`) son internas pero derivan del URL; renombrables con tabla de equivalencia.
- Typo contractual del proveedor VirtualPOS (`suscription_date`, `suscription_url`): inglés mal escrito pero es contrato; solo envolver.
Estrategia: capa `adapters/tch.ts` que convierte `numero_ficha -> ficha/serialNumber`, `estado -> status`, `monto -> amount`, etc. Los tipos del dominio (`TchSubscription`) quedan en inglés; los tipos "wire" (`TchSubscriptionWire`) conservan las claves del backend y viven SOLO en el adaptador.

### B.2 (b) Puramente internos (renombrables sin riesgo de API)
- Hook TCH (`tch/useTch.ts`, 32 ids, 105 ocurrencias): `tchClientes, tchClientesPage, tchClienteFiltro, tchClienteDetail, tchSuscripciones, tchSusFiltroEstado, tchSuscripcionDetail, tchTransacciones, tchTransPage, tchTransFiltroPeriodo, tchTransaccionDetail` y sus 11 `setTch*`; acciones `showTchCliente`, `showTchSuscripcion`, `showTchTransaccion`.
- Tipos: `TchCliente, TchClienteDetail, TchClientesResp, TchSuscripcion(+Detail,+esResp), TchTransaccion(+Detail,+esResp)` (9 en `shared/types.ts`), `ExportCanal`, `RecaudoMensual`/`recaudoMensual` (cliente), `numeroFicha`.
- Componentes de gráfico en `MonthlyStatusChart.tsx`: `ActivacionCaidaChart, CrecimientoMensualChart, ChurnMensualChart, TransaccionesSuscripcionesChart, IngresosMensualesChart` (+ usos en `GeneralKpis`, `GeneralSummaryContent`).
- Variables locales: `altasBajas, cobrableByKey, cobrableSubs, showVigente, transFilter/setTransFilter, ALTAS_COLOR, BAJAS_COLOR`, y en `TchContent.tsx` (86 pares) props/atributos de las filas (`s.estado`, `t.monto`…) que desaparecerían con el adaptador.
- Tests que referencian estos nombres: solo `test/tch.characterization.test.tsx` (nombres internos `showTch*`/`numero_ficha` en fixtures) -> mínimo impacto.

### B.3 Top 15 archivos por pares (archivo, identificador español)
| # | Archivo | Total | a (contrato) | b (interno) | c (palabra suelta) |
|---|---|---|---|---|---|
| 1 | `features/tch/TchContent.tsx` | 86 | 25 | 22 | 39 |
| 2 | `features/shared/types.ts` | 69 | 37 | 9 | 23 |
| 3 | `features/tch/useTch.ts` | 32 | 1 | 30 | 1 |
| 4 | `MonthlyStatusChart.tsx` | 17 | 0 | 7 | 10 |
| 5 | `features/shared/utils.ts` | 17 | 9 | 0 | 8 |
| 6 | `features/billing/CreateRequestDialog.tsx` | 15 | 0 | 0 | 15* |
| 7 | `features/dashboard/ChannelDashboardView.tsx` | 15 | 0 | 3 | 12 |
| 8 | `features/dashboard/GeneralSummaryContent.tsx` | 15 | 0 | 4 | 11 |
| 9 | `AutomaticReport.tsx` | 14 | 0 | 0 | 14* |
| 10 | `features/dashboard/OperationalAlerts.tsx` | 13 | 2 | 0 | 11 |
| 11 | `features/billing/billingLabels.ts` | 12 | 2 | 0 | 10* |
| 12 | `features/billing/PlanPreviewView.tsx` | 12 | 0 | 0 | 12* |
| 13 | `features/virtualpos/VirtualPosWriteDialogs.tsx` | 12 | 0 | 0 | 12* |
| 14 | `features/recovery/RecoveryPanel.tsx` | 11 | 1 | 0 | 10* |
| 15 | `AppCore.tsx` | 10 | 1 | 6 | 3 |
(*) Mayormente ruido: palabras españolas del JSX/strings que el escáner no separa; revisar a mano. Los datos reales de identificadores se concentran en las filas 1-5, 7-8, 10, 15 (TCH, tipos, gráficos, utils, dashboards).

Resumen: ≈ 90% del trabajo de renombrado está en TCH (`TchContent`, `useTch`, `types.ts`, `utils.ts:normalizeTchSummary`, `MonthlyStatusChart`, `GeneralKpis/Summary`).

---
## C. PROPUESTA

### C.1 Arquitectura mínima de textos
```
frontend/src/i18n/
  es.ts          // catálogo: Record<Domain, Record<string, string>> (solo datos)
  label.ts       // label(domain, value, opts?) + normalizeKey()
  label.test.ts  // exactitud, normalización, fallback «Desconocido (X)»
  catalog.guard.test.ts  // guardián (ver C.3)
```
Dominios: `status` (estados de suscripción/cobro/pago/medio de pago de VP, Toku, Payku), `tchStatus`, `secondaryStatus` (cobrable/incobrable/inactiva/nunca_cobrado), `runStatus` (completed, failed, running, partial, queued), `phase` (sync_virtualpos, sync_toku…), `channel` (virtualpos, virtualpos1/2, toku, payku, tch), `resource` (reutiliza `statusResourceLabels` + `resourceTitle`), `field` (reutiliza `fieldLabels` con tildes), `paymentMethod`, `cardType`, `cardBrand`, `paymentType`, `boolean` (true/false/T/F -> Sí/No), `severity` (alta/media/baja), `rejectionCode`, `frequency` (monthly…), `currency`, `eventType`, `billingStatus`, `billingType`, `permission` (opcional).
Valores iniciales a cargar (observados en fixtures, snapshots y código): ACTIVA/ACTIVO/active/ACTIVE -> «Activa»; CANCELADA/CANCELLED/canceled -> «Cancelada»; PAUSED -> «Pausada»; PAID/paid/pagado/pagada -> «Pagado»; SUCCESS/success -> «Exitoso»; FAILED/failed -> «Fallido»; REJECTED/rechazado/rechazada -> «Rechazado»; PENDING/pendiente -> «Pendiente»; VIGENTE -> «Vigente»; ELIMINADA -> «Eliminada»; ACEPTADA -> «Aceptada»; RECHAZADA -> «Rechazada»; completed -> «Completada»; running -> «En curso»; partial -> «Parcial»; cobrable/incobrable/inactiva -> «Cobrable/Incobrable/Inactiva»; PERSONA/EMPRESA; ACTIVO/BLOQUEADO; VN/VC/… (payment_type_code, confirmar con VP).
API: `label("status", raw)` devuelve string; `labelOr(domain, raw, fallback)` para null; `tryLabel` devuelve `undefined` si es desconocido (para tests). `normalizeKey`: tildes fuera, minúsculas, `[_-]` -> espacio, trim. Mantener `statusColors.ts` como está (color); `label` y `statusColor` comparten la normalización.
Regla de fallback: `«Desconocido (${raw})»` y `console.warn` solo en `import.meta.env.DEV`/test (sin PII en logs; los valores son estados, no datos personales).
`billingLabels` se conserva como dominio propio (ya correcto); solo cambia el fallback de `statusLabel/typeLabel/eventLabel` a `Desconocido (...)`. Los tests `billing.labels.test.ts` y `billing.pure.test.ts` fijan hoy el fallback crudo (verificar antes).

### C.2 Convención de nombres (inglés en código)
- Dominio en inglés; claves wire solo dentro de `adapters/*Wire.ts`. TCH: `TchCliente -> TchClient`, `TchSuscripcion -> TchSubscription`, `TchTransaccion -> TchTransaction`, `numero_ficha -> mandateSerial` (o `slipNumber`), `estado -> status`, `monto -> amount`, `periodo -> period`, `fecha_cargo -> chargeDate`, `razon_rechazo -> rejectionReason`, `showTchSuscripcion -> showTchSubscription`, `renderTchContent` (inexistente hoy; `TchContent` ya está en inglés), gráficos `ActivacionCaidaChart -> ActivationsVsChurnChart`, `CrecimientoMensualChart -> MonthlyGrowthChart`, `ChurnMensualChart -> MonthlyChurnChart`, `IngresosMensualesChart -> MonthlyRevenueChart`, `TransaccionesSuscripcionesChart -> TransactionsVsSubscriptionsChart`.
- Regla ESLint (opcional, fase final): `id-denylist` con la lista de palabras españolas del proyecto para impedir regresiones (sin romper claves wire: archivo de adaptadores exento).

### C.3 Test guardián
`frontend/src/i18n/catalog.guard.test.tsx`:
1. Para cada dominio, todo código conocido (lista `KNOWN_RAW` en el test, extraída de fixtures/backend) devuelve texto sin `[A-Z_]{3,}` ni minúscula inglesa conocida (`active|paid|failed|success|pending|true|false|completed|running|cancelled`).
2. Renderiza las vistas de caracterización (reutilizando `appHarness` + `fixtures.ts`) y falla si el `document.body.textContent` contiene un token de la lista `FORBIDDEN_EN = ["ACTIVE","PAID","SUCCESS","FAILED","CANCELLED","PAUSED","completed","failed","running","partial","True","False","Status"]` (como palabra completa, excluyendo atributos `value=`/`data-*` y nombres propios). Una lista de excepciones explícita (`ALLOWED = ["Email"?]`) documenta lo permitido.
3. Test de "valor desconocido": inyectar `status: "ZZ_NEW"` en un fixture y verificar «Desconocido (ZZ_NEW)».
4. Test estático de cobertura: cada código que `statusColors.normalizeStatus` clasifica distinto de `unknown` debe tener entrada en el catálogo (`it.each` sobre las `KEYWORDS`).

### C.4 LISTA DE TRABAJO (uno a uno; cada paso: cambio -> `vitest` del archivo + suites afectadas -> actualizar snapshot si procede)
Esfuerzo: S <1h, M 1-3h, L >3h. Riesgo: B bajo, M medio, A alto.
| # | Paso | Archivos | Esf. | Riesgo | Tests existentes que lo cubren | Tests que faltan |
|---|---|---|---|---|---|---|
| 0 | Crear `i18n/es.ts`, `label.ts`, tests unitarios y guardián (inicialmente solo reglas 1,3,4) | nuevos | M | B | - | `label.test.ts`, `catalog.guard.test.tsx` |
| 1 | Rótulos estáticos en inglés: «Status»->«Estado» (2), «Email»->«Correo electrónico» (6), «ID Sub», `renewalText` Sí/No, opciones Toku | `ClientDetailView`, `PlanDetailView`, `columns.ts`, `constants.ts`, `TchContent`, `utils.ts`, `ProviderWriteDialogs` | S | B | `records.characterization` (snapshot con «True» ×1, ACTIVE/PAUSED/CANCELLED ×2 en `writes.characterization`), `staging.characterization` | aserciones explícitas de `renewalText` y de opciones del diálogo Toku |
| 2 | Desacoplar rótulo de columna y lógica de filtro (clave `key` en `TableColumn`; `vpColumnFields`/`filterFieldForColumn` por clave) | `virtualpos/constants.ts`, `columns.ts`, `VirtualPosDetailTable.tsx`, `exportMapping.ts` | M | A | `exportMapping.test` (13), `export.integration.test` (12), `staging.characterization` | test que cambie el rótulo y compruebe que el filtro de columna sigue exportando |
| 3 | Tildes y «Suscripción» en todos los rótulos (`fieldLabels`, `virtualPos*FieldLabels`, `recurringFieldLabels`, `columns.ts`, `cardTypeText`, filtros) | `utils.ts`, `virtualpos/constants.ts`, `columns.ts`, `StagingRecordsList`, etc. | M | M (snapshots + paso 2 primero) | snapshots `records/staging/writes`, `exportMapping.test` | guardián de ortografía: lista de palabras sin tilde prohibidas («Telefono», «Subscripcion»…) |
| 4 | `label("status")` en `StatusBars` + leyendas/tooltips (`title`) y `chartRows.statusStackedChart` (series: `key` crudo, `label` traducido; color sigue por `statusColor(raw)`) | `StatusBars.tsx`, `chartRows.ts`, `channelCharts.ts` | M | M (leyendas; claves de datos no deben cambiar) | `chartRows.test`, `chartRows.extended.test`, `ChannelChart.*.test`, `statusColors.test`, `ChannelDashboardView.test`, `general.characterization` | test de leyenda traducida y de fallback «Desconocido (X)» |
| 5 | Estados en listas y fichas VirtualPOS/Toku/Payku (≈25 columnas «Estado», `payment_type_code`, `secondary_status`) | `columns.ts`, `ClientDetailView`, `PlanDetailView`, `SubscriptionDetailView`, `Charge/PaymentDetailView`, `ProviderWriteDialogs:47` | M | M | `records.characterization`, `staging.characterization`, `writes.characterization` (snapshots cambian: ACTIVA×10, ACTIVE×5) | caso por canal con estado inglés y desconocido |
| 6 | `text()`/detalle de proveedor: valores booleanos/enum (`is_active`, `frequency_type`, `currency`, `card_brand`, tipos de medio de pago) con dominios `boolean/frequency/currency/cardType/paymentMethod`; `fieldLabel` fallback «Campo (clave)» | `ProviderRecordDetailView`, `TokuPaymentMethodProfile`, `utils.ts` | M | M | `records.characterization` | detalle Toku medio de pago con valores crudos |
| 7 | ETL/Scheduler/Sync: `runStatus`, `phase`, `channel`; SSE `msg` (mapear por `type/phase`, no mostrar `msg` libre) | `EtlPanel`, `GeneralSummaryContent`, `SchedulerPanel`, `SidebarHealth` | M | M | `SchedulerPanel.test` (12), `general.characterization`, `useChannelHealth.test` | `statusBadge('queued')`, fase desconocida |
| 8 | TCH valores: `estado`, `secondary_status`, `ultimo_etl.status`, tipos de transacción | `TchContent.tsx` | M | M | `tch.characterization` (14 + snapshot: VIGENTE×4, ACEPTADA×3, RECHAZADA×2, ELIMINADA×2) | estado TCH desconocido |
| 9 | Alertas y recuperador: `severity` capitalizada, `status` de detalle, `account`, `rejection_code/reason`, `result` | `OperationalAlerts`, `alertGroups`, `RecoveryTable`, `RecoveryPanel` | M | B/M | `OperationalAlerts.test` (10), `alertGroups.test` (8), `recovery.test` (11) | códigos de rechazo en inglés (si el backend los devuelve) |
| 10 | Billing: reemplazar fallback crudo por «Desconocido (X)» en `statusLabel/typeLabel/eventLabel/PLATFORM_LABELS`; `technicalCode` con prefijo «Código técnico» | `billingLabels.ts`, `RequestDetail`, `BillingInbox` | S | B | `billing.labels.test`, `billing.pure.test`, `billing.fixes.*`, `billing.ui.test` | tests del fallback nuevo (los actuales pueden fijar el comportamiento crudo) |
| 11 | Errores de red/API: `httpErrorMessage` no muestra `detail` libre del backend salvo códigos conocidos (`detail.code` -> catálogo `apiError`); agregar `ApiError.code` | `api.ts`, `billingErrors.ts` | M | M | `billing.fixes.ui.test`, `ExportButton.test`, (api sin test propio) | `api.test.ts` nuevo |
| 12 | Descripciones de permisos (`PermCheckboxes`, `groupPermissions`) con dominio `permission` o confirmar que el backend ya las envía en español | `PermCheckboxes`, `utils.ts` | S | B | ninguno | test de grupos |
| 13 | RENOMBRADO internos B.2 - 13a: gráficos `MonthlyStatusChart.tsx` (5 componentes) | `MonthlyStatusChart`, `GeneralKpis`, `GeneralSummaryContent` | S | B | `GeneralKpis.test`, `general.characterization`, `chartProps.test` | - |
| 14 | 13b: variables locales (`altasBajas`, `cobrableSubs`, `showVigente`, `transFilter`, `ALTAS_COLOR`) | `channelCharts`, `RecoveryTable`, otros | S | B | `channelCharts.test` (15), `recovery.test` | - |
| 15 | 13c: hook y estado TCH (`useTch`, `AppCore`, `TchContent`): `showTchSuscripcion->showTchSubscription`, `tchClientes->tchClients`, `setTch*`, etc. (solo nombres internos, sin tocar claves wire) | `useTch.ts`, `AppCore.tsx`, `TchContent.tsx` | M | M | `tch.characterization` (14) + `navigation.characterization` | - (cobertura buena) |
| 16 | ADAPTADOR TCH: `adapters/tchAdapter.ts` convierte wire (`numero_ficha, estado, monto, periodo…`) a dominio en inglés; renombrar tipos (`TchSubscription`…), `normalizeTchSummary`, `exportMapping.tchExportTarget`; los tests de fixtures siguen en wire | `types.ts`, `utils.ts`, `useTch.ts`, `TchContent.tsx`, `exportMapping.ts`, `test/fixtures.ts` | L | A | `tch.characterization`, `export.integration`, `exportMapping.test` | `tchAdapter.test.ts` (wire->dominio, nulos), contrato con muestra real del backend |
| 17 | Adaptador de alertas y claves de recuperador/billing (`tipo, canal, detalle, ultimo_cobro, monto_vigente, id_cargo…`) | `types.ts`, `alertGroups.ts`, `OperationalAlerts`, `RecoveryTable` | M | M | `alertGroups.test`, `OperationalAlerts.test`, `recovery.test` | `alertAdapter.test.ts` |
| 18 | Rutas internas (`view: "clientes"|"usuarios"|"sincronizacion"`, `numeroFicha`) a inglés, manteniendo URLs en español | `routes.ts`, `navigation.ts`, `AppCore`, `Sidebar` | M | M | `navigation.characterization` (19), `navigation.menu.test` (18), `Sidebar.test` (27) | test de ida y vuelta URL<->ruta |
| 19 | Activar regla lint `id-denylist` y guardián de identificadores (script de test que lee los fuentes y falla con palabras españolas fuera de `adapters/` y del catálogo `es.ts`) | `eslint.config`, nuevo test | S | B | - | el propio guardián |

Orden recomendado: 0 -> 1 -> 10 -> 4 -> 5 -> 6 -> 8 -> 7 -> 9 -> 2 -> 3 -> 11 -> 12 -> 13-15 -> 16 -> 17 -> 18 -> 19. Los pasos 1-12 cambian TEXTO (se verifican con los snapshots); 13-19 cambian NOMBRES (los snapshots no deberían variar: si varían, hay una regresión).

Cobertura de los 686 tests: los que más protegen la traducción son los 5 `*.characterization` (con 5 snapshots, 103 líneas con valores crudos: ACTIVA×10, ACTIVE×5, VIGENTE×4, ACEPTADA×3, RECHAZADA/ELIMINADA/PAUSED/CANCELLED/completed ×2, True×1) y `statusColors.test`/`chartRows*` (series por estado). Los snapshots de pasos 4-9 se actualizarán de forma intencional y deben revisarse a mano. Huecos: `api.ts`, `utils.ts` (`renewalText`, `cardTypeText`, `fieldLabel`), `StatusBars`, `EtlPanel`, `TokuPaymentMethodProfile`, `GeneralSummaryContent` (sin test propio).

### C.5 Riesgos y decisiones abiertas para el usuario
1. «Email»: ¿se acepta como préstamo o se exige «Correo electrónico»?
2. `technicalCode` (billing) muestra etiquetas técnicas en inglés a propósito: ¿se mantiene bajo el rótulo «Código técnico»?
3. Mensajes `rejection_reason` del proveedor y `msg` de SSE son texto libre: o el backend envía códigos, o se muestran bajo «Detalle del proveedor» sin traducir (excepción explícita en el guardián).
4. Renombrar claves wire de TCH exige coordinar con backend; recomendado NO renombrar el backend y usar adaptador.
5. Los nombres de marca/sigla (VirtualPOS, Toku, Payku, TCH, RUT, CLP, UF, MRR, ARPU, LTV, ETL) se consideran válidos en ambas reglas.
