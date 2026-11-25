# ML-12: evidencia y deuda de validacion

Fecha: 2026-11-25. Rama local codex/actualizacion-20261118. Cambio: piloto sintetico TCH del Recuperador; no es una correccion general de dashboards, exportaciones o navegacion.

## Comprobaciones del cambio

- Cuatro archivos de Recuperador, incluido el piloto nuevo: **57 pruebas aprobadas** en la repeticion focalizada con un worker. Contrato/validacion, permisos, flag, foco, errores, paginacion y cambio de sesion; sin operaciones WR.
- Backend: **184 pruebas aprobadas** de API/PostgreSQL/ETL/permisos, incluida validacion de los cuatro campos agregados al resultado. Solo crm_ml_registry_test. Advertencia Starlette/TestClient existente; no se alteraron dependencias.
- TypeScript/Vite build pasa, Ruff completo pasa. Lint sin errores y sin avisos en los archivos nuevos del piloto; mantiene advertencias de otros modulos.
- Chrome: escritorio 1366px, movil 390px sin overflow horizontal, temas claro/oscuro, foco de detalle/retorno, vacio y API deshabilitada. Peticiones solo GET, APIs interceptadas con fixtures. Capturas/arnes quedan ignorados en .local/ml12. No se arranco/migro API operativa ni se habilito una bandera en .env/.env.local. El servidor de prueba 5176 se detuvo.

## Suite global: no esta en verde

`npm.cmd --prefix frontend run test` termino con **1.554 aprobadas y 10 fallidas (1.564)** en 124 archivos; no se presenta como aprobada. Incluyo la primera version del piloto antes de sumar una comprobacion de cambio de propietario. La repeticion focalizada posterior valida tambien esa comprobacion y los ajustes finales de texto/contrato.

Se creo un checkout local aislado de **120849c**, version previa a ML-12, en .local/ml12-baseline. Dependencias mediante junction local; sin skills personales/datos operativos. Se reprodujeron alli estos fallos sin modificar sus fuentes:

| Caso | Resultado previo a ML-12 |
|---|---|
| Exportacion VirtualPOS: boton Filtros por columna | Falla igual: el test espera un control que no encuentra. |
| Catalogo i18n: ficha general de cliente | Falla por timeout; el mismo caso se importa tambien desde pruebas de WebhookHealthPanel. |
| Guard de identificadores | Falla por siete identificadores canal/mes/canales en archivos de Dashboard/summary que no cambia ML-12. |
| Guard de ortografia | Falla por ID subscripcion con grafia «subscripción» en StagingRecordsList.tsx, sin cambios en esta entrega. |
| Menu de Bajas | Falla al buscar un boton dentro de una seccion colapsada; Sidebar no cambia aqui. |
| Estilo KpiCard | Falla por su inspeccion del bloque restante de Staging.css; ese archivo no cambia aqui. |

La ficha TCH que fallo en el run global paso aislada tanto en 120849c como en el arbol actual (14/14). El caso de conservacion de contexto de Suscripciones tambien paso en la repeticion actual. Cobros unificados paso en la copia previa, agoto el tiempo en la repeticion amplia actual y finalmente **paso aislado en el arbol actual: 10/10**, sin modificarlo o ampliar timeouts. No se certifica estabilidad de la suite global por ese resultado. Los cambios de AppCore en esta entrega solo pasan la identidad de sesion al Recuperador; no se modifica Cobros.

La comprobacion ampliada actual de nueve archivos termino con **121 aprobadas y 3 fallidas (124)**: exportacion, catalogo y Cobros. En la copia anterior, los cuatro archivos exportacion/Cobros/catalogo/UX terminaron con **51 aprobadas y 2 fallidas (53)**: exportacion/catalogo. No sumar estos conteos como pruebas distintas entre ejecuciones.

## Deuda registrada: QA-ML12-01

Reconciliar expectativas heredadas del frontend con la navegacion/filtros actuales, revisar los guards sobre claves de contrato y aislar las causas de timeouts en fichas/Cobros. Conservar validacion util y no cambiar pruebas solo para hacerlas pasar. Es trabajo separado del piloto sintetico; queda pendiente en docs/tasks.md. No se afirma que el repositorio completo pase QA o este autorizado para produccion.

## Limites del piloto

Las pruebas demuestran comportamiento de consulta con datos ficticios, no usabilidad medida con ejecutivos ni precision de modelos. No se registran aprobaciones humanas operativas o exposiciones; el piloto no enlaza estas filas a personas/cobros reales. Esas fronteras requieren datos auditados del socio y autorizacion posterior. Sin entrenamiento, inferencia real, proveedores, push o skills incluidas.
