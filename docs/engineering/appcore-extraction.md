# Extracción de vistas de `AppCore.tsx` (UX-04)

Estado: en curso (2026-10-29). Objetivo: sacar el estado y el JSX de cada pantalla de `frontend/src/AppCore.tsx` a módulos en `frontend/src/features/*` **sin cambiar comportamiento ni apariencia** (mismas rutas, textos, peticiones y estado visible). No se unifican vistas, no se renombra el menú, no se toca la navegación (eso es UX-05) y no se cambian estilos.

## 1. Mapa de `AppCore.tsx` (antes de empezar: 3.666 líneas)

`AppCore` es **una sola función componente** de ~3.580 líneas que concentra: sesión, tema, navegación por URL, el estado y los efectos de todas las pantallas, los manejadores de escritura contra VirtualPOS/Toku/Payku y el JSX de todas las vistas. No tenía ningún test propio.

### 1.1 Bloques (líneas del archivo original)

| Bloque | Líneas aprox. | Contenido |
|---|---|---|
| Estado | 82-243 | ~110 `useState`; sesión, ruta, dashboards, listas, detalles, formularios de escritura, TCH, ETL, tema, sidebar |
| Efectos de carga | 245-483 | sesión (`/auth/me`), tema, resumen de staging, dashboard general, clientes/suscripciones consolidados, registros de staging, valores de filtro, dashboard de canal, TCH (7 sub-vistas) |
| Escrituras | 500-1144 | crear/editar cliente, crear plan, crear suscripción, crear/cancelar/reintentar cargo, cancelar suscripción, editar/eliminar registro de Toku y Payku, cambiar estado de suscripción Toku |
| Navegación | 1146-1429 | `navigate`, permisos de ruta, `show*` (dashboard, clientes, suscripciones, reporte, TCH, canal, sección, recuperador, cambios de cobro, admin, perfil), ETL (`runFullSync`, `syncChannel`) |
| Fichas | 1431-1583 | `openVirtualPos{Client,Plan,Subscription,Charge,Payment}`, `openProviderRecord`, `openRecord` |
| Rutas | 1585-1691 | `applyRoute` (`useEffectEvent`) y tres efectos que escriben `?campo`, `?offset`, `?orden` en la URL |
| JSX de fichas | 1722-2217 | seis fichas: cliente, plan, suscripción, cargo y transacción de VirtualPOS + ficha genérica de Toku/Payku |
| JSX de listas | 2218-2586 | controles de filtro + tabla de registros de staging (`providerDetail`) |
| JSX dashboard general | 2587-2793 | KPIs del año, gráficos, tabla de clientes y suscripciones consolidados, panel ETL |
| JSX diálogos | 2794-3018 y 3348-3660 | 11 diálogos de edición, creación, cancelación y confirmación |
| JSX TCH | 3019-3241 | resumen y 6 sub-vistas |
| Composición | 3243-3366 | `content` (selección de vista), `Sidebar`, paneles de admin/perfil |

### 1.2 Vistas (lo que ve el usuario) y su acoplamiento

| Vista | Ruta | Estado propio | Estado/funciones compartidas | Riesgo |
|---|---|---|---|---|
| TCH (resumen, clientes, suscripciones, transacciones, 3 fichas) | `/tch/*` | `tch*` (16 estados), su propio `tchError`/`tchLoading` | `session`, `setReportScope`, `showTch` (lo invocan Sidebar y `applyRoute`), `clearDetails` desde `showTch` | Bajo: no usa `error` global ni `records` |
| Dashboard general (resumen) | `/central/resumen` | `generalData`, `generalMode`, `generalYear`, `debtFilter`, `transFilter`, `summary` | `error`, `setReportScope`, ETL (`runFullSync`) | Medio |
| Clientes consolidados | `/central/clientes` | `generalClients`, consulta, filtro, offset, ficha | `error`; el offset y el campo se escriben en la URL desde un efecto | Medio |
| Suscripciones consolidadas | `/central/suscripciones` | análogo | análogo | Medio |
| Reporte automático | `/central/reporte-automatico` | ninguno | solo `generalView` | Muy bajo (ya es un componente) |
| Dashboard de canal | `/{canal}/resumen` | `channel`, `channelData`, `mode`, `year`, `syncing`, `channelLoading` | `invalidateCache`, `openChannelResource` → `showSection` | Bajo |
| Listas de staging (VP/Toku/Payku) | `/{canal}/{recurso}` | `records`, `recordsOffset`, filtros, orden, `vpPlatform`, `statusValues` | **`records` lo mutan todas las escrituras**; `error`; URL | Alto |
| Fichas VirtualPOS (5) | `/virtualpos/{recurso}/{id}` | `clientDetail`, `planDetail`, `subscriptionDetail`, `chargeDetail`, `paymentDetail`, `detailLoading` | las escrituras los mutan (cancelar, reintentar, crear cargo, editar cliente); `showResourceList` | Alto |
| Ficha Toku/Payku | `/{toku|payku}/{recurso}/{id}` | `providerRecordDetail` | escrituras de proveedor | Medio |
| Diálogos de escritura VirtualPOS (6) | (modales) | ~35 estados | `records`, 4 fichas, `refreshCsrfToken` | Alto |
| Diálogos de proveedor (3) | (modales) | ~9 estados | `records` | Medio |
| Recuperador, Cambios de cobro, Admin, Perfil | `/virtualpos/recuperador-socios`, `/general/cambios-de-cobro`, `/admin/*`, `/mi-perfil` | ya son componentes en `features/*` | `can`, sesión | Ya extraídas |

### 1.3 Acoplamientos que condicionan el orden

1. **El estado de AppCore sobrevive a la navegación; el de un componente hijo no.** Si un estado hoy vive en AppCore (p. ej. `tchMode`, `debtFilter`) y se mueve a un componente que se desmonta al cambiar de vista, **cambia el comportamiento visible** (se reinicia al volver). Regla de esta extracción: el JSX pasa a componentes de presentación y el estado pasa a **hooks con nombre llamados desde AppCore**, que mantienen la misma vida útil.
2. `error` (global) lo escriben ~12 efectos y manejadores y lo muestran dos vistas (dashboard general y listas de staging); `showDashboard`, `showSection`, `showChannel`, `showTch` lo ponen en `null`. Se queda en AppCore y los hooks reciben `setError`.
3. `records` y las 5 fichas de VirtualPOS son lo que las escrituras actualizan: son el **estado compartido real** (lista ↔ fichas ↔ diálogos). Se sube a `useStagingRecords` y `useRecordDetails`; las escrituras se extraen **después** y reciben sus setters.
4. `showTch`, `showChannel`, `showSection`, etc. se llaman desde `Sidebar`, `applyRoute` y botones internos; se quedan en AppCore (son la navegación) y llaman a los setters de cada hook.
5. `applyRoute` conoce el estado de listas (filtro, orden, offset, cuenta VirtualPOS) y de clientes/suscripciones consolidados. Se queda en AppCore; no se toca (UX-05).

## 2. Orden de extracción y riesgo

De la más aislada a la más acoplada. Cada paso: (a) test de caracterización contra el código original (verde), commit; (b) extracción, mismo test verde, commit. Tras cada commit: `npm test`, `npm run build`, `npm run lint`.

| # | Extracción | Destino | Riesgo | Estado |
|---|---|---|---|---|
| 1 | TCH: hook de estado y efecto + `TchContent` | `features/tch/` | Bajo | pendiente |
| 2 | Clientes y suscripciones consolidados (tablas + hook de lista) | `features/dashboard/` | Medio | pendiente |
| 3 | Dashboard general (KPIs, gráficos, tarjetas de canal) y panel ETL | `features/dashboard/` | Medio | pendiente |
| 4 | Dashboard de canal (hook) | `features/dashboard/` | Bajo | pendiente |
| 5 | Fichas VirtualPOS (5) y ficha Toku/Payku | `features/virtualpos/`, `features/provider/` | Medio | pendiente |
| 6 | Listas de staging (controles de filtro + tabla) | `features/provider/` | Alto | pendiente |
| 7 | Diálogos de escritura VirtualPOS + hook | `features/virtualpos/` | Alto | pendiente |
| 8 | Diálogos de proveedor (editar, eliminar, estado Toku) + hook | `features/provider/` | Medio | pendiente |

La navegación (`navigate`, `show*`, `applyRoute`, efectos de URL), la sesión y el tema **se quedan en AppCore** a propósito: moverlas es UX-05.

## 3. Pruebas de caracterización

Se renderiza `<AppCore />` completo con `fetch` simulado (`frontend/src/test/appHarness.tsx`) y datos sintéticos, y se verifican textos, columnas y la petición que dispara cada vista. Las pruebas no conocen la estructura interna, así que valen igual antes y después de mover el código.

(Se completa al terminar cada paso.)

## 4. Resultado y pendientes

(Se completa al terminar.)
