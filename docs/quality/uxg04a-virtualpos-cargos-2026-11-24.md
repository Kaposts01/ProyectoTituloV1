# UXG-04A: Cargos VirtualPOS como piloto

Fecha: 2026-11-24. Rama local `codex/actualizacion-20261118`. Sin push.

## Usuario, tarea y alcance

Ejecutivo no técnico, principalmente en escritorio y con consulta móvil. Recorrido: buscar una suscripción, combinar fecha/estado/monto, identificar un cargo, abrir su ficha y volver sin perder contexto. Cargos es el único listado piloto de esta entrega; no se extiende automáticamente a los otros recursos VirtualPOS ni a Toku, Payku o TCH.

Se conserva el contrato de staging y los permisos del servidor. La búsqueda existente de cargos admite ID de suscripción, no nombre ni RUT: la etiqueta lo dice sin prometer otra capacidad. No se agregan escrituras, dependencias, migraciones ni sincronizaciones.

## Dirección visual y correcciones

Se reutilizan colores, tipografías y tokens del producto. Se priorizan datos y espacio de lectura: sin nuevas tarjetas decorativas, barras adicionales, breadcrumbs, botones de cuenta ni retorno al resumen.

| Hallazgo observado | Prioridad | Solución |
|---|---|---|
| El listado enlaza la suscripción pero no el cargo; en móvil predominan identificadores. | Media | Acceso «Ver cargo» con su ID; cliente junto al acceso. Primera columna fija al desplazarse horizontalmente. Nombre largo admite varias líneas. |
| Los filtros están en la tabla ancha y desaparecen si no hay filas. | Media | Búsqueda por ID de suscripción y filtros avanzados fuera de la tabla. Criterios visibles al plegar, con eliminación individual y limpieza total. Fechas visibles en formato chileno. |
| Registros anteriores y exportación siguen habilitados mientras cambian los filtros. | Media | Estado de consulta desde el primer cambio, incluso durante debounce. Bloqueo de ficha, operaciones, exportación y paginación hasta la respuesta. Explicación explícita de que las filas visibles pertenecen a la consulta anterior. |
| Un ejecutivo sin permiso de cancelación ve «Cancelar» en lista y ficha. | Media | Alinear visibilidad con `virtualpos.charges.cancel`, conservando el control del servidor. Reintento y enlaces relacionados también respetan sus permisos específicos. El backend ya exigía autorización; no se identificó una nueva vía de escritura. |
| Volver de la ficha reinicia filtros, orden, cuenta y posición. | Media | Memoria transitoria de criterios y filas, asociada a usuario/permisos. Retorno por botón o navegador; nueva consulta antes de restaurar foco y scroll. Sin búsquedas personales en URL o almacenamiento persistente. |
| Error de ficha puede dejar el listado bajo una URL de detalle; una respuesta tardía puede reaparecer tras salir. | Media | Error propio con salida y reintento de lectura. Cancelación al salir, descarte de respuesta obsoleta y limpieza de la ficha anterior. Salida disponible mientras carga. |
| Mensaje vacío único y fechas ISO dificultan interpretar la consulta. | Baja | Diferenciar ausencia de cargos y filtros sin coincidencias; fecha del listado y chips DD-MM-AAAA, sin cambiar el día del dato. |

## Validación

- **96 pruebas en siete archivos pasan**, sin actualizar expectativas durante la comprobación final. Siete casos nuevos cubren permisos de consulta, bloqueo inmediato, recuperación, filtros/orden/cuenta de retorno, vacío, respuesta tardía y espera de una nueva consulta antes de restaurar foco.
- Se revisaron cuatro snapshots afectados: tres presentaciones de lista/diálogo y el encabezado enfocable de la ficha. Permanecen las comprobaciones de operaciones autorizadas con HTTP simulado; no se ejecutaron operaciones reales.
- Lint y TypeScript/build pasan. Lint conserva advertencias React y señala la coordinación de estado en el efecto de rutas de `AppCore`, además del reinicio de estados disponible en el hook de listas. No se ocultaron advertencias ni se amplió esta entrega a un refactor del enrutamiento.
- Chrome con datos sintéticos: scroll nativo por teclado, encabezado fijo y primera columna estable; ficha con Enter, foco de entrada y retorno; botón Volver y Atrás del navegador conservan criterios. La revisión detectó una restauración prematura de foco: se corrigió esperando la nueva respuesta, incluso si coincide con una consulta anterior.
- Revisión en 1366×650 y 1100×580, móvil 390/320px y reflujo 683px, claro/oscuro. En 1100×580 con tres criterios activos se verificaron al menos tres filas completas. Sin desborde horizontal adicional del documento o área principal; la tabla conserva su desplazamiento bidimensional.
- Carga lenta, errores de lista/ficha con reintento, ausencia de resultados e interrupción durante carga comprobados. Cero errores JavaScript observados. Solo GET simulados, incluida la consulta del conteo de exportación con criterios activos; sin descarga de archivos ni llamadas reales a proveedores.
- Campos visibles en ambos temas: contraste de texto ≥4,5:1 y borde frente a fondo ≥3:1. Icono nativo de fecha adaptado a tema oscuro. Objetivos móviles de 44px para filtros y acceso al cargo.

## Evidencia y límites

Capturas exclusivamente sintéticas:

- [Antes](assets/uxg04a-2026-11-24/before.png), [escritorio](assets/uxg04a-2026-11-24/desktop.png) y [filtros](assets/uxg04a-2026-11-24/filters.png).
- [Móvil 320px](assets/uxg04a-2026-11-24/light-320.png) y [tema oscuro](assets/uxg04a-2026-11-24/dark.png).
- [Consulta pendiente](assets/uxg04a-2026-11-24/loading.png), [sin coincidencias](assets/uxg04a-2026-11-24/no-results.png) y [error de ficha](assets/uxg04a-2026-11-24/detail-error.png).

Sin validación nueva contra datos operativos, revisión integral de accesibilidad, lector de pantalla real o estudio con ejecutivos. El reflujo a 683px no sustituye zoom real del navegador. La ficha conserva su presentación de datos de origen; su reorganización completa queda para otro lote. Exportación mantiene sus limitaciones y avisos existentes para criterios sin equivalente.

Deuda registrada: la navegación heredada coordina estado y cargas en efectos de `AppCore`; el aviso de lint requiere una revisión específica, sin silenciarlo ni sustituir el router en este piloto. Otros recursos conservan su comportamiento previo y requieren revisión propia.

Las 31 piezas personales originales conservan SHA-256; skills e instrumentos privados bajo `.local/` quedan excluidos de Git. Los cambios solo corresponden al proyecto y a esta evidencia.
