# Menu de cuenta del sidebar — 2026-11-18

## Comportamiento

Un solo boton de cuenta al pie: avatar y nombre del usuario autenticado en abierto, solo avatar en rail. Panel encima del boton, con exactamente cuatro acciones: Mantener menu abierto (checkbox con marca), modo claro/oscuro, Mi perfil y Cerrar sesion. No inventa vistas, preferencias de negocio ni llamadas nuevas.

El panel se monta solo al abrirlo y queda fuera del contenedor que recorta el rail. Se cierra al seleccionar una accion, pulsar fuera o Escape; el cierre exterior conserva el foco del destino. Escape devuelve foco al disparador. Enter/Espacio activan botones nativos, flechas/Home/End recorren opciones, Tab sale del panel. En movil el primer Escape solo cierra cuenta; el segundo cierra el drawer.

Las acciones conservan sus callbacks, rutas, persistencia de tema/fijado y logout con CSRF. Username procede de la sesion existente; los textos fijos estan en el catalogo de idioma. Colores por tokens en ambos temas.

## Validacion

- 148 pruebas pasan en Sidebar, rail/cuenta, navegacion de la app y contratos CSS/tokens. Incluye ocho casos nuevos de apertura, cierre, foco, teclado y ejecucion unica de acciones.
- Lint sin errores (avisos anteriores conservados) y build/TypeScript pasan.
- Chrome headless en CRM local autenticado: cuatro acciones visibles/clicables sin recorte en rail y escritorio, temas oscuro/claro, seleccion de tema, fijado, perfil, clic exterior y foco con teclado.
- Movil 390x700 y 320x480: limites del popup dentro del viewport, todas las acciones clicables y doble Escape para cuenta/drawer.
- Evidencia local ignorada: `.local/account-menu-dark.png`, `.local/account-menu-light.png`, `.local/account-menu-mobile-390.png`, `.local/account-menu-mobile-320.png`.
- Backend y bases no cambian. No se publican cambios a GitHub.
