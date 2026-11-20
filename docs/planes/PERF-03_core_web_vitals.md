# PERF-03: Core Web Vitals en el frontend (plan)

Pedido del usuario (2026-11-20): «debemos cumplir con el: Velocidad de carga percibida (LCP) … Capacidad de respuesta (INP) … Estabilidad visual (CLS)». Meta propuesta (lectura del Maestro): umbrales «bueno» de Google en el p75: **LCP ≤ 2,5 s, INP ≤ 200 ms, CLS ≤ 0,1**, sobre la build (producción ya se sirve así desde PERF-02d), en escritorio y móvil. Planner en sonnet, solo lectura.

## 1. Medición

- **Base (PERF-03a):** `npx lighthouse@12.6.1` con el Chrome instalado, contra una build de sandbox servida con `vite preview` en un puerto propio (5178, proxy al 8001, `crm_sandbox`), con la cookie de un usuario temporal de solo lectura por `--extra-headers`. Rutas: `/central/resumen`, `/central/suscripciones`, `/virtualpos/resumen`, `/central/clientes`, `/central/cobros`. Escritorio (`--preset=desktop`) y móvil (predeterminado: Moto G, 4G lento simulado). 1 pasada de descarte + 5 por ruta y perfil; p75 = 4.º valor ordenado. Laboratorio, no usuarios reales.
- **INP:** no sale en modo navegación. Proxy de laboratorio: Total Blocking Time (TBT ≤ 200 ms). Medición real propuesta: `web-vitals` (~2 KB) cargado solo en sandbox, con `onINP/onLCP/onCLS` a la consola, interactuando a mano (buscar, filtrar, paginar, cambiar rango de gráficos); móvil con CPU 4x en DevTools.
- **Presupuesto en CI (PERF-03g):** Lighthouse CI (`@lhci/cli`) en un job nuevo de `.github/workflows/ci.yml`: PostgreSQL de servicio, migraciones, semilla sintética (script nuevo, ~2.000 clientes y cobros, usuario ficticio), backend + build + `vite preview`, login por script; aserciones LCP ≤ 2500 ms, CLS ≤ 0,1, TBT ≤ 200 ms, 3 corridas por URL. Empezar avisando y bloquear cuando haya dos semanas estables.

## 2. Riesgos por métrica (hipótesis del código, por confirmar con la medición)

- **LCP:**
  - `frontend/index.html:8-12`: hojas de Fontshare y Google Fonts externas que bloquean el render.
  - Cascada de arranque en `AppCore.tsx`: `/auth/me` tras montar → shell → `Suspense` del chunk perezoso de la vista → datos.
  - La vista de entrada también es `lazy`.
  - `vendor-charts` (recharts) baja detrás de la vista.
- **CLS:**
  - La franja de ambiente (`EnvironmentBanner`, `App.css:11-13`) aparece tras un `fetch` y empuja toda la página. Solo existe en sandbox, pero infla la medición.
  - Fuentes con métricas distintas a las de reserva (`index.css`).
  - Estados de carga de una línea («Cargando vista…») que saltan al contenido completo.
  - Tablas que cambian de alto al cargar.
  - Avisos que se insertan arriba.
- **INP:**
  - `AppCore` monolítico (~790 líneas, más de 40 `useState`): escribir en un buscador re-renderiza todo.
  - Filtros de Cobros sin `startTransition`.
  - Recharts con animación activa.
  - Revisar el debounce de `useStagingRecords`.

## 3. Correcciones candidatas (por impacto y costo)

1. Fuentes autoalojadas (`woff2`, subconjunto latino con tildes y ñ, `font-display: swap`, `preload` de las críticas, métricas de reserva ajustadas) y sin pedidos a dominios externos.
2. Reservar el espacio de la franja de ambiente de forma síncrona (según el modo de la build).
3. Esqueletos con alto reservado en Dashboard, Suscripciones, Cobros, Clientes y VirtualPOS; tablas con alto mínimo.
4. Romper la cascada: vista de entrada sin `lazy` o con `modulepreload`, precarga del chunk de la ruta mientras `/auth/me` está en vuelo, y `environment` y salud en paralelo.
5. INP: `useDeferredValue`/`startTransition` en filtros, `memo` en `Sidebar` y filas, sacar el estado de listados de `AppCore`.
6. Recharts sin animación al cambiar datos y `memo` de `ChannelChart`.
7. Compresión y caché de `assets/*` (hoy `vite preview` responde `no-cache` y sin gzip): evaluar después de medir.

Cada una se verifica con la misma pauta de Lighthouse (y `web-vitals` para INP) antes y después.

## 4. Subtareas

- PERF-03a: medición base (docs).
- PERF-03b: `web-vitals` en sandbox (frontend; depende de decisión).
- PERF-03c: fuentes locales y franja síncrona (frontend).
- PERF-03d: esqueletos y altos reservados (frontend).
- PERF-03e: cascada, precarga y recharts (frontend).
- PERF-03f: INP (frontend), con datos de 03a y 03b.
- PERF-03g: semilla sintética y presupuesto en CI (backend, frontend y CI).
- PERF-03h: documentación del presupuesto (docs).

**Decisiones del usuario (fichas):** móvil emulado o real; si el presupuesto en CI bloquea o solo avisa; dependencias de desarrollo nuevas (`web-vitals`, `@lhci/cli`, Playwright); autoalojar las fuentes.

## 5. Riesgos

Ruido de laboratorio (±10 %, más en CI); datos sintéticos distintos de los reales; separar el CLS de sandbox (franja) del de producción; INP p75 real solo con usuarios reales; refactor de `AppCore` con riesgo de regresión (solo con la suite en verde).

## Medición base (PERF-03a, 2026-11-20)

Lighthouse 12.6.1 (Chrome instalado, sin cabeza), build de sandbox con `vite preview` en 5178 (proxy al 8001, `crm_sandbox`), usuario temporal de solo lectura borrado al terminar. Una pasada de descarte + 5 por ruta y perfil, de a una; p75 = 4.º valor. Escritorio: `--preset=desktop`. Móvil: predeterminado (Moto G, 4G lento y CPU 4x simulados). Las 60 pasadas terminaron sin error. **Laboratorio, no usuarios reales.** INP no se mide en navegación: se muestra TBT como indicio (meta de laboratorio ≤ 200 ms).

| Pantalla | Perfil | LCP p75 | CLS p75 | TBT p75 | FCP p75 | Peso | Elemento LCP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard (`/central/resumen`) | Escritorio | 815 ms | 0,033 | 27 ms | 559 ms | 302 KB | texto de «mes en curso» (`.summary-partial p`) |
| | Móvil | **3.563 ms** | 0,012 | **371 ms** | 2.505 ms | 302 KB | ídem |
| Suscripciones | Escritorio | 671 ms | **0,216** | 0 | 496 ms | 190 KB | franja de sandbox (`.env-banner-detail`) |
| | Móvil | **2.887 ms** | 0,045 | 0 | 2.124 ms | 190 KB | texto de carga (`section.panel p.muted-copy`) |
| VirtualPOS | Escritorio | 787 ms | 0,024 | 37 ms | 450 ms | 311 KB | monto de KPI (`.metric-amount`) |
| | Móvil | **3.666 ms** | 0,039 | **312 ms** | 1.958 ms | 311 KB | encabezado del canal |
| Clientes | Escritorio | 676 ms | 0,033 | 0 | 498 ms | 183 KB | texto de carga |
| | Móvil | 2.291 ms | 0,041 | 0 | 2.120 ms | 182 KB | texto de carga |
| Cobros | Escritorio | 673 ms | **0,172** | 0 | 494 ms | 193 KB | texto de carga |
| | Móvil | **2.733 ms** | **0,136** | 0 | 2.123 ms | 193 KB | texto de carga |

Lectura:

- **Escritorio cumple LCP en las cinco pantallas** (todas bajo 0,9 s). **CLS no cumple** en Suscripciones (0,216) y Cobros (0,172).
- **Móvil emulado no cumple LCP en cuatro de cinco** (2,7 a 3,7 s; solo Clientes, 2,29 s). FCP ya está en ~2,1 s: la primera pintura llega tarde, lo que apunta a las hojas de fuentes externas que bloquean el render y a la cascada de arranque (correcciones 1 y 4).
- El elemento LCP de varias pantallas es un **texto de carga o de aviso**, no el contenido: el LCP real del dato llega después. Con esqueletos (corrección 3) cambia qué se mide como LCP.
- **TBT alto en móvil** en Dashboard (371 ms) y VirtualPOS (312 ms), las dos pantallas con gráficos: riesgo de INP; apunta a recharts y al render inicial.
- En Suscripciones de escritorio el LCP es la franja de sandbox: confirma que la franja influye en la medición (corrección 2). Hay que separar el CLS propio de sandbox del de producción.
- El perfil móvil simula 4G lento; el CRM se usa en red local, así que es una cota pesimista, pero es el criterio de Google.

## Medición después de 03b a 03e (2026-11-20)

Misma pauta que la base (Lighthouse 12.6.1, 1 descarte + 5 pasadas, p75; escritorio y móvil emulado), sobre `bd0082b`. Dos variantes, las dos contra el backend de sandbox (8001):

- **Con franja:** build `--mode sandbox` en 5178.
- **Sin franja:** build de producción en 5179 con proxy forzado al 8001 y `/api/v1/system/environment` bloqueado en Lighthouse, para que no aparezca la franja (como en producción).

Las 120 pasadas terminaron sin error.

| Pantalla | Perfil | LCP antes → con franja → sin franja (ms) | CLS antes → con → sin | TBT antes → con → sin (ms) |
| --- | --- | --- | --- | --- |
| Dashboard | Escritorio | 815 → 797 → 792 | 0,033 → 0,009 → 0,008 | 27 → 37 → 32 |
| | Móvil | **3.563 → 3.621 → 3.644** | 0,012 → 0 → 0 | **371 → 269 → 292** |
| Suscripciones | Escritorio | 671 → 549 → 630 | **0,216 → 0,195 → 0,203** | 0 |
| | Móvil | **2.887 → 2.891 → 2.887** | 0,045 → 0,006 → 0,007 | 0 |
| VirtualPOS | Escritorio | 787 → 833 → 797 | 0,024 → 0 → 0 | 37 → 25 → 33 |
| | Móvil | **3.666 → 3.838 → 3.651** | 0,039 → 0 → 0 | **312 → 346 → 262** |
| Clientes | Escritorio | 676 → 587 → 586 | 0,033 → 0 → 0 | 0 |
| | Móvil | 2.291 → 2.584 → **2.738** | 0,041 → 0 → 0 | 0 |
| Cobros | Escritorio | 673 → 588 → 588 | **0,172** → 0,049 → 0,060 | 0 |
| | Móvil | **2.733 → 2.584 → 2.584** | **0,136** → 0,038 → 0 | 0 |

Lectura:

- **CLS: resuelto en 9 de 10 casos** (todos ≤ 0,06). Queda **Suscripciones en escritorio, ~0,2**, y no es la franja: el desplazamiento viene de `section.panel > div.table-wrap` (la tabla cambia de alto al llegar los datos aunque tenga alto mínimo). Corrección siguiente: reservar el alto real de la página de resultados (filas fijas o `min-height` acorde a 50 filas) o filas esqueleto dentro de la tabla.
- **LCP en escritorio:** cumple en todas (≤ 0,85 s), algo mejor que antes en Clientes, Cobros y Suscripciones.
- **LCP en móvil emulado: no mejoró** (2,6 a 3,8 s; ninguna cumple). La primera pintura bajó de ~2,1 s a ~1,8–2,0 s con las fuentes locales, pero el elemento LCP sigue siendo un texto que aparece cuando llegan los datos (`section.panel p.muted-copy` o el aviso de mes en curso). El cuello es el hilo principal: en VirtualPOS móvil, 1,3 s de trabajo en el hilo principal, 0,7 s de arranque de JS y ~80 KB de JS sin usar en la carga.
- **TBT en móvil:** bajó en Dashboard (371 → ~270–290 ms) y en VirtualPOS sin franja (312 → 262), pero sigue sobre 200 ms. Es el indicio de INP: va a PERF-03f.
- La compresión del servidor (`vite preview` no comprime) ahorraría solo ~10 KB: no es la causa principal.

Siguiente tanda propuesta: (1) Suscripciones: alto real de la tabla o filas esqueleto; (2) móvil: que el LCP sea el contenido estable de la página (título o tarjeta reservada) y no un texto tardío, y aligerar el arranque (diferir recharts y vistas pesadas, revisar el JS sin usar); (3) PERF-03f para TBT/INP.

## Medición después de la tanda 2 (a9d0bd3 y fd97748, 2026-11-20)

Misma pauta, variante sin franja (build de producción en 5179, proxy al 8001, `/system/environment` bloqueado). 60 pasadas sin error.

| Pantalla | Perfil | LCP base → tanda 1 → ahora (ms) | CLS base → tanda 1 → ahora | TBT base → tanda 1 → ahora (ms) |
| --- | --- | --- | --- | --- |
| Dashboard | Escritorio | 815 → 792 → 796 | 0,033 → 0,008 → 0,008 | 27 → 32 → 34 |
| | Móvil | 3.563 → 3.644 → **3.665** | 0,012 → 0 → 0 | 371 → 292 → **291** |
| Suscripciones | Escritorio | 671 → 630 → 631 | 0,216 → 0,203 → **0,014** | 0 |
| | Móvil | 2.887 → 2.887 → **2.896** | 0,045 → 0,007 → 0,002 | 0 |
| VirtualPOS | Escritorio | 787 → 797 → 808 | 0,024 → 0 → 0 | 37 → 33 → 48 |
| | Móvil | 3.666 → 3.651 → **3.724** | 0,039 → 0 → 0 | 312 → 262 → **384** |
| Clientes | Escritorio | 676 → 586 → 588 | 0,033 → 0 → 0 | 0 |
| | Móvil | 2.291 → 2.738 → **2.733** | 0,041 → 0 → 0 | 0 |
| Cobros | Escritorio | 673 → 588 → 588 | 0,172 → 0,060 → 0,054 | 0 |
| | Móvil | 2.733 → 2.584 → **2.586** | 0,136 → 0 → 0,044 | 0 |

Lectura:

- **CLS: cumple en las 10** (máximo 0,054). Suscripciones en escritorio bajó de 0,203 a **0,014**: resuelto con el alto real de la página y la línea de totales reservada.
- **LCP escritorio:** cumple en todas (≤ 0,81 s). **LCP móvil:** sin cambios (2,59 a 3,72 s); esta tanda no lo atacaba (depende de d264).
- **TBT móvil no bajó:** Dashboard queda igual (291 ms) y **VirtualPOS empeoró** (262 → 384 ms; pasadas 260, 282, 364, 384 y 427 frente a 235 a 274 en la tanda 1). Lo aplicado en fd97748 (`memo`, manejadores estables, `startTransition`) evita re-renders en interacciones, pero en la carga inicial que mide Lighthouse agrega trabajo y no lo quita. El INP real de las interacciones no se puede medir en navegación; falta medirlo con web-vitals en sandbox. Antes de integrar fd97748, revisar qué parte agrega costo en la carga de VirtualPOS (posibles: comparación de props de `memo` en muchos componentes, `useStableCallbacks`, `startTransition` en la primera página) o medir el INP real para decidir si se conserva.
