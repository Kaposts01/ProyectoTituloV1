# Legibilidad del menu lateral — 2026-11-18

## Problema y cambio

La salud desplegada y cuatro filas fijas del pie dejaban la navegacion dentro de una franja pequena. El menu abierto pasa de 232 a 272px; las entradas principales usan 14px y no se comprimen. Marca y buscador permanecen arriba, salud y navegacion comparten una sola zona de desplazamiento, y el pie permanece visible con tema/perfil en dos columnas. Barra de scroll de escritorio contrastada; en rail compacto no quita espacio a los iconos. Drawer movil hasta 288px, 100dvh y controles tactiles de 44px.

No cambia rutas, permisos, datos ni peticiones de sincronizacion. Mantiene hover con intencion, fijado persistente, busqueda, foco, Escape, temas y movimiento reducido. DESIGN.md y los contratos CSS existentes reflejan el ancho y la nueva zona desplazable.

## Validacion

- 118 pruebas pasan: Sidebar, rail y tokens/diseno.
- Lint sin errores (advertencias anteriores conservadas); TypeScript y build pasan.
- Chrome real headless sobre el CRM local autenticado: alturas de escritorio 480, 600, 768 y 900px. Se verifican altura disponible de scroll, filas >=38px, pie dentro del viewport y que cada opcion enfocada se desplaza hasta ser visible.
- Rail de 64px conserva los iconos dentro de su ancho. Verificados ambos temas.
- Movil 390x700: detalle por canal abierto y ultimo elemento accesible, pie visible y Escape cierra el drawer.
- Las capturas solo incluyen el menu: `.local/sidebar-after-dark.png`, `.local/sidebar-after-light.png`, `.local/sidebar-after-compact.png`, `.local/sidebar-after-mobile.png` y `.local/sidebar-after-navigation.png`; evidencia geometrica en `.local/sidebar-layout-results.json`. Artefactos locales ignorados, sin datos personales.
- No se repitieron suites backend ni se migraron bases: el cambio se limita a presentacion del menu.

Rama local `codex/actualizacion-20261118`, sin push.
