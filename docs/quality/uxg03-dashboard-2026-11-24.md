# UXG-03: Dashboard para consulta ejecutiva

Fecha: 2026-11-24. Trabajo exclusivamente local en `codex/actualizacion-20261118`.

## Supuestos y alcance

Usuario confirmado: ejecutivo sin conocimientos de programación que consulta socios, suscripciones y cobros. Tarea revisada: entender mes y actualización, elegir un indicador, consultar un listado autorizado y regresar. La solicitud expresa habilita esta entrega posterior al cierre previsto de S7; no declara completadas las otras tareas de S8.

Se conserva el Dashboard existente: cuatro indicadores principales, ocho secundarios, gráficos, filtros y detalle. Sin cambios de backend, fórmulas, metas, clasificación financiera, fecha de corte, cobertura TCH, contratos o permisos. No se consultaron proveedores ni se modificaron bases de datos.

## Dirección visual y hallazgos corregidos

Se reutilizan tipografía, paleta, tokens y densidad operativa del producto. La mejora usa orden y lenguaje, sin otro framework ni nueva identidad.

| Hallazgo observado | Prioridad | Corrección y motivo |
|---|---|---|
| «Datos hasta el día 24» se obtiene del reloj aunque una ejecución falle o sea antigua. | Media | «Mes en curso · Cierre pendiente». Conserva el aviso de comparación parcial sin prometer actualización a hoy. |
| El bloque de actualización desaparece si no devuelve entradas; los canales sin entrada tampoco se enumeran. | Media | Mostrar todos los canales seleccionados permitidos: consultando, estado recibido o información desconocida. Los desconocidos cuentan entre los que requieren revisión; no se anuncian fallos mientras carga. |
| La fecha de ejecución puede interpretarse como fecha de los movimientos o cobertura garantizada. | Media | Indicar «Última ejecución» por canal y aclarar que no garantiza cobertura completa. Mantener generación de la vista separada. El rótulo y cobertura del gráfico TCH se conservan. |
| Al expandir ocho indicadores secundarios, «Qué revisar» queda después de ellos. | Media | Colocar avisos después de los cuatro indicadores y su detalle, antes de los secundarios. Mantener instrucciones según permisos y sin iniciar sincronizaciones ni cobros. |
| Todos los valores nulos producen «Ningún canal tiene actividad». | Media | Explicar que faltan indicadores y que esto no confirma ausencia de actividad. Con cero canales permitidos, mostrar acceso restringido y solicitud de revisión de permisos, sin tarjetas o acciones de período inútiles. |
| «No deduplicada» exige vocabulario técnico. | Baja | Explicar que se suman suscripciones por canal y una persona puede aparecer más de una vez. Otras notas del servidor se conservan. |
| Un selector CSS más específico dejaba las casillas móviles en 36px. | Baja | Restablecer objetivos de 44px para canales, botones secundarios y desplegables móviles. |

## Implementación y validación

Archivos afectados: `SummaryView`, `SummaryHealth`, `SummaryKpiGrid`, sus pruebas y estilos acotados al Dashboard. Sin dependencias nuevas.

- **83 pruebas frontend / 7 archivos pasan:** pantalla, avisos, adaptador, contrato HTTP, series, accesos/corte y recorrido integrado Dashboard → Pagos Payku → retorno. Incluyen estados nulos/cero, permisos, filtros, separación de cargas y desconocidos, foco de cierre con Escape y orden de avisos al desplegar secundarios.
- `npm.cmd --prefix frontend run lint` y `run build` pasan. Lint conserva advertencias existentes en otros módulos; no aparecen avisos nuevos en los archivos modificados.
- Chrome con datos sintéticos: escritorio 1366×650, móvil 390/320px y ancho de reflujo 683px, ambos temas. Se esperó el ajuste de Recharts y se verificó ausencia de desborde horizontal tanto en documento como en el área desplazable.
- Teclado: abrir detalle con Enter, foco en encabezado, cerrar con Escape y devolver foco. Acceso autorizado al listado y retorno con el mes conservado. Casillas y cambio a mes cerrado/actual comprobados.
- Carga, error con reintento, información de actualización desconocida, mes sin indicadores y acceso sin canales comprobados en navegador. Cero errores JavaScript observados; solo solicitudes GET simuladas.
- Conciliación sintética: los cuatro ingresos del detalle suman $92.000, igual al total de la respuesta y a la tarjeta. El cálculo productivo no cambia.
- Muestreo de contraste de 12 textos visibles en cada tema: razón ≥4,5:1 para subtítulo, etiquetas, aviso mensual, estado de actualización, rótulos de indicadores y texto de avisos. Es una comprobación parcial, no certificación WCAG.

Los scripts privados de captura permanecen ignorados en `.local/`. Las capturas siguientes contienen únicamente información sintética.

## Evidencia y límites

- [Antes](assets/uxg03-2026-11-24/before.png) y [después en escritorio](assets/uxg03-2026-11-24/desktop.png).
- [Tema oscuro](assets/uxg03-2026-11-24/dark.png) y [móvil 320px](assets/uxg03-2026-11-24/light-320.png).
- [Actualización desconocida](assets/uxg03-2026-11-24/unknown.png), [sin indicadores](assets/uxg03-2026-11-24/empty.png) y [acceso restringido](assets/uxg03-2026-11-24/denied.png).

No se ejecutaron pruebas contra datos operativos ni una nueva conciliación financiera real: se reutiliza el contrato existente y se valida con fixtures. El hook compartido de salud devuelve un mapa vacío ante error; por eso se comunica información desconocida, sin inventar si la causa fue conexión, permiso o ausencia de ejecuciones.

Quedan pendientes sesiones con ejecutivos, lector de pantalla real, auditoría AA integral, zoom del navegador y rendimiento con volúmenes productivos. El ancho 683px comprueba reflujo, no sustituye la prueba de zoom real. UXG-04 y siguientes siguen pendientes. Skills personales intactas y excluidas; no se realizó push.
