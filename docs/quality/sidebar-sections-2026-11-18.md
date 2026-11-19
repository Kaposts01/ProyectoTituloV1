# Secciones desplegables del sidebar — 2026-11-18

## Comportamiento

Resumen permanece como acceso directo. Cartera, Operacion, Sistema y Detalle por canal se abren al pulsar su encabezado y despliegan sus opciones debajo. Detalle contiene un segundo nivel para VirtualPOS, Toku, Payku y TCH. Cada nivel permite un solo grupo abierto; volver a pulsar lo cierra. Iconos, flechas y sangria distinguen encabezados, proveedores y destinos.

La pantalla activa abre su seccion y proveedor al navegar, incluidas las rutas directas. El usuario puede cerrar manualmente la seccion actual; el encabezado conserva su indicacion activa. Buscar despliega las coincidencias y bloquea el cierre mientras hay texto; al limpiar se restaura la expansion anterior. Los permisos filtran entradas y grupos vacios como antes. Se conservan rutas y callbacks.

Los botones nativos exponen aria-expanded/aria-controls; paneles cerrados usan hidden y no reciben foco. Enter/Espacio alternan; derecha abre y izquierda cierra un nivel devolviendo foco a su encabezado. En rail, pulsar una seccion revela el menu. En movil los destinos cierran el drawer y los controles mantienen altura tactil de 44px.

Por solicitud explicita del usuario esta presentacion sustituye la navegacion plana documentada en D29. Se elimina del menu el aviso tecnico Transitorio; no se retiran vistas ni se modifica el alcance de la unificacion futura. El componente, las acciones y los estilos del menu de cuenta permanecen intactos.

## Validacion

- 155 pruebas pasan en Sidebar, rail/cuenta, navegacion de AppCore y contratos CSS/tokens. Incluyen exclusividad, cierre, cambio de pantalla, busqueda, proveedores, teclado y ausencia de seleccion central obsoleta en perfil.
- Lint sin errores, con avisos preexistentes fuera de este cambio; TypeScript y build pasan.
- Chrome local autenticado: secciones/proveedores exclusivos, busqueda y restauracion, rutas directas a Socios y transacciones TCH, teclado y popup de cuenta con cuatro acciones.
- Movil 390x700 y 320x480: seleccion y reapertura de la seccion actual, drawer y pie dentro del viewport. Capturas revisadas visualmente.
- Evidencia ignorada bajo .local: sidebar-accordion-closed.png, sidebar-accordion-cartera.png, sidebar-accordion-platform.png y sidebar-accordion-mobile-390.png / sidebar-accordion-mobile-320.png.
- Diff revisado sin cambios de backend, bases, credenciales, dependencias ni operaciones de proveedores. Sin push a GitHub.
