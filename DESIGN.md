---
# gstack: design-md-format=spec
name: SynkmetriX
description: "Registro industrial — herramienta operativa azul-gris con acento azul, datos en mono, confiabilidad como norte visual."
colors:
  primary: "#1a5cae"
  on-primary: "#f4f7ff"
  surface: "#ffffff"
  background: "#f3f5fa"
  text: "#131a2e"
  text-muted: "#475270"
  link: "#1565b0"
  accent: "#1f6fc1"
  success: "#196b40"
  warning: "#7a5200"
  error: "#8b3030"
  sidebar: "#111727"
  sidebar-dark: "#0a0f1c"
  sidebar-active: "#242a38"
  series-1: "#7f55da"
  series-2: "#434ce6"
  series-3: "#0e9f5c"
  series-4: "#0b86c9"
  series-5: "#ee46bc"
  series-6: "#4e5ba6"
typography:
  display:
    fontFamily: "Cabinet Grotesk, Barlow, system-ui, sans-serif"
    fontWeight: 700
    fontSize: "22px"
    letterSpacing: "-0.01em"
  body:
    fontFamily: "General Sans, DM Sans, system-ui, sans-serif"
    fontSize: "14px"
    lineHeight: 1.55
  label:
    fontFamily: "General Sans, DM Sans, system-ui, sans-serif"
    fontSize: "11px"
    letterSpacing: "0.06em"
  mono:
    fontFamily: "JetBrains Mono, Courier New, monospace"
    fontFeature: "tnum"
rounded:
  sm: 4px
  md: 6px
  lg: 10px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
  button-primary-hover:
    backgroundColor: "#1f6fc1"
  input:
    borderColor: "#cbd2e3"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  nav-link:
    textColor: "#c3cada"
---

# SynkmetriX

## Overview

**Creative North Star:** Registro industrial — los números son evidencia, no presentación; el sistema visual transmite confiabilidad antes de que el operador lea el primer dato.

**Product context:** CRM interno de una fundación (Techo.org) para gestión de socios, suscripciones y cobros provenientes de 4 canales: VirtualPOS, Toku, Payku y TCH. Los datos consolidan en entidades canónicas con trazabilidad completa de fuente. El número de socios es defendible ante el directorio.

**Mode per surface:**
- Dashboard y listas: Operate — densidad alta, scan antes que lectura
- Formularios de operación: Operate — eficiencia, feedback inmediato
- Pantalla de revisión de identidad: Operate — decisión con evidencia

**Reference sites:** Metabase (densidad de tabla), Linear (mono para IDs, zero decoration), Retool (ratio función/chrome alto)

**Key characteristics:**
- Sidebar azul marino oscuro (#111727 claro / #0a0f1c oscuro): señal de "estoy en la herramienta", no decoración (D1, 2026-10-29; antes teal)
- Todos los datos numéricos en JetBrains Mono — RUTs, IDs, montos, timestamps; los datos se leen como datos
- Dark mode azul-gris propio (D27), derivado de la imagen de inspiración — no préstamo de GitHub Dark; el sidebar es azul marino en ambos temas
- Gráficos con paleta categórica violeta/índigo (`--series-1..6`), no con el acento azul de interacción
- Tablas first-class: filas de 38px, header en caps pequeñas, hover suave
- Sin decoración: ni blobs, ni íconos en círculo de color, ni sombras agresivas

## Colors

**Strategy:** Committed — el azul de acción (#1a5cae) es el color de marca interactivo y los neutrales tienen base azul-gris (D27, 2026-10-29; antes teal profundo #1a3d47 con neutrales azul-verdosos).

**Light or dark:** Ambos modos definidos. La sidebar siempre en azul marino (#111727 en claro; en oscuro deriva a #0a0f1c, más oscuro que el bg de base). No invertir ingenuamente: el modo oscuro tiene su propia paleta azul-gris, verificada para contraste.

**Sidebar azul marino (D1).** Tonos muestreados píxel a píxel de `docs/dashboardeinspiracion.png`: fondo #111727, ítem activo/campo de búsqueda #242a38. Tokens: `--bg-sidebar`, `--sidebar-text` (#c3cada claro / #b6bfd2 oscuro, ≥ 4,5:1), `--sidebar-text-strong` (#ffffff), `--sidebar-label` (#a3adc2 / #9aa5bd), `--sidebar-heading` (#e4e8f1 claro / #dce1ec oscuro, 14,6:1: títulos de grupo como Cartera u Operación, más claros que los ítems), `--sidebar-hover-bg` (blanco 8 %), `--sidebar-active-bg` (#242a38 claro / #1b2233 oscuro) con `--sidebar-active-text` (#fff, además en peso 700: el activo no depende solo del color), `--sidebar-border`, marca `--sidebar-brand-bg` (#6d3fd0, violeta de la serie 1 oscurecido para texto blanco ≥ 4,5:1). Foco de teclado en el menú: anillo `--series-4` de 2px.

**Paleta categórica de series (D19).** Derivada de la imagen de inspiración (violeta #7f55da, índigo #434ce6, verde #12b76a, azul #0aa5ec, rosa #ee46bc, índigo apagado #4e5ba6); donde el hex original no daba ≥ 3:1 sobre la superficie blanca se oscureció el tono. Las series son **marcas** (barras, líneas, puntos): ≥ 3:1 sobre `--bg-surface`; el texto de leyendas y ejes usa `--text-1/-2`, nunca el color de serie.

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--series-1` | #7f55da (4,98:1) | #9b7af0 (4,66:1) | violeta: serie principal |
| `--series-2` | #434ce6 (6,15:1) | #7f8af5 (4,97:1) | índigo: segunda serie, comparación |
| `--series-3` | #0e9f5c (3,42:1) | #2ed18a (7,68:1) | verde (categoría extra; no es el verde «pagado») |
| `--series-4` | #0b86c9 (3,99:1) | #38b6f5 (6,65:1) | azul |
| `--series-5` | #ee46bc (3,37:1) | #f06ac9 (5,51:1) | rosa |
| `--series-6` | #4e5ba6 (6,23:1) | #8b97d6 (5,43:1) | índigo apagado |
| `--series-muted` | #f5eaff | #2a2350 | barras no seleccionadas, relleno de área |
| `--chart-ref` | #2b3350 | #cbd3e6 | línea punteada de meta (≥ 3:1) |
| `--flow-in` | = `--series-4` (#0b86c9) | = `--series-4` (#38b6f5) | altas; tramo que sube en waterfall y barras divergentes (DEC-36) |
| `--flow-out` | #c2410c (≥ 3:1) | #f39a4a (≥ 3:1) | bajas; tramo que baja (naranja: no es el rojo de «rechazado» ni el gris de «cancelado») |

Orden de uso: series 1 y 2 primero; 3–6 solo si hay más categorías. Los estados de negocio (pagado/rechazado/pendiente) siguen en `--status-*` (statusColors.ts). Los canales (`chartColors.ts`) usan un mapeo fijo sobre `--series-N`: VirtualPOS `--series-1`, Toku `--series-2`, TCH `--series-3`, Payku `--series-4`; un estado nunca usa un token de serie. Altas y bajas usan `--flow-in` (azul) y `--flow-out` (naranja) en todos los gráficos (DEC-36), también como tramos positivo y negativo de waterfall y barras divergentes; nunca verde/rojo de estado. `MonthlyStatusChart.tsx` se borró en VIZ-06/VIZ-07 (DEC-39): todos los gráficos son de la familia `ChannelChart`. Con series 1 y 2 en el mismo gráfico, distinguirlas además por leyenda directa o etiqueta (violeta e índigo son cercanos para daltonismo).

**Chips de meta y semáforo.** Tres chips pill con dot + texto (nunca solo color): «en meta» (`--chip-ok-*`, verde), «lejos de meta» (`--chip-off-*`, rojo), «sin meta» (`--chip-none-*`, neutro). Texto ≥ 4,5:1 sobre su fondo en ambos temas. Delta vs período anterior: `--delta-up` / `--delta-down` / `--delta-flat` (texto ≥ 4,5:1 sobre superficie) con flecha ▲ ▼ ▬ y texto «sube/baja/sin cambio». Semáforo semántico: `--status-paid`, `--status-rejected`, `--status-pending` ≥ 3:1 como marca.

**Tarjeta KPI destacada.** `--kpi-hero-bg` (#2e2a8f claro / #3b3fbf oscuro), texto `--kpi-hero-text` y subtexto `--kpi-hero-muted` ≥ 4,5:1, barra `--kpi-hero-fill` sobre `--kpi-hero-track`. Máximo 1–2 por pantalla. Todas las razones de contraste las vigila `frontend/src/designTokens.test.ts`.

**Superficies, primario y acción azul-gris / azul (D27).** Tonos tomados de la imagen de inspiración (contenido blanco y azul-gris muy claro, enlaces y acciones en azul). Todos los pares de texto cumplen ≥ 4,5:1 y las marcas de acción ≥ 3:1; los vigila `frontend/src/designTokens.test.ts` (bloque «D27»).

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--bg-base` | #f3f5fa | #101626 | fondo de la página |
| `--bg-surface` | #ffffff | #182036 | tarjetas, tablas, diálogos |
| `--bg-hover` / `--bg-muted` / `--bg-filter` | #e3e8f4 / #e8ecf6 / #eef1f9 | #232d4a / #1c2540 / #182036 | hover, relleno neutro, paneles de filtro |
| `--border` / `--border-light` / `--border-subtle` | #cbd2e3 / #d8deed / #e3e7f2 | #2a3555 / #232c48 / #1d2540 | bordes |
| `--text-1` / `-2` / `-3` | #131a2e / #475270 / #5a6584 | #dde4f5 / #9aa7c7 / #7d8bb0 | texto (≥ 4,5:1 sobre superficie y fondo) |
| `--color-primary` | #1a5cae | #2f6fc4 | botón primario, pestaña activa (texto `--text-on-primary` #f4f7ff ≥ 4,5:1) |
| `--color-accent` | #1f6fc1 | #5aa2ee | foco, subrayado de pestaña, hover (≥ 3:1) |
| `--link-color` | #1565b0 | #6fb0f2 | enlaces y botones de texto (≥ 4,5:1) |

El acento azul señala interacción: hover, focus ring, botón primario, pestaña activa, enlaces. No usarlo como decoración — solo para estados interactivos o alertas de acción positiva. En modo oscuro escala a #5aa2ee para mantener contraste sobre fondos oscuros. El panel de sincronización destacado usa `--bg-accent-panel` (#1c2a5a claro / #182036 oscuro).

Los colores semánticos (success/warning/error) son independientes del acento. El éxito es #196b40 (verde), nunca el azul de acción.

## Typography

**Cabinet Grotesk** (Fontshare, Indian Type Foundry): display y encabezados de página. Geometric grotesque con letterforms ligeramente más amplias que Inter. Da solidez sin corporativismo. Uso exclusivo en heading (h1–h3): 22px/700, 17px/600, 14px/600. No usar para body ni labels.

**General Sans** (Fontshare): body, UI, labels, table content, form fields. Clean, con precisión casi mecánica en tamaños pequeños. Reemplaza Inter en todos los roles de text-rendering. Pesos 400 y 600.

**JetBrains Mono** (Google Fonts): TODOS los valores que vienen de la base de datos. RUTs, IDs de suscripción, montos, timestamps, códigos de proveedor, hashes. Esto no es estilo — es semántica: el mono indica "este valor vino del sistema, no fue tipeado". 13px regular para celdas de tabla, 11px para timestamps secundarios.

Carga: Fontshare via `<link href="https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@variable,general-sans@variable&display=swap">`. Google Fonts para JetBrains Mono. Fallbacks: system-ui para display/body, Courier New para mono.

## Layout

Sidebar azul marino (D1) como **rail compacto** (2026-11-13): 64px de íconos (`--sidebar-w`) que se despliega a 272px (`--sidebar-w-open`) al pasar el mouse (intención de 150ms; se repliega 200ms después de salir) superpuesto al contenido, sin moverlo, con una sombra (`--sidebar-float-shadow`). «Mantener menú abierto» (dentro del panel de cuenta, `role="menuitemcheckbox"` y `aria-checked`) lo fija abierto y entonces sí reserva los 272px; la preferencia se recuerda por navegador (`localStorage` `crm-sidebar-pinned`, con try/catch). En compacto se muestran los iconos de las secciones; sus hijos permanecen ocultos, el foco de teclado muestra un tooltip con el nombre, y el buscador, la salud y «Detalle por canal» despliegan el rail mientras el foco siga dentro (Esc lo vuelve a compactar). Íconos SVG propios de trazo 1.75 en `currentColor` (`frontend/src/components/sidebarIcons.tsx`, decorativos), uno distinto por entrada. En móvil sigue siendo el drawer, siempre desplegado. Contenido principal fluid, max-width 1160px. Padding lateral 24px en desktop, 16px en mobile.

**Legibilidad del menú (2026-11-18).** Marca y búsqueda permanecen arriba; salud y navegación comparten una única zona con scroll visible en escritorio, sin comprimir grupos ni filas. El pie queda fijo con un solo boton de cuenta (avatar y nombre; solo avatar en rail). Al pulsarlo se abre arriba un panel con las cuatro acciones: fijar menu, tema, perfil y salir. Ancho abierto 272px; móvil hasta 288px con margen de 24px respecto al viewport, alto dinámico 100dvh y acciones táctiles de 44px. En rail se oculta la barra visual para conservar los 40px de contenido de los iconos; el desplazamiento por rueda y teclado sigue disponible.

**Navegación del menú: secciones desplegables (UI-LOCAL-03, 2026-11-18).** Por solicitud del usuario, sustituye la presentación plana de UX-05/D29. Un acordeón por nivel permite abrir o cerrar una sección pulsando su encabezado. Estructura, de arriba abajo:

1. **Encabezado fijo:** marca (`Sx SynkmetriX`, lleva a Resumen) y **buscador** (filtra por rotulo o grupo, sin tildes ni mayusculas; con texto activo muestra coincidencias del detalle por canal). El **indicador global de salud** inicia la zona desplazable: punto con el peor nivel de los canales y resumen; al abrirlo muestra cada canal y su antiguedad, usando `GET /api/v1/sync-runs/health`. Sin datos no se pinta.

2. **Secciones** con icono y flecha de apertura (14px/600, fuente de cuerpo, `--sidebar-heading`); hijos con sangría y guía vertical. Solo una sección abierta por nivel; pueden cerrarse todas. Dashboard conserva acceso directo (ruta /central/resumen). La sección de la pantalla actual se abre al navegar; puede cerrarse manualmente. La búsqueda abre las coincidencias y al limpiarla restaura la expansión anterior. Enter/Espacio alternan, flecha derecha abre y flecha izquierda cierra el nivel y devuelve el foco a su encabezado.
   - *(sin etiqueta)* **Dashboard** (`/central/resumen`)
   - **Cartera:** Socios (`/central/clientes`, clientes consolidados), Suscripciones (`/central/suscripciones`, consolidadas), Cobros (`/central/cobros`, cobros y pagos de todos los canales, UX-09)
   - **Operación:** Recuperador (`/general/recuperador`; la ruta vieja `/virtualpos/recuperador-socios` redirige), Cambios de cobro (`/general/cambios-de-cobro`), Bajas (`/general/bajas`, con el permiso `subscriptions.cancellation.view`)
   - **Sistema:** Sincronización (`/admin/sincronizaciones`), Administración (`/admin/usuarios`), Reportes (`/central/reporte-automatico`)
3. **Detalle por canal:** sección con subacordeones VirtualPOS, Toku, Payku y TCH. Un proveedor abierto a la vez muestra sus pantallas disponibles; conserva permisos y rutas. Al navegar directamente a un canal se abren su sección y proveedor. Se omiten el rótulo «Transitorio» y el aviso técnico de retirada para mantener la navegación limpia; esto no implica retirar vistas ni cerrar el trabajo futuro de unificación.
4. **Pie:** boton de cuenta con avatar e indicador de apertura. El panel solo se monta al abrirlo y contiene Mantener menu abierto, modo claro/oscuro, Mi perfil y Cerrar sesion. Se cierra al seleccionar, pulsar fuera o Escape; las flechas e Inicio/Fin recorren las acciones. Escape devuelve foco al boton; en movil el primer Escape cierra el panel y el segundo cierra el drawer. Colores desde tokens de superficie/texto del tema activo; el panel se dibuja fuera de la zona recortada del rail.

Cada ítem de grupo se muestra solo con su permiso (`dashboard.view`; `virtualpos.recovery.view`; `virtualpos.billing_changes.view`; `sync_runs.view` o `sync.run`; `users.manage` o `roles.manage`); un grupo sin ítems visibles desaparece. Las vistas unificadas conservan los filtros por canal disponibles.

**Fuera del menú a propósito (no se inventan vistas):** *Identidad* (Operación; cola de candidatos, UX-11). *Cobros* ya entró en Cartera con UX-09. Cuando existan se agregan a `menuGroups` en `frontend/src/navigation.ts`. Las rutas no cambian con el rediseño del menú: solo se reagrupan y renombran (Resumen→Dashboard para la vista general, Clientes→Socios en Cartera, Reporte automático→Reportes, Recuperador de Socios→Recuperador); las rutas viejas (p. ej. `/virtualpos/cambios-de-cobro`) siguen redirigiendo con `legacyRedirectPath`. El ítem activo lleva `aria-current="page"` además del peso 700 y el fondo.

**Orientación de páginas (UX-LOCAL-01, 2026-11-18).** Los destinos principales comparten nombres entre el catálogo del menú y los encabezados mediante `pageLabels.ts`. Administración y Sincronización mantienen un h1 estable; Usuarios, Roles y Programación y estado son secciones h2. Los resúmenes por canal conservan el nombre Resumen y se distinguen del Dashboard general por su contexto. Los clientes de proveedor conservan Clientes; Socios identifica la cartera general.

Una ruta de navegación encima del contenido muestra la jerarquía, por ejemplo Dashboard / Cartera / Socios o Dashboard / Detalle por canal / Toku / Clientes / Detalle de cliente. Los grupos sin pantalla propia son texto; los destinos existentes y autorizados son enlaces reales. La página actual lleva aria-current=page. Clic normal navega en la SPA; modificadores conservan las acciones nativas del navegador. Rutas directas, enlaces antiguos e historial conservan su comportamiento y URLs. Los detalles internos de TCH solo enlazan destinos que ya existen; no se crean URLs con RUT, nombres o correos. El título de pestaña refleja página y proveedor, sin atributos personales ni identificadores de fichas. En móvil la ruta permite saltos de línea y reserva espacio bajo el botón de menú. El panel de cuenta conserva su diseño y acciones.

Tablas full-width dentro del área de contenido, sin max-width propio. Altura de fila: 38px (padding 9px top+bottom). Sticky header con background surface-alt. Alternancia de row: solo en hover — no zebra estática que distrae.

**Búsqueda y tablas de Cartera (UX-LOCAL-02, 2026-11-18).** Socios, Suscripciones y Cobros comparten búsqueda principal, canal y exportación. Buscar usa todos los campos soportados por defecto; Más filtros agrupa el campo específico, estado y criterios propios (resultado/fechas en Cobros). Cerrar el grupo conserva sus valores; los chips activos quedan fuera y permiten quitar criterios o limpiarlos todos. Borrar búsqueda devuelve el foco al campo y conserva los demás filtros. El texto buscado permanece fuera de URL y almacenamiento persistente.

PortfolioTable permite elegir columnas y restaurar la vista inicial. Socios fija RUT/nombre; Suscripciones fija ID/socio; Cobros y Pagos fijan su ID. Fechas adicionales, estado secundario y referencias secundarias se ofrecen bajo Columnas. La preferencia se guarda por vista bajo synkmetrix:list-columns:v1, solo con nombres de columnas; no contiene filas ni criterios de búsqueda. No altera la exportación. El scroll de la tabla tiene foco de teclado, encabezado fijo y montos alineados a la derecha; en móvil permanece dentro de la página.

Al cambiar una consulta se muestran indicadores de carga y se bloquea exportar hasta que llegue el resultado correspondiente. Errores, falta de permisos, ausencia de registros y ausencia de coincidencias tienen mensajes diferentes; los errores permiten reintentar y una búsqueda vacía de coincidencias permite quitar criterios. Las respuestas canceladas no reemplazan una consulta nueva y Socios separa los datos por usuario de sesión. Se conserva paginación en servidor de 50 registros, con controles deshabilitados durante carga y retorno a Primera página. El análisis de rechazo queda después del listado de Cobros y explicita que usa canal/fechas, conservando su definición.

Stats cards en grid de 4 columnas (desktop), 2 en tablet, 1 en mobile. Gap 12px. Sin aspect-ratio forzado.

En mobile el menú es un drawer (hamburguesa, velo, Esc y clic fuera cierran, foco atrapado); buscador, indicador de salud y cabecera del grupo transitorio miden 44px de alto. Salud y lista comparten una zona de scroll; marca, búsqueda y pie permanecen visibles.

## Elevation & Depth

Shadow card: `0 1px 3px rgba(23,32,74,.08), 0 0 0 1px rgba(23,32,74,.04)` — offset mínimo + ring tenue. En dark mode: `0 1px 3px rgba(0,0,0,.3), 0 0 0 1px rgba(255,255,255,.04)`.

No zero-offset colored shadows. No glow halos. La profundidad viene del borde sutil, no de la sombra agresiva.

Cards elevadas (modales, drawers): `0 3px 12px rgba(23,32,74,.10), 0 0 0 1px rgba(23,32,74,.04)`.

## Shapes

- `--r1: 4px` — micro (inputs, tags inline)
- `--r2: 6px` — UI base (botones, inputs, nav items)
- `--r3: 10px` — contenedores (cards, table wrapper, mockup container)
- `--full: 9999px` — badges/pills de estado

Radio interno de un elemento dentro de un card: `outer_radius - gap`. Un card con r3 (10px) y padding 12px tiene elementos internos con r2 (6px). No anidar cards.

## Components

**Cabecera del Dashboard (2026-11-18):** Un titulo, mes mostrado como subtitulo y una fila independiente de filtros Mes / Canales. Casillas sencillas, sin chips. El mes en curso se explica en un aviso breve con acceso al ultimo mes cerrado. Actualizacion de datos usa un desplegable con resumen de incidencias; estados de canal y hora de generacion se consultan dentro. La hora de generacion no representa frescura de origen. En movil el titulo deja espacio al boton del menu. Mantener definiciones de KPI y acciones existentes.

**Botones:** Tres variantes: primary (`--color-primary` bg, `--text-on-primary`), secondary (accent-sub bg, accent text), ghost (transparent bg, border). Destructive (error-bg, error text). Todos con `border-radius: var(--r2)`. Disabled siempre con `opacity: 0.45`, cursor `not-allowed`.

**Badges de estado:** Cuatro variantes semánticas (ok/warning/error/neutral) + dot indicador de 5px. Font-size 11px / weight 600. Siempre pill (`border-radius: 9999px`). Padding 2px 8px. No usar el color del badge como único indicador — siempre acompañar con texto o dot.

**Channel tags:** Font-size 10px / JetBrains Mono / background surface-alt / border color. Pequeños y discretos — son metadata, no foco.

**Inputs:** Border 1px solid `--border`. Focus ring: anillo azul de 3px con `--color-accent` al 12–35 % + border-color `--color-accent`. Mono variant para valores de datos (RUT, monto). Labels: 10px / 600 / uppercase / text-label.

**Tables:** Ver Layout. Header en caps pequeñas. TD con `font-variant-numeric: tabular-nums` en todas las columnas numéricas. Columnas de monto: `text-align: right`. Hover de fila: `background: var(--surface-alt)` — no shadow, no scale.

**Detalle por canal (2026-11-18):** Los listados aprovechan el ancho y alto disponibles, con cabecera compacta y filas desplazables dentro de la tabla. El encabezado permanece visible; los filtros por columna de VirtualPOS arrancan plegados, conservan sus valores al cerrar y muestran un contador de criterios activos. Se usa solo el scroll nativo, con barras contrastadas y foco de teclado. Por solicitud del usuario se retiran de estas vistas la ruta visual, el retorno al resumen y los botones de cuenta Todas / VP 1 / VP 2. El menú conserva el acceso a secciones y resúmenes; los enlaces profundos existentes mantienen su cuenta. En móvil o con poca altura la página permite alcanzar los controles. Las fichas tienen tablas relacionadas de altura limitada y los resúmenes analíticos conservan su recorrido completo. Sin dependencias nuevas.

**Alert banner:** Solo para estados que requieren acción. Warning bg + border + icono de info. Texto breve, link "Ver →" a la derecha.

**Sidebar:** Siempre fondo `--bg-sidebar` (azul marino). Secciones interactivas de 14px/600 con icono, flecha y `aria-expanded`; paneles cerrados con `hidden`. Ítems con hover `--sidebar-hover-bg`; activo en `--sidebar-active-bg` + `--sidebar-active-text` + peso 700 + `aria-current`. Buscador sobre `--sidebar-active-bg`, salud global y acordeones por proveedor dentro de «Detalle por canal». Pie con botón de cuenta y panel de acciones al pulsarlo. Ver Layout.

**KPI card (v2).** Superficie normal con borde sutil (sin borde lateral de color, sin cards anidadas). Etiqueta, valor en JetBrains Mono (`—` con texto accesible «sin datos» si no hay dato), `delta` vs mes anterior con flecha y color semántico, chip de meta, barra de progreso hacia la meta (con `role="progressbar"` y texto «X % de la meta»), sparkline opcional (decorativo, `aria-hidden`; la tendencia va en texto). Variantes: `normal` y `destacada` rellena (máx. 1–2 por pantalla). Churn (D20): tarjeta con chip, meta y sparkline, no velocímetro.

**Gráficos de evolución.** Barras apiladas por fuente con meta punteada (`--chart-ref`), línea acumulada vs ritmo meta vs proyección, eje en porcentaje cuando se pide, un único tooltip con total y % de la meta, botón «Ver datos» que alterna a una tabla accesible equivalente, selector de rango «Últimos 12 meses / Año / Todo».

**Sistema único de gráficos (sprint VIZ, DEC-34).** Librería: **Recharts 3** (MIT), la única del proyecto; se amplía `ChannelChart` en lugar de sumar otra (DEC-34 A). Medido en el build: `vendor-charts` 408,43 kB (115,07 kB gzip) y `ChannelChart` 18,8 kB (7,1 kB gzip); el sprint no agrega dependencias. Familia:

| Pregunta (matriz KPI a gráfico) | Componente | Uso actual |
|---|---|---|
| Tendencia | `ChannelChart` `line` / `area` / `bar` / `stacked` | cobros, cargos por estado, socios, churn mensual (`mode="percent"`) |
| Ganar o perder socios | `ChannelChart` `diverging` (+ `overlayLine` de neto) | altas arriba en `--flow-in`, bajas abajo en `--flow-out` |
| Variación del mes | `ChannelChart` `waterfall` | «Crecimiento real mensual» |
| Reparto de cartera | `ChannelChart` `stacked100` (o tabla si hay más de 6 estados) | disponible |
| Ranking | `RankingChart` (barras horizontales ordenadas) | canales, motivos de rechazo |
| Valor con contexto | `KpiCard` / `ChurnKpiCard` | churn sin meta (DEC-38): chip «sin meta», sin barra |

Reglas comunes: tooltip único (`ChartTooltipContent`), valores en JetBrains Mono, «Ver datos» con tabla equivalente, y **teclado**: el gráfico es una sola parada de Tab (el contenedor `.chart-plot`; la capa de Recharts va apagada), ←/→ recorren los meses, Inicio/Fin van al primero y al último, Escape suelta; el mes elegido se marca con una línea `--color-accent` y se lee en una región `aria-live`. El modelo puro vive en `components/chartModel.ts`. No se grafican LTV, salud de sincronización ni alertas.

## Interaction States

| Componente | Loading | Empty | Error | Success |
|---|---|---|---|---|
| Dashboard — stat cards | Skeleton rect 60px alto, animated pulse | Mostrar "—" en mono, sin texto adicional | Badge rojo + tooltip con mensaje | — |
| Dashboard — tabla suscripciones | Skeleton rows (5 rows de altura fija) | "No hay suscripciones recientes." + link a canal relevante | Alerta inline roja, botón reintentar | — |
| OperationalAlerts | Spinner small 16px inline | **No retornar null** — mostrar estado positivo: "Sin alertas operativas" + ícono check verde + "Última sync: hace Xh" | Badge rojo en panel header | Badge verde cuando se resuelve |
| Sincronización — botón | Spinner replace texto + disabled | — | Toast error con mensaje del proveedor | Toast success "Sync completada" |
| Identidad — cola | Loading inline | "Sin candidatos pendientes. Todos revisados." | Mensaje de error + reload | — |

**Reglas de estado:**
- Loading skeletons siempre en `--surface-alt` background, sin border
- Empty states incluyen una acción: link, botón o instrucción — nunca solo texto
- Errores de proveedor externo: mostrar canal + código de error en JetBrains Mono 11px
- No usar spinners globales de pantalla completa — siempre loading inline en el componente afectado

## Do's and Don'ts

**Do:**
- Usar JetBrains Mono para cualquier valor que venga de la base de datos
- Mantener la sidebar en `--bg-sidebar` (azul marino) en ambos modos — es el ancla de identidad
- Usar `--series-N` para series de gráficos (violeta/índigo primero) y validar ≥ 3:1 de marcas y ≥ 4,5:1 de texto
- Señalar estado con badge + dot + texto (nunca solo color)
- Usar `font-variant-numeric: tabular-nums` en columnas de tabla numéricas
- Mantener el dark mode azul-gris propio (D27) — no copiar paletas de otras herramientas

**Don't:**
- No usar Inter como fuente en ningún rol — Cabinet Grotesk y General Sans la reemplazan completamente
- No usar el acento azul como decoración — solo estados interactivos y acción positiva
- No anidar cards (card dentro de card)
- No usar sombras de borde de color lateral en cards
- No usar `rgba(0,0,0,.X)` para bordes — usar los tokens `--border` y `--border-subtle`
- No mostrar números de base de datos en DM Sans/General Sans — siempre mono

## Motion

- **Approach:** Minimal-functional — solo transiciones que ayudan a la comprensión
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50–100ms) short(150–200ms)
- **Menú rail (2026-11-13):** ancho del panel (200ms, fuera del flujo: no hay reflujo del contenido), opacidad + desplazamiento de 6px de los rótulos (180–200ms), giro del chevron de «Detalle por canal», entrada del submenú y del tooltip con opacidad + desplazamiento (150–200ms). Con `prefers-reduced-motion` (o `data-motion="reduced"` en el aside) no hay transiciones ni animaciones.
- **El único momento coreografiado:** el indicador de sincronización activa (spinner en el botón Sincronizar + badge pulsante). Todo lo demás es transición de estado pura.

Respetar `prefers-reduced-motion`: desactivar todas las transiciones CSS bajo ese media query.

## Decisions Log

| Fecha | Decisión | Razón |
|---|---|---|
| 2026-10-21 | Sistema de diseño inicial creado | /design-consultation — contexto: CRM nonprofit, claridad + confiabilidad + eficiencia |
| 2026-10-21 | Sidebar en brand teal en modo claro | Riesgo elegido: diferencia a SynkmetriX de herramientas con sidebar gris; señala "panel de control" |
| 2026-10-21 | JetBrains Mono para todos los datos | Semántica visual: mono = valor del sistema, sans = contenido editorial |
| 2026-10-21 | Dark mode derivado del teal | El dark mode anterior pedía prestado a GitHub Dark; ahora tiene identidad propia |
| 2026-10-21 | Cabinet Grotesk + General Sans (Fontshare) | Display + body con identidad; reemplazan Inter completamente. Preview proxy: Barlow + DM Sans |
| 2026-10-21 | Nav sidebar expandible por proveedor (2 niveles) | Nav plana de 6 ítems era mockup ilustrativo — la nav real usa grupos colapsables por canal |
| 2026-10-29 | D29 / UX-05: menú de UN SOLO NIVEL con grupos Resumen · Cartera (Socios, Suscripciones) · Operación (Recuperador, Cambios de cobro) · Sistema (Sincronización, Administración, Reportes); salud de canal pasa a un indicador global en el encabezado; buscador que filtra el menú; las pantallas por canal quedan en el grupo plegado y transitorio «Detalle por canal» | Decisión del usuario (D29). Revierte «Nav sidebar expandible por proveedor (2 niveles)» (2026-10-21). Cobros e Identidad fuera del menú hasta que existan sus vistas (UX-09, UX-11); el detalle por canal se retira con UX-09 a UX-11. Rutas sin cambios (solo reagrupar y renombrar). Sin íconos en esta tanda |
| 2026-10-29 | D1: sidebar azul marino oscuro (#111727 claro / #0a0f1c oscuro; activo #242a38) en lugar de teal | Decisión del usuario, a partir de docs/dashboardeinspiracion.png. Revierte la decisión del 2026-10-21 «Sidebar en brand teal». El teal sigue siendo primario/acento interactivo fuera del menú |
| 2026-10-29 | D19: paleta de series violeta e índigo (`--series-1..6`, con verde, azul y rosa como categorías extra), marcas ≥ 3:1 en claro y oscuro | Decisión del usuario (imagen de inspiración); cierra DEC-36 en lo cromático. Hex oscurecidos donde el original no pasaba 3:1 sobre blanco |
| 2026-10-29 | D20: churn como tarjeta KPI con chip, meta y sparkline (no velocímetro) | Decisión del usuario; alineado con el tablero de la jefatura |
| 2026-10-29 | D9: los cambios se avisarán por SSE | Decisión del usuario; sin cambios de diseño por ahora (se implementa aparte) |
| 2026-10-29 | Chips de meta, delta, tarjeta KPI destacada y gráficos de evolución especificados (UX-01/02/03) | Referencia: tablero de la jefatura. Texto ≥ 4,5:1, marcas ≥ 3:1 |
| 2026-10-29 | D27: se migran TAMBIÉN las superficies del contenido, el color primario y el color de acción (botones, enlaces, foco) a azul-gris y azul, en claro y oscuro; los gráficos antiguos pasan a `--series-N` | Decisión del usuario, a partir de docs/dashboardeinspiracion.png. Revierte «Dark mode derivado del teal» (2026-10-21) y el primario/acento teal; cierra las dudas abiertas 1, 2 y 5. Texto ≥ 4,5:1 y marcas ≥ 3:1 vigilados por `designTokens.test.ts`. Pendiente: `--accent-primary`/`--accent-secondary` de Staging.css no están definidos (preexistente) y los tonos de `metric-dot` y badges siguen fijos |
| 2026-11-02 | DEC-34: Recharts 3 como única librería y `ChannelChart` ampliado (porcentaje, teclado, divergente, 100 %, waterfall) más `RankingChart` | Decisión del usuario (ficha d109). Sin dependencias nuevas; ver «Sistema único de gráficos» |
| 2026-11-02 | DEC-36: altas en azul (`--flow-in`) y bajas en naranja (`--flow-out`) | Decisión del usuario; par seguro para daltonismo y distinto de los estados rechazado (rojo) y cancelado (gris). Cierra UI-33 |
| 2026-11-02 | DEC-37/DEC-38: churn con la misma definición en los cuatro canales (D31) y tarjeta D20 sin meta | Decisión del usuario; el chip dice «sin meta» hasta que existan metas |
| 2026-11-02 | DEC-39: borrado `MonthlyStatusChart.tsx` (incluye `TransactionsVsSubscriptionsChart`, con doble eje Y, y `MonthlySimpleChart`) | Decisión del usuario; código muerto o reemplazado por la familia `ChannelChart` |
| 2026-11-02 | Títulos de grupo del menú resaltados: de 9px/800 `--sidebar-label` (7,9:1) a 11px/700 Cabinet Grotesk `--sidebar-heading` (14,6:1), con separador sutil y más aire arriba | Pedido del usuario tras revisar el sandbox («a los títulos como Cartera y Operación los resaltaría más»). Ancho de 220px sin cambios |
| 2026-11-13 | Menú lateral como rail compacto con íconos: 64px que se despliega por hover y se puede fijar abierto (recordado por navegador); grupos Cartera/Operación/Sistema con encabezados que en compacto quedan como raya; «Detalle por canal» con chevron y «Transitorio» como antetítulo; tooltips por teclado en compacto; drawer en móvil | Pedido del usuario («está muy grande; que sea compactable y se abra al poner el mouse encima; algo moderno»). Revierte «Sidebar fijo de 220px» y el «Sin íconos en esta tanda» de D29; rutas, grupos y permisos sin cambios. Íconos SVG propios (sin dependencia nueva) |
| 2026-11-07 | QA-07 (L8-QA): el Resumen sigue abriendo en el mes en curso, pero con el aviso «Mes en curso, al día X: datos parciales» y un botón «Ver el último mes cerrado». En el mes en curso las tarjetas de flujo (ingreso, acumulado del año, activaciones, bajas, crecimiento neto, churn, no cobrado, por cobrar) no muestran variación contra el mes anterior; los stocks y razones (socios, cobrabilidad, MRR, ARPU) sí | Opción A de las dos del informe de QA: abrir en el último mes cerrado escondía el mes que la jefatura sigue día a día. Comparar unos días contra un mes completo dibujaba caídas que no ocurrieron |
| 2026-11-07 | QA-08 (L8-QA): RUT con un solo formato `12.345.678-9` (puntos es-CL y guion) en JetBrains Mono en todas las vistas y en los CSV (`features/shared/rut.ts`, `RutCell.tsx`, `exporter.format_rut`); lo que no tiene forma de RUT o trae un dígito verificador incorrecto se muestra tal cual con la marca «no válido» (texto, no solo color) | Cada canal entregaba el RUT a su manera (`197292059`, `19780113-1`, `42.000.150-9`) y Socios lo pintaba en General Sans bold |
| 2026-10-21 | Estados UI especificados en tabla (tabla Interaction States) | Empty states son features: OperationalAlerts con null-return → estado positivo con warmth |

## Design Review Completion Summary

```
+====================================================================+
|         DESIGN PLAN REVIEW — COMPLETION SUMMARY                    |
+====================================================================+
| System Audit         | DESIGN.md presente, frontend sin alinear    |
| Step 0               | Rating inicial 3/10 — 6 brechas críticas    |
| Pass 1  (Info Arch)  | 5/10 → 8/10 — nav documentada              |
| Pass 2  (States)     | 4/10 → 8/10 — tabla de estados agregada     |
| Pass 3  (Journey)    | 6/10 — sin issues nuevos                    |
| Pass 4  (AI Slop)    | 7/10 — OPERATE, sin rechazos duros          |
| Pass 5  (Design Sys) | 2/10 → 9/10* — 6 brechas aprobadas T1-T6   |
| Pass 6  (Responsive) | 5/10 — mobile existe en código, sin issues  |
| Pass 7  (Decisions)  | 2 resueltos, 0 diferidos                    |
+--------------------------------------------------------------------+
| NOT in scope         | 3 items                                     |
| What already exists  | documentado                                 |
| TODOS.md updates     | 0 diferidos — todo en tareas T1-T6          |
| Approved Mockups     | 0 (DESIGN_NOT_AVAILABLE — no OpenAI key)    |
| Decisions made       | 2 añadidas al plan                          |
| Decisions deferred   | 0                                           |
| Overall design score | 2/10 → 7/10 (Pass 5 sube post-implementación)|
+====================================================================+
```
*Pass 5 sube a 9/10 una vez implementadas T1–T6.

## GSTACK REVIEW REPORT

| Review | Trigger | Por qué | Runs | Status | Findings |
|--------|---------|---------|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & estrategia | 0 | — | — |
| Outside Review | — | Segunda opinión independiente | 0 | — | — |
| Eng Review | `/plan-eng-review` | Arquitectura & tests | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | issues_open | score: 2/10 → 7/10, 2 decisiones |
| DX Review | `/plan-devex-review` | Developer experience | 0 | — | — |

**VERDICT:** Design Review completa — 6 brechas aprobadas para implementación. eng review required antes de ship.

**Dudas abiertas para el usuario (2026-10-29), NO aplicadas:**
1. ~~Superficies oscuras en teal~~ y 2. ~~acento teal~~: resueltas por D27 (2026-10-29), ver Decisions Log.
3. ~~Layout con navegación de 2 niveles por proveedor~~: reescrito en UX-05 (un solo nivel, D29), ver Layout y Decisions Log.
4. Título «hero» grande (DEC-41) y encabezado marino de página (C1/C4/C6 de la auditoría): sin aplicar.
5. ~~Colores de canal y de MonthlyStatusChart~~: migrados a `--series-N` / `--status-*` (D27). ~~DEC-36 (color de altas/bajas)~~: resuelta el 2026-11-02, altas `--flow-in` (azul) y bajas `--flow-out` (naranja).
