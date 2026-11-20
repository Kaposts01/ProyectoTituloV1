# Diagnóstico UX/UI inicial de SynkmetriX

Fecha: 20-11-2026. Etapa UXG-00. Alcance: diagnóstico; sin implementar cambios de interfaz.

Estado posterior: los ocho hallazgos observados se atendieron en [UXG-FIX-01](uxg-fix-2026-11-20.md). Este documento conserva la referencia inicial; las hipótesis de investigación siguen diferenciadas de las correcciones implementadas.

## Usuario, alcance y método

El usuario confirmó que los destinatarios son **ejecutivos sin conocimientos de programación**, que buscan cobros, socios y planes. Se revisaron consulta de socio, seguimiento de suscripción y revisión de cobro; se añadió una comprobación acotada del acceso a Planes. No se presupone que el ejecutivo conozca IDs internos o el proveedor de cada registro.

Se aplicó una revisión de tareas, jerarquía, recuperación y contexto. La dirección propuesta para las próximas entregas es operativa, sobria y de densidad útil, reutilizando identidad y componentes existentes. Esta etapa no selecciona una nueva paleta ni cambia el sistema visual.

Los servicios originales estaban detenidos. Se ejecutó únicamente Vite en loopback, puerto 5174, y Chrome con **todas las llamadas API interceptadas**: sesión ejecutiva ficticia, respuestas sintéticas, 120 socios, páginas de 50 registros, nombres largos, RUT sintéticos válidos y estados controlados. No se inició el backend ni se accedió a PostgreSQL o proveedores. Los métodos distintos de GET estaban bloqueados; no se intentó ninguna escritura. La demora de ficha de 1,8 s es artificial: sirve para inspeccionar feedback, no mide el rendimiento real.

Se combinaron navegación en el frontend real, capturas, inspección de foco y geometría, revisión de código y pruebas existentes. Los hallazgos observados describen la interfaz bajo estos escenarios; las hipótesis de comprensión necesitan sesiones con ejecutivos. No es una auditoría de seguridad ni una certificación WCAG.

## Recorridos revisados

| Recorrido | Resultado observado |
| --- | --- |
| Buscar socio, abrir ficha y volver | Funciona mediante el RUT; búsqueda y canal se conservan al cerrar la ficha. Falta feedback durante la apertura y el foco termina en BODY al entrar y salir. |
| Buscar sin resultados y recuperar listado | Mensaje específico y botón para quitar filtros recuperan los registros. |
| Error temporal de listado y reintento | Mensaje de error y Reintentar funcionan con una respuesta 503 simulada. |
| Esperar listado / acceso denegado | Exportar está deshabilitado durante la carga; 403 se distingue de una lista vacía. |
| Filtrar Suscripciones, ir a Cobros y volver | La búsqueda DEMO y el canal VirtualPOS 1 se pierden: ambos vuelven a vacío. |
| Filtrar Suscripciones, abrir ficha y volver con Atrás | También se pierden búsqueda y canal. Se comprobaron filtros activos antes de abrir la ficha. |
| Revisar Cobros | Presenta socio, RUT, resultado, fecha y monto; su búsqueda está orientada a IDs y estado. |
| Localizar Planes | Buscar Planes en el menú muestra dos destinos, VirtualPOS y Payku; se comprobó el acceso a /virtualpos/planes. No se auditó el contenido de los planes. |
| Acceso general sin permiso de ficha | Puede ver la suscripción, pero el ID aparece como texto sin explicación del acceso a detalle. No se intentó eludir permisos. |

## Hallazgos observados y prioridad

Gravedad: alta = obstaculiza una tarea principal o impone esfuerzo reiterado; media = confusión o recuperación deficiente; baja = presentación localizada. No se identificó un hallazgo crítico en este alcance limitado.

| ID | Gravedad | Evidencia y consecuencia | Siguiente intervención propuesta |
| --- | --- | --- | --- |
| UXG00-F01 | Alta | Encabezados repetidos, separación vertical y bloques previos desplazan los resultados. A 1366×650, ninguna de las tres listas muestra una fila completa al entrar. En móvil se necesita desplazar la página antes de trabajar con los registros. | UXG-01: compactar la jerarquía de Socios y reservar espacio real para filas, conservando filtros activos y la advertencia de identidad. Validar el piloto antes de extenderlo. |
| UXG00-F02 | Alta | La ficha de Socios muestra RUT, Portal, ID interno e ID origen, sin nombre en su encabezado ni enlaces de acceso a suscripciones/cobros relacionados. El ejecutivo debe interpretar o copiar identificadores y cambiar de módulo. | UXG-01: revisar el contexto humano de la ficha y proponer accesos de lectura autorizados donde existan rutas y permisos. Mantener identificadores como apoyo, sin ocultar datos necesarios ni inventar relaciones. |
| UXG00-F03 | Alta | La búsqueda de Cobros/Pagos y su contrato admiten IDs y estado; no nombre/RUT. La tabla sí muestra esos datos. Consultar directamente los cobros de una persona no está cubierto por esa búsqueda. | UXG-02B: contrastar la búsqueda habitual del ejecutivo y diseñar la consulta por socio. Una ampliación requiere revisión de contrato, consultas y permisos; cambiar el placeholder por sí solo sería engañoso. |
| UXG00-F04 | Media | Suscripciones usa estado local para búsqueda, canal y filtros. Al salir a otro módulo o volver desde la ficha, los valores probados se reinician. | UXG-02A: definir conservación de contexto y retorno sin poner búsquedas personales en URL o almacenamiento persistente. Validar canal, criterios, página y foco. |
| UXG00-F05 | Media | Durante los 1,8 s de apertura simulada de la ficha de Socios no aparece texto de carga ni aria-busy. El usuario no tiene confirmación de que se está abriendo. | UXG-01: feedback de apertura, prevención de solicitudes repetidas y recuperación del error de ficha sin perder búsqueda. |
| UXG00-F06 | Media | Al reemplazar la tabla por la ficha y al cerrarla, document.activeElement es BODY. No se dirige el foco al encabezado ni se devuelve al disparador. | UXG-01: establecer entrada y retorno de foco coherentes y comprobarlos con teclado; no declarar conformidad completa a partir de este arreglo. |
| UXG00-F07 | Media | Con permiso general de Suscripciones, sin permiso específico de ficha, el ID deja de ser botón y no hay explicación. La restricción es correcta, pero su presentación puede parecer una interacción rota. | UXG-02A: explicar el alcance de consulta sin ampliar permisos ni mostrar destinos no autorizados. |
| UXG00-F08 | Baja | Cobros muestra 2026-11-05. El helper compartido day recorta la fecha ISO, mientras el criterio de interfaz usa español de Chile. | UXG-02B: formato humano coherente, conservando el valor ISO para intercambio y filtros y evitando desplazamientos de día por zona horaria. |

Referencias de implementación para reproducir y dimensionar los cambios:

- [GeneralClientsPanel.tsx](../../frontend/src/features/dashboard/GeneralClientsPanel.tsx): apertura de ficha, composición, advertencia de identidad, carga y retorno.
- [UnifiedSubscriptionsView.tsx](../../frontend/src/features/general/UnifiedSubscriptionsView.tsx): estado de búsqueda/canal y acceso condicionado a fichas.
- [UnifiedChargesView.tsx](../../frontend/src/features/charges/UnifiedChargesView.tsx): campos de búsqueda, presentación y pestañas.
- [export_queries.py](../../app/services/export_queries.py): FILTER_FIELDS y campos de _search para cobros/pagos; el hallazgo F03 se respalda en código, no en una supuesta consulta a la base.
- [unifiedDisplay.tsx](../../frontend/src/features/general/unifiedDisplay.tsx): formato day y guardas de acceso.
- [App.css](../../frontend/src/App.css): márgenes de topbar, disposición móvil y dimensiones de tablas; no se modificaron.

## Referencia de espacio disponible

Mediciones en píxeles CSS, al entrar con filtros avanzados plegados y sin desplazar la página. El conjunto incluye nombres largos; no representa la distribución de longitud de los datos productivos. Cero filas completas no significa que la tabla esté inaccesible: se puede llegar mediante scroll de página.

| Ventana | Socios: inicio de tabla | Suscripciones: inicio | Cobros: inicio | Filas completas iniciales |
| --- | ---: | ---: | ---: | --- |
| 1366×650 | 563 | 543 | 627 | 0 en las tres listas |
| 390×820 | 851 | 730 | 854 | 0 en las tres listas |
| 320×740 | 899 | 773 | 882 | 0 en las tres listas |

A 1366×768, Socios comienza aproximadamente en y=563. En los nueve casos de la tabla no se observó desbordamiento horizontal de la página; la tabla mantiene su desplazamiento interno. La limitación observada es espacio vertical y jerarquía, no ausencia de responsive.

Capturas reproducibles con datos exclusivamente sintéticos:

- [Socios en escritorio](assets/uxg00-2026-11-20/socios-escritorio.png).
- [Ficha de socio](assets/uxg00-2026-11-20/ficha-socio.png).
- [Socios en móvil](assets/uxg00-2026-11-20/socios-movil390.png).
- [Cobros en escritorio](assets/uxg00-2026-11-20/cobros-escritorio.png).
- [Planes mediante búsqueda de menú](assets/uxg00-2026-11-20/planes-menu.png).

## Hipótesis y preferencias: no tratarlas como defectos demostrados

1. El placeholder Buscar del menú podría interpretarse como búsqueda de registros. Su nombre accesible sí dice Buscar en el menú. Comprobar si el ejecutivo distingue ambos buscadores antes de añadir una búsqueda global.
2. Para encontrar Planes se necesita elegir un canal. Confirmar si el ejecutivo conoce ese dato; disponer de dos destinos no demuestra por sí mismo un problema ni autoriza a crear una vista unificada.
3. La explicación de RUT no verificado y la columna Suscripciones activas, cuyos valores son canales, pueden necesitar lenguaje más directo. Verificar comprensión sin eliminar la advertencia ni presentar como confirmada la identidad de la persona.

Las decisiones visuales anteriores del usuario siguen vigentes: menú por secciones, cuenta desplegable y retiro de elementos indicados en Detalle por canal. No se consideran defectos por apartarse de una plantilla.

## Qué funciona y debe conservarse

- Búsqueda etiquetada, criterios activos visibles y filtros avanzados que conservan valores al plegarse.
- Recuperación del vacío filtrado, reintento de error y mensaje diferenciado de permiso insuficiente.
- Bloqueo de exportación durante carga, selección de columnas y paginación de servidor.
- Conservación de búsqueda/canal al abrir y cerrar la ficha de Socios.
- El foco pasa de Buscar socios al selector Canal con Tab en el recorrido comprobado.
- Planes puede localizarse con el buscador del menú; ambos destinos incluyen su proveedor.
- Accesos a fichas condicionados al permiso específico. La mejora UX no debe ampliar esos permisos.

## Próxima entrega: piloto de Socios, todavía pendiente

Resolver primero F01, F05 y F06, y preparar una propuesta acotada para F02. No ampliar el contrato de búsqueda de Cobros en este piloto ni resolver la identidad centralizada por diseño.

Criterios propuestos para UXG-01:

1. Con el mismo escenario, a 1366×650 mostrar al menos cuatro filas completas sin scroll de página; a 390×820 hacer visible el encabezado de resultados y el primer registro al entrar con filtros plegados. Contrastar estos objetivos con la captura final, sin esconder advertencias o estados críticos para cumplirlos.
2. Encontrar el socio por RUT o nombre, abrir su ficha con una acción comprensible y ver confirmación de apertura durante una respuesta demorada.
3. Identificar a quién corresponde la ficha; distinguir información del negocio de identificadores de soporte. Los accesos relacionados solo existen cuando hay ruta, datos y permiso de lectura suficientes.
4. Al volver, conservar búsqueda, canal, página y criterios; recuperar el foco en un disparador válido. No persistir datos personales en URL/localStorage para conseguirlo.
5. Repetir escenario normal, sin resultados, error, demora y acceso limitado; revisar escritorio/altura corta, móvil y ambos temas. Registrar cualquier límite que requiera backend o decisión de producto.

Antes de evaluar rapidez real, observar a ejecutivos en tareas representativas y registrar errores, pasos y necesidad de ayuda. No se asignan mejoras porcentuales ni tiempos objetivo a partir de mocks.

## Validación y límites

- Pasaron **32 pruebas existentes** en cuatro archivos: portfolio.integration, general.characterization, UnifiedSubscriptionsView y UnifiedChargesView. No se añadieron pruebas que dupliquen implementación ni se modificó su código.
- Navegador sin errores JavaScript de render en los escenarios completados; cero escrituras intentadas. Revisión clara/oscura en Socios; matriz responsive de las tres listas. Las sesiones y las respuestas fueron simuladas, no perfiles efectivos de producción.
- Se inspeccionaron foco y navegación básica por teclado. No se midió contraste completo, no se usó un lector de pantalla real ni se certificó WCAG AA. Tampoco se midieron tiempos de backend, rendimiento con grandes volúmenes, exportaciones reales o SSE de producción.
- No se cambiaron fuentes de aplicación, dependencias, permisos, fórmulas, migraciones o bases. Lint/build no se repitieron: esta entrega modifica documentación y capturas, no frontend. Revisión de diff y archivos públicos sin credenciales ni datos de personas reales.
- Pendiente investigación con usuarios: frecuencia relativa de tareas, información con la que comienzan una búsqueda de cobros, conocimiento de canales y necesidad móvil habitual. El perfil de ejecutivo no técnico sí fue confirmado por el usuario durante esta etapa.

La etapa de diagnóstico queda completada con estos límites. La implementación UXG-01 y los siguientes lotes permanecen pendientes. Solo rama local; sin publicación ni archivos de skills personales.
