# Busqueda, filtros y tablas de Cartera — 2026-11-18

## Implementacion

- Socios, Suscripciones y Cobros/Pagos comparten busqueda visible y filtro de canal; los campos especificos se agrupan en Mas filtros, con contador y chips que permanecen visibles al cerrar. Los criterios se conservan al plegar. Borrar busqueda devuelve foco al campo; Limpiar filtros reinicia criterios y pagina, conservando preferencias de columnas.
- PortfolioTable muestra columnas principales por defecto, permite recuperar las adicionales y restaurar la vista inicial. Los identificadores esenciales permanecen visibles. Preferencias limitadas a nombres de columnas por vista, validadas y tolerantes a almacenamiento bloqueado/corrupto; filas y busquedas no se persisten.
- Encabezados de tabla fijos dentro de un scroll accesible, montos alineados, paginacion en servidor, Primera pagina y controles bloqueados durante carga. No se ordena solo la pagina local ni se modifica el contrato del servidor.
- Carga, error, falta de permisos y vacio se distinguen. Una consulta pendiente oculta filas/recuentos anteriores y bloquea exportar; errores permiten reintentar, y vacios filtrados permiten recuperar el listado quitando criterios.
- useUnifiedGet ignora respuestas canceladas incluso si el transporte no aborta, permite reintentar y separa el contexto de usuario para la vista persistente de Socios. Las fichas pendientes de Socios no reaparecen tras cambiar filtros.
- Analisis de rechazo despues del listado, con indicador de carga/error y aclaracion del alcance canal/fechas; definicion financiera intacta. Se conservan avisos de identidad por RUT no verificado y las limitaciones de exportacion de Socios.

## Validacion

- 151 pruebas pasan en 11 archivos: controles, preferencias, respuestas fuera de orden, cambio de usuario, reintento, busqueda pendiente, ficha pendiente, privacidad, permisos, paginacion, exportacion y navegacion previa.
- Dos snapshots de Socios actualizados para la estructura de controles/tabla y revisados; fixtures sinteticos y contratos API conservados.
- TypeScript/build y lint pasan sin errores; permanecen avisos anteriores de React.
- Chrome autenticado en QA local: las tres listas, busqueda real sin coincidencias y recuperacion, teclado en Mas filtros, persistencia de columnas tras recargar, identificadores fijos, tabla con scroll, cambio a Pagos y menu de cuenta con cuatro acciones. Verificados escritorio, 390px y 320px, sin desbordamiento horizontal ni errores de render, y tema oscuro.
- Capturas locales ignoradas: .local/portfolio-{socios,suscripciones,cobros}-desktop.png, versiones mobile-320/mobile-390 y portfolio-dark.png. Se capturan controles/encabezados sin filas personales.
- Navegador limitado a GET durante la revision. No se cambian backend, datos, migraciones, dependencias ni escrituras de proveedores. Skills personales excluidas del indice y preservadas. Entrega solo en rama local; no publicar a GitHub.
