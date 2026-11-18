# Listados de Detalle por canal — 2026-11-18

## Comportamiento final

- VirtualPOS, Toku, Payku y las tres listas TCH aprovechan el ancho y alto disponibles. Cabecera y espaciado compactos; filas con desplazamiento propio y encabezado fijo. El encabezado completo de VirtualPOS permanece visible al desplegar sus filtros por columna.
- Filtros por columna comienza plegado, conserva valores al cerrar e indica cuantos criterios siguen activos. No se esconden criterios activos sin aviso. Orden, exportacion, fichas, permisos y operaciones existentes se conservan.
- Por solicitud expresa del usuario, se retiran de Detalle por canal la ruta visual de navegacion, el boton Volver al resumen y los botones Todas / VP 1 / VP 2. La barra lateral sigue dando acceso a los resumenes. Los enlaces profundos existentes mantienen su cuenta y alcance de exportacion; sin parametro de cuenta se muestran todas las cuentas autorizadas.
- Se usa unicamente el desplazamiento nativo de la tabla, con barras contrastadas y foco por teclado. No hay barra adicional, flechas ni texto Explorar columnas. El scroll horizontal queda al pie de la zona visible, sin recorrer todas las filas para alcanzarlo.
- En movil o con poca altura se permite desplazar la pagina para alcanzar los controles; las filas conservan su zona propia. Las tablas relacionadas de las fichas tienen altura limitada. Los resumenes analiticos conservan su recorrido para consultar todos sus paneles.
- Se conserva el objeto de filtros VirtualPOS cuando ya esta vacio, evitando una segunda carga inicial provocada por su debounce. Sin cambios de contratos ni dependencias.

## Validacion

- 78 pruebas en seis archivos: componente accesible, filtros plegables y persistencia de criterios, carga, orden, paginacion, fichas, escrituras simuladas, exportacion con cuenta de URL y orientacion actualizada. Snapshots revisados: contenedores y controles solicitados; sin cambios de datos sinteticos ni contratos.
- Lint y TypeScript/build sin errores; permanecen avisos React anteriores. No se modifican backend, base de datos, migraciones ni paquetes.
- Chrome autenticado: 16 rutas de los cuatro canales; cinco con desbordamiento horizontal y diez con vertical. Encabezados y titulo estables al recorrer filas, teclado en region desplazable, paginacion accesible y ausencia de los controles retirados.
- Ventanas de 1100x580 y 1366x650: seis y nueve filas completas visibles respectivamente en Cargos VirtualPOS. Movil 390x820 y 320x740, temas claro/oscuro y menu de cuenta conservado. Sin desbordamiento horizontal de pagina ni errores JavaScript.
- Capturas locales ignoradas .local/channel-scroll-final-*.png, sin datos de filas. Navegador limitado a GET despues del login; sin escrituras a proveedores.
- Los 31 archivos personales se conservan por SHA-256 y las skills estan excluidas del indice. Solo rama local, sin push a GitHub.
