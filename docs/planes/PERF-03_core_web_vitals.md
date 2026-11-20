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
