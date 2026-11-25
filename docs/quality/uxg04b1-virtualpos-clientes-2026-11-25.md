# UXG-04B1: consulta de clientes VirtualPOS

Fecha: 2026-11-25. Rama local `codex/actualizacion-20261118`, sin push. Primer sublote de otros recursos VirtualPOS tras Cargos; Planes, Suscripciones y Transacciones siguen pendientes.

## Supuestos y alcance

Ejecutivos sin conocimientos técnicos, principalmente en escritorio y con consulta móvil. Tarea: buscar cliente por nombre/documento, combinar criterios, abrir ficha y volver sin perder consulta, cuenta, orden o posición. No se presupone identidad centralizada confirmada; la ficha conserva sus relaciones por RUT tal como las entrega la API.

Se revisaron contratos y componentes existentes. No se cambian endpoints, fórmulas, backend, migraciones, permisos del servidor, modelos ML o configuración de escrituras. No se ejecutan sincronizaciones ni operaciones reales. Las pruebas y capturas usan exclusivamente fixtures sintéticos.

## Dirección visual

Se conserva la tipografía, paleta y tokens de SynkmetriX. Prioridad al nombre y a la lectura de filas; controles secundarios plegables, sin tarjetas decorativas ni nuevas barras. Se mantiene el desplazamiento nativo y no se reintroducen breadcrumbs, botones de cuenta o retorno al resumen retirados por el usuario.

Nombre y RUT/documento quedan a la vista; correo, teléfono, estado e ID son filtros adicionales. Se combinan con AND mediante el contrato actual; los términos personales no se guardan en URL, localStorage o sesión persistente.

## Correcciones

| Hallazgo observado | Corrección y motivo |
|---|---|
| Filtros dentro de una tabla ancha, inaccesibles si no hay filas. | Controles fuera de la tabla, criterios activos visibles al plegar y eliminación individual. Permite corregir una búsqueda sin resultados. |
| Nombre secundario y acceso a ficha poco explícito. | Nombre primero con «Ver ficha», conservando el acceso existente por RUT; encabezado y nombre fijos en escritorio al desplazar. En móvil se desplazan todas las columnas: fijar el nombre ocupaba casi todo el ancho e impedía leer las otras. |
| Las filas previas parecían utilizables durante el debounce o después de un error. | Estado pendiente desde el primer cambio, aviso de consulta anterior y bloqueo de ficha, edición, exportación y paginación hasta una respuesta válida. |
| Error genérico sin recuperación y vacío indistinto. | Reintentar consulta sin perder filtros; distinguir falta de registros de falta de coincidencias. Contador no presenta éxito tras un fallo. |
| Regreso de ficha reiniciaba la consulta. | Memoria temporal asociada al usuario/permisos y recurso; conserva filtros, cuenta, orden, filas cargadas y posición. Refresca antes de restaurar foco/scroll. Cliente de retorno identificado por ID interno de fila, no RUT. |
| Carga de ficha sin salida; errores podían dejar lista bajo URL de ficha; respuesta tardía podía reaparecer. | Botón de salida durante carga, error propio con reintento, cancelación/descarte de respuesta y foco inicial en el título. |
| Alta/edición y accesos relacionados visibles sin los permisos correspondientes. | Se ajusta visibilidad a `virtualpos.clients.update` y permisos de consulta relacionados; cancelación mantiene además la restricción administrativa existente. FastAPI sigue autorizando. |

La ficha identifica cuenta e ID y muestra un título útil cuando falta el nombre. No se rediseña toda la información relacionada ni se cambia la semántica de sus asociaciones. Mantener los accesos por nombre y RUT conserva el recorrido anterior y ofrece una entrada más reconocible para quien busca por nombre.

## Validación y límites

Siete pruebas nuevas de integración cubren consulta sin permisos de escritura, filtros simultáneos sin PII en URL, debounce/error con filas bloqueadas, reintentos, retorno con respuesta nueva/foco/scroll/cuenta/orden, vacío con limpieza y salida durante carga sin respuesta tardía. Con Cargos y caracterizaciones de lista/ficha: **51 pruebas aprobadas** sin actualizar snapshots en la comprobación final.

Se revisaron cuatro snapshots afectados: listado, ficha y dos diálogos existentes de clientes. Los escenarios de escritura reciben explícitamente su permiso; las peticiones permanecen simuladas y sus validaciones/CSRF/cuerpos no se eliminan. Se conserva el contrato de exportación y sus avisos sobre criterios sin equivalente.

La comprobación ampliada incluye navegación, exportación, escrituras simuladas, mapeo de exportación y scroll. Se detectó un selector antiguo de filtros de Cargos, reproducido en el worktree de referencia `120849c`; se actualizó el selector conservando las aserciones de parámetros. El helper de exportación vuelve a localizar el botón tras la carga en lugar de esperar sobre un nodo reemplazado. Esto no cierra la deuda general QA-ML12-01 ni certifica la suite global.

Resultado final ampliado: **71 pruebas aprobadas** sin actualización de snapshots; junto con las 51 anteriores son **122 pruebas distintas en nueve archivos**, siete nuevas. Comandos desde la raíz:

~~~powershell
npm.cmd --prefix frontend run test -- src/test/virtualpos-client-ux.integration.test.tsx src/test/virtualpos-charge-ux.integration.test.tsx src/test/records.characterization.test.tsx src/test/staging.characterization.test.tsx --maxWorkers=1
npm.cmd --prefix frontend run test -- src/test/writes.characterization.test.tsx src/test/navigation.characterization.test.tsx src/test/export.integration.test.tsx src/features/shared/exportMapping.test.ts src/components/ChannelTableScroll.test.tsx --maxWorkers=1
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build
~~~

Chrome headless con API interceptada: solo GET simulados, cero escrituras y cero errores JavaScript. Consulta con 100 filas de nombres/correos largos, entrada por teclado, foco y retorno, Atrás del navegador, error/reintento de lista y ficha, ausencia de coincidencias e interrupción durante carga. Desplazamiento bidimensional nativo y encabezado fijo; en escritorio el nombre permanece visible. A 1100×580 con dos criterios plegados se verificaron tres filas completas; se ajustó el espaciado vertical tras detectar pérdida de altura útil.

Revisión en 1366×650, 1100×580, móvil 390/320 y reflujo 683 píxeles, ambos temas y movimiento reducido. Sin desborde horizontal del documento o área principal; la tabla conserva scroll propio. En los inputs visibles, texto ≥4,5:1 y bordes ≥3:1; controles principales móviles de 44 px. Esta revisión parcial no certifica conformidad AA integral, lector de pantalla, zoom real del navegador, rendimiento con datos operativos o facilidad de uso demostrada con ejecutivos.

TypeScript/build y lint se ejecutan. Permanecen las advertencias conocidas de React sobre coordinación de estado en efectos de AppCore/useStagingRecords y otras vistas; no se silencian ni se amplía el lote a un refactor de navegación. No se añaden dependencias o APIs externas; se reutilizan patrones locales existentes.

Evidencia sintética:

- [Escritorio](assets/uxg04b1-2026-11-25/desktop.png).
- [Móvil 320](assets/uxg04b1-2026-11-25/light-320.png).
- [Tema oscuro con filtros](assets/uxg04b1-2026-11-25/dark.png).
- [Sin coincidencias](assets/uxg04b1-2026-11-25/no-results.png).
- [Error de ficha recuperable](assets/uxg04b1-2026-11-25/detail-error.png).

Siguiente lote propuesto: Planes VirtualPOS, revisando sus tareas y contrato antes de extender cambios. Suscripciones y Transacciones quedan para entregas posteriores. Los archivos personales y los instrumentos privados permanecen locales y fuera de Git.
