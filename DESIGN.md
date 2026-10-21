---
# gstack: design-md-format=spec
name: SynkmetriX
description: "Registro industrial — herramienta operativa teal oscuro, datos en mono, confiabilidad como norte visual."
colors:
  primary: "#1a3d47"
  on-primary: "#f0f8f6"
  surface: "#ffffff"
  text: "#111e22"
  text-muted: "#4a6168"
  accent: "#2a7a64"
  success: "#196b40"
  warning: "#7a5200"
  error: "#8b3030"
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
    backgroundColor: "#226655"
  input:
    borderColor: "#cdd8d5"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  nav-link:
    textColor: "#7ca8a0"
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
- Sidebar en brand teal (#1a3d47) en modo claro: señal de "estoy en la herramienta", no decoración
- Todos los datos numéricos en JetBrains Mono — RUTs, IDs, montos, timestamps; los datos se leen como datos
- Dark mode derivado del teal — no préstamo de GitHub Dark
- Tablas first-class: filas de 38px, header en caps pequeñas, hover suave
- Sin decoración: ni blobs, ni íconos en círculo de color, ni sombras agresivas

## Colors

**Strategy:** Committed — el teal profundo (#1a3d47) es dueño de la marca. Los neutrales tienen base azul-verde, no gris puro.

**Light or dark:** Ambos modos definidos. La sidebar siempre en brand teal (en modo oscuro deriva a #091418 — todavía más oscuro que el bg de base). No invertir ingenuamente: el modo oscuro tiene su propia paleta derivada del teal, verificada para contraste.

El acento (#2a7a64) señala interacción: hover, focus ring, botón primario, nav item activo. En dark mode escala a #3a9d7e para mantener contraste sobre fondos oscuros. No usar el acento como decoración — solo para estados interactivos o alertas de acción positiva.

Los colores semánticos (success/warning/error) son independientes del acento. No usar verde de acento para éxito — el éxito es #196b40, un verde más saturado y diferenciable.

## Typography

**Cabinet Grotesk** (Fontshare, Indian Type Foundry): display y encabezados de página. Geometric grotesque con letterforms ligeramente más amplias que Inter. Da solidez sin corporativismo. Uso exclusivo en heading (h1–h3): 22px/700, 17px/600, 14px/600. No usar para body ni labels.

**General Sans** (Fontshare): body, UI, labels, table content, form fields. Clean, con precisión casi mecánica en tamaños pequeños. Reemplaza Inter en todos los roles de text-rendering. Pesos 400 y 600.

**JetBrains Mono** (Google Fonts): TODOS los valores que vienen de la base de datos. RUTs, IDs de suscripción, montos, timestamps, códigos de proveedor, hashes. Esto no es estilo — es semántica: el mono indica "este valor vino del sistema, no fue tipeado". 13px regular para celdas de tabla, 11px para timestamps secundarios.

Carga: Fontshare via `<link href="https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@variable,general-sans@variable&display=swap">`. Google Fonts para JetBrains Mono. Fallbacks: system-ui para display/body, Courier New para mono.

## Layout

Sidebar fijo de 220px en brand teal. Contenido principal fluid, max-width 1160px. Padding lateral 24px en desktop, 16px en mobile.

**Navegación sidebar (estructura real):** dos niveles — nivel 1: ítems planos (Dashboard, Clientes, Suscripciones, Reporte); nivel 2: grupos de proveedor expandibles/colapsables (VirtualPOS, Toku, Payku, TCH) con sus sub-secciones (Suscripciones, Cobros, Socios, Intentos fallidos por proveedor). Administración como grupo separado (Usuarios, Sincronización). El sidebar del preview en el artifact es ilustrativo — la nav real usa expandibles. Section labels en 9px/600/uppercase.

Tablas full-width dentro del área de contenido, sin max-width propio. Altura de fila: 38px (padding 9px top+bottom). Sticky header con background surface-alt. Alternancia de row: solo en hover — no zebra estática que distrae.

Stats cards en grid de 4 columnas (desktop), 2 en tablet, 1 en mobile. Gap 12px. Sin aspect-ratio forzado.

Sidebar colapsa a top-bar en mobile con scroll horizontal para nav items.

## Elevation & Depth

Shadow card: `0 1px 3px rgba(26,61,71,.08), 0 0 0 1px rgba(26,61,71,.04)` — offset mínimo + ring tenue. En dark mode: `0 1px 3px rgba(0,0,0,.3), 0 0 0 1px rgba(255,255,255,.04)`.

No zero-offset colored shadows. No glow halos. La profundidad viene del borde sutil, no de la sombra agresiva.

Cards elevadas (modales, drawers): `0 3px 12px rgba(26,61,71,.10), 0 0 0 1px rgba(26,61,71,.04)`.

## Shapes

- `--r1: 4px` — micro (inputs, tags inline)
- `--r2: 6px` — UI base (botones, inputs, nav items)
- `--r3: 10px` — contenedores (cards, table wrapper, mockup container)
- `--full: 9999px` — badges/pills de estado

Radio interno de un elemento dentro de un card: `outer_radius - gap`. Un card con r3 (10px) y padding 12px tiene elementos internos con r2 (6px). No anidar cards.

## Components

**Botones:** Tres variantes: primary (accent bg, white text), secondary (accent-sub bg, accent text), ghost (transparent bg, border). Destructive (error-bg, error text). Todos con `border-radius: var(--r2)`. Disabled siempre con `opacity: 0.45`, cursor `not-allowed`.

**Badges de estado:** Cuatro variantes semánticas (ok/warning/error/neutral) + dot indicador de 5px. Font-size 11px / weight 600. Siempre pill (`border-radius: 9999px`). Padding 2px 8px. No usar el color del badge como único indicador — siempre acompañar con texto o dot.

**Channel tags:** Font-size 10px / JetBrains Mono / background surface-alt / border color. Pequeños y discretos — son metadata, no foco.

**Inputs:** Border 1px solid `--border`. Focus ring: `0 0 0 3px rgba(42,122,100,.12)` + border-color `--accent`. Mono variant para valores de datos (RUT, monto). Labels: 10px / 600 / uppercase / text-label.

**Tables:** Ver Layout. Header en caps pequeñas. TD con `font-variant-numeric: tabular-nums` en todas las columnas numéricas. Columnas de monto: `text-align: right`. Hover de fila: `background: var(--surface-alt)` — no shadow, no scale.

**Alert banner:** Solo para estados que requieren acción. Warning bg + border + icono de info. Texto breve, link "Ver →" a la derecha.

**Sidebar:** Siempre fondo `--sidebar`. Nav items con hover `rgba(255,255,255,.08)`. Active item en `--accent`. Section labels en 9px / 600 / uppercase / text-sidebar-muted. Footer con avatar y email del usuario.

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
- Mantener la sidebar en `--sidebar` (teal) en ambos modos — es el ancla de identidad
- Señalar estado con badge + dot + texto (nunca solo color)
- Usar `font-variant-numeric: tabular-nums` en columnas de tabla numéricas
- Derivar el dark mode del teal — no copiar paletas de otras herramientas

**Don't:**
- No usar Inter como fuente en ningún rol — Cabinet Grotesk y General Sans la reemplazan completamente
- No usar el acento verde como decoración — solo estados interactivos y acción positiva
- No anidar cards (card dentro de card)
- No usar sombras de borde de color lateral en cards
- No usar `rgba(0,0,0,.X)` para bordes — usar los tokens `--border` y `--border-subtle`
- No mostrar números de base de datos en DM Sans/General Sans — siempre mono

## Motion

- **Approach:** Minimal-functional — solo transiciones que ayudan a la comprensión
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50–100ms) short(150–200ms)
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

NO UNRESOLVED DECISIONS
