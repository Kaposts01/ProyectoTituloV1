# Extracción de vistas de `AppCore.tsx` (UX-04)

Estado: extracción completada (2026-10-29): `AppCore.tsx` pasó de 3.666 a 700 líneas. Objetivo: sacar el estado y el JSX de cada pantalla de `frontend/src/AppCore.tsx` a módulos en `frontend/src/features/*` **sin cambiar comportamiento ni apariencia** (mismas rutas, textos, peticiones y estado visible). No se unifican vistas, no se renombra el menú, no se toca la navegación (eso es UX-05) y no se cambian estilos.

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
| 1 | TCH: `useTch` + `renderTchContent` | `features/tch/` | Bajo | hecho (`d4ffac3`) |
| 2 | Dashboard general, clientes y suscripciones consolidados, panel ETL: `useGeneralDashboard`, `useEtl`, `GeneralDashboardView` y paneles | `features/dashboard/` | Medio | hecho (`56d6ad0`) |
| 3 | Dashboard de canal: `useChannelDashboard` | `features/dashboard/` | Bajo | hecho (`1ae3f49`) |
| 4 | Fichas de detalle (5 de VirtualPOS + ficha Toku/Payku) | `features/virtualpos/`, `features/provider/` | Medio | hecho (`a99ef50`) |
| 5 | Lista de registros de staging: `useStagingRecords` + `StagingRecordsList` | `features/provider/` | Alto | hecho (`e7246fa`) |
| 6 | Estado de las fichas abiertas y sus `open*`: `useRecordDetails` | `features/shared/` | Medio | hecho (`9aa3f21`) |
| 7 | Escrituras y diálogos: `useVirtualPosWrites` + `VirtualPosWriteDialogs`, `useProviderWrites` + `ProviderWriteDialogs` | `features/virtualpos/`, `features/provider/` | Alto | hecho (`0e86573`) |

La navegación (`navigate`, `show*`, `applyRoute`, efectos de URL), la sesión y el tema **se quedan en AppCore** a propósito: moverlas es UX-05.

## 3. Pruebas de caracterización

Se renderiza `<AppCore />` completo con `fetch` simulado por tabla de rutas (`frontend/src/test/appHarness.tsx`), sesión y datos sintéticos (`frontend/src/test/fixtures.ts`), y se verifican textos, columnas, la petición que dispara cada vista (ruta y parámetros) y el marcado del área de contenido mediante snapshots normalizados (`contentHtml()`). Las pruebas no conocen la estructura interna, así que valen igual antes y después de mover el código: cada extracción se hizo con la prueba del paso anterior en verde y los snapshots sin tocar.

| Archivo | Pruebas | Cubre |
|---|---|---|
| `tch.characterization.test.tsx` | 14 | resumen, listas, fichas de cliente y de cargo TCH, filtros, paginación, error |
| `general.characterization.test.tsx` | 18 | resumen general, clientes y suscripciones consolidados, Sync completo, persistencia al navegar |
| `staging.characterization.test.tsx` | 24 | listas de VirtualPOS/Toku/Payku (parámetros, columnas, acciones, filtros, orden, cuenta, «Ver más», URL) y dashboard de canal |
| `records.characterization.test.tsx` | 13 | fichas de cliente, plan, suscripción, cargo, transacción y registro Toku/Payku |
| `writes.characterization.test.tsx` | 23 | diálogos y manejadores de escritura (cuerpo enviado, validaciones, actualización de filas y fichas, errores) |
| `navigation.characterization.test.tsx` | 14 | sesión, tema, redirecciones por permiso, ruta antigua de cambios de cobro, popstate, menú |
| **Total** | **106** | 34 snapshots del marcado |

Estabilidad: 20 corridas seguidas de `src/test` y 10 de la suite completa sin fallos (tras fijar `asyncUtilTimeout` y esperar el fin de carga de las listas antes de comparar snapshots).

Vacíos conocidos: los paneles que ya eran componentes (admin, perfil, recuperador, cambios de cobro) solo se verifican a nivel de ruta.

## 4. Resultado

- `AppCore.tsx`: **3.666 → 700 líneas**. Lo que queda es a propósito: sesión, tema, `navigate`/permisos de ruta/`show*`/`applyRoute`/efectos de URL (navegación, UX-05), el selector de qué vista pintar y la composición con `Sidebar`.
- Módulos nuevos: `features/tch/{useTch,TchContent}`, `features/dashboard/{useGeneralDashboard,useEtl,useChannelDashboard,GeneralDashboardView,GeneralSummaryContent,GeneralClientsPanel,GeneralSubscriptionsPanel,EtlPanel}`, `features/provider/{useStagingRecords,StagingRecordsList,ProviderRecordDetailView,useProviderWrites,ProviderWriteDialogs}`, `features/shared/useRecordDetails`, `features/virtualpos/{ClientDetailView,PlanDetailView,SubscriptionDetailView,ChargeDetailView,PaymentDetailView,useVirtualPosWrites,VirtualPosWriteDialogs}`.
- Regla que se siguió: el JSX pasa a componentes de presentación y el estado a **hooks con nombre llamados desde AppCore**; así cada estado conserva su vida útil (modo, año, filtros y ficha abierta sobreviven a la navegación como antes). El estado compartido real (lista de registros y fichas abiertas, que las escrituras actualizan) está en `useStagingRecords` y `useRecordDetails`, y las escrituras los reciben por contexto.
- Cambios no funcionales deliberados: los setters que ahora llegan por parámetro a un hook (`setError`, `setLoading`) se agregaron a las dependencias de sus efectos (son estables, no cambian cuándo corren); `renderTchContent` se invoca como función (ver hallazgo 1).

### Fuera de esta tanda

- Navegación (`navigate`, `show*`, `applyRoute`, efectos de URL, `canAccessRoute`): se queda en AppCore por mandato (UX-05).
- `useVirtualPosWrites` (653 líneas) mantiene los ocho manejadores tal cual; partirlo por recurso (cliente, plan, suscripción, cargo) es posible pero no aporta a UX-05 a UX-11 y exigiría tocar la limpieza de avisos (hallazgo 3).
- `ChannelDashboardView` se sigue montando en línea desde AppCore (ya era un componente).

## 5. Hallazgos de comportamiento

Cada uno está fijado por una prueba de caracterización marcada como HALLAZGO o RAREZA. Estado al 2026-10-29: **corregidos 1, 2, 3 y 4** (pruebas actualizadas de forma deliberada); **pendientes 5, 6 y 7**, que se resolverán con las vistas unificadas (UX-05) y no se tocan antes.

1. **[CORREGIDO, f6e4bb3] La ficha de suscripción TCH no se podía abrir.** `showTchSuscripcion` pinta un detalle provisional `{ numero_ficha }` sin `transacciones` antes de que llegue la respuesta, y el JSX hace `transacciones.map(...)`: el render de AppCore lanza `TypeError`. (Las fichas de cliente y de cargo TCH sí funcionan porque su detalle provisional es tolerante.) Por eso `renderTchContent` se invoca como función y no como elemento: así el fallo sigue propagándose a AppCore igual que antes, en lugar de quedar atrapado por `ContentErrorBoundary`. Corrección: el detalle provisional trae `transacciones: []`, el JSX tolera su ausencia y `TchContent` es ahora un componente (un fallo de render queda en `ContentErrorBoundary`). La prueba HALLAZGO se reemplazó por la caracterización de la ficha (mandato, cargos, snapshot, volver, respuesta sin cargos, error de carga).
2. **[CORREGIDO, a6b6217] Tras «↻ Sincronizar» en un dashboard de canal la vista quedaba en «Cargando mini dashboard...»**: `syncChannel` ponía `channelLoading` en `true` y nunca lo devolvía a `false`. Ahora el `finally` lo apaga.
3. **[CORREGIDO, f57b735] Los avisos «Cambios guardados correctamente.» y «Cliente creado correctamente.» nunca se veían**: el efecto de limpieza se disparaba al cerrar el diálogo, justo después de fijar el aviso. Ahora el aviso solo se limpia al abrir un diálogo de cliente (los de plan, suscripción y cargo no cambiaron).
4. **[CORREGIDO, 43f4dd7] El dashboard de canal no mostraba el error de carga**: el mensaje quedaba en `error`, que esa vista no pinta. Ahora `useChannelDashboard` expone `channelError` y `reloadChannel`, y AppCore pinta un aviso `.error-message` (`role="alert"`) con «Reintentar».
5. **[PENDIENTE, UX-05] Un enlace profundo carga datos que no se muestran**: al abrir directamente `/central/clientes` (o cualquier ruta que no sea el resumen) la vista aún es «summary» durante el primer render, así que se piden `staging/summary` y `staging/dashboard/general` antes de aplicar la ruta.
6. **[PENDIENTE, UX-05] Acciones con distinto reinicio de errores según dónde se disparen**: «Cancelar» una suscripción desde la ficha de cliente reinicia el error del diálogo, desde la lista o la ficha de suscripción no; «Eliminar» un registro reinicia el error desde la ficha pero no desde la lista. Se conservaron las diferencias con callbacks separados.
7. **[PENDIENTE, UX-05] `loading` compartido**: el indicador «Cargando» de la lista de registros también lo apaga el efecto del resumen de staging (`setLoading(false)`), así que puede mostrar «N registros» antes de que termine la carga de la lista en curso.
