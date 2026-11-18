# Orientacion de paginas — 2026-11-18

## Entrega

Los nombres principales se comparten entre menu y encabezados mediante pageLabels.ts. Dashboard sustituye Resumen en la pagina general; Reportes, Recuperador, Administracion y Sincronizacion coinciden con sus accesos. Las secciones de usuarios, roles y programacion pasan a h2 bajo un h1 estable. Las listas y fichas de canal tienen h1 y mantienen sus datos y terminologia de origen.

PageBreadcrumbs muestra grupos, proveedor, listado y detalle. Los grupos sin destino son texto y los padres autorizados son enlaces reales con navegacion SPA. Conserva las acciones nativas con modificadores y marca la pagina actual con aria-current. Los enlaces de fichas internas TCH reabren explicitamente la lista, incluso cuando comparten la misma URL. No se crean rutas con atributos personales.

El titulo de pestana identifica pantalla/proveedor sin nombre, RUT ni identificador de registro. Los catalogos y guards existentes resuelven los destinos; no cambian URLs, permisos, contratos API ni el menu de cuenta.

## Validacion

- Tanda amplia: 467 casos de navegacion, caracterizacion, permisos, exportacion, encabezados, dashboard, administracion y menu; 466 pasaron inicialmente. Un caso existente comprobaba Cancelada inmediatamente al cerrar el dialogo, antes de completarse la actualizacion de fila: se cambio a una espera por el resultado visible. Repeticion focalizada de 41 casos (escrituras simuladas, TCH y orientacion) completa sin fallos, incluyendo el regreso desde ficha TCH al listado en la misma URL.
- Treinta snapshots actualizados y revisados: cambios de nombres, contexto de encabezado y niveles h1/h2. El arnes sigue comparando contenido funcional; la ruta de navegacion tiene pruebas de componente e integracion separadas.
- TypeScript/build pasan. Lint sin errores, con avisos preexistentes; no quedan avisos nuevos del efecto de titulo.
- Chrome autenticado en QA local: 18 pantallas, un h1 por pantalla, titulo y pagina actual coherentes, sin errores de render ni desbordamiento horizontal. Enlaces de perfil, Atrás/Adelante, regreso desde ficha interna TCH, activacion con Enter, temas claro/oscuro y movil de 320/390px verificados. Menu de cuenta conserva sus cuatro acciones.
- Capturas ignoradas bajo .local: orientation-desktop.png, orientation-dark.png y orientation-mobile-320.png / orientation-mobile-390.png.
- Navegador restringido a GET durante la comprobacion. Sin escrituras de proveedores, cambios en bases, dependencias ni backend. No se publica a GitHub.
- Skills personales fuera del indice, ignoradas y conservadas localmente; no forman parte de esta entrega.
