# ML-12: piloto sintetico del Recuperador TCH

Fecha: 2026-11-25. **Piloto de consulta implementado; apagado y sin validacion con usuarios/datos reales.** No se entrenan o cargan modelos, no hay probabilidades numericas ni gestiones contra proveedores. El socio valida los datos completos y el uso con ejecutivos. ADR-002 sigue Proposed.

## Alcance y criterio de diseño

Usuario: ejecutivo no tecnico que necesita entender por que un caso requiere revision y que falta verificar. El error costoso seria interpretar una señal como autorizacion para cobrar o como acusacion de fraude.

Se elige **TCH** como primer canal del piloto por su vista operativa existente de solo lectura. Esto no declara que sus datos reales sean estadisticamente aptos: la auditoria historica de esta copia sigue limitada y no se usa para alimentar la interfaz. Un boton en la pestaña TCH cambia entre gestion existente y piloto; nunca se mezclan filas ficticias con socios/cobros reales.

Direccion visual: tipografia y tokens existentes del CRM, superficies planas, divisores y densidad de consulta. Lista y explicacion lado a lado en escritorio; una columna en movil sin barra horizontal. Controles de al menos 44px, foco visible y retorno del foco al caso. Sin tarjetas KPI decorativas, emojis o porcentajes inventados.

## Flujo disponible

1. En `/general/recuperador`, pestaña TCH, aparece **Ver piloto con datos de prueba** solo si la bandera frontend esta encendida, hay propietario de sesion y se cumplen todos los permisos siguientes: `general.recovery.tch.view`, `ml.rejections.read`, `ml.tch.access`, `tch.transacciones.view`.
2. Al entrar se consulta exclusivamente GET `/api/v1/ml/tch/charge/results?limit=10&offset=...`. Sin consulta automatica mientras esta oculto. La API ML-11 sigue exigiendo sesion, permisos propios, bandera de backend y base descartable *_test.
3. La lista muestra posiciones de la muestra, motivo interpretado y corte del analisis. **Caso de prueba 1** es una posicion de pagina, no un ID persistente de un socio/cobro. No se inventa un nombre, RUT, monto, historial o vinculo a una ficha real.
4. **Ver explicacion** abre el detalle: siguiente revision sugerida, limitaciones de la clasificacion, fecha de corte con hora de Chile, datos pendientes y resguardos. Una señal de seguridad no demuestra fraude de la persona. Un conflicto no recibe un motivo definitivo.
5. La probabilidad se muestra como **No disponible: aun no hay un modelo validado**, nunca cero, un porcentaje estimado o una barra de progreso. Clasificar un motivo y estimar pago a 30 dias siguen siendo problemas diferentes.
6. La advertencia de revision humana es permanente: **el piloto no registra aprobaciones ni autoriza gestiones**. No hay botones de cobro, reintento, enlace de tarjeta, exportacion o modificacion. Las confirmaciones/permisos WR existentes no cambian. Cerrar el detalle devuelve el foco al caso; volver a gestion TCH desmonta el piloto.

No hay una vinculacion individual demostrada entre estos resultados sinteticos y filas operativas del Recuperador. Asociarlos por posicion, nombre, RUT o coincidencia parcial seria incorrecto. Un piloto con datos reales necesita un enlace Core/evidencia auditado y revalidacion de estado/conciliacion antes de cualquier flujo operativo. No se simula una aprobacion local como si fuera una decision guardada; registro de exposicion/decisiones corresponde a ML-14.

## Datos, estados y privacidad

`pilotContract.ts` recibe JSON desconocido y acepta solo TCH/synthetic, reglas sin modelos, versiones preparadas ML-09, probabilidad/confianza nulas y ejecucion falsa. Rechaza filas de otro canal, proposito real, scores, ejecucion habilitada, versiones incompatibles, estructuras invalidas, IDs duplicados, paginas excesivas y contradicciones basicas entre categoria/estado. Campos extra no entran al estado de presentacion.

La API añade de forma compatible cuatro campos seguros al resultado ya persistido: `classification_state`, `rules_state`, `severity`, `matched_rules`. No hay nueva migracion, lectura de proveedores, calculo durante GET o texto libre incorporado. La UI muestra etiquetas de negocio; codigos desconocidos se presentan como pendiente de interpretar, sin copiar el valor arbitrario. Detalles de procedencia permiten consultar versiones y numero de reglas sin convertir los IDs tecnicos en explicaciones causales.

Estados distintos: cargando, muestra vacia, respuesta incompatible, problema de conexion/servidor con reintento de lectura, sesion terminada, permiso insuficiente y piloto no habilitado. No se presenta un error como cero rechazos ni se conservan filas viejas visibles tras actualizar o fallar. La paginacion esta acotada a diez y no inventa un total global: una pagina completa puede llevar a una siguiente vacia, con opcion de volver.

Las peticiones se cancelan y descartan al salir. El propietario de sesion/permisos forma la identidad de montaje; cambio de usuario/permisos elimina resultados/seleccion anteriores. No se guardan casos, filtros o explicaciones en localStorage, URLs, caches compartidas o archivos del usuario. El cambio de entorno existente abre otra pestaña con otra sesion; no se introduce persistencia entre entornos.

## Banderas y reproduccion

`frontend/.env.example` documenta `VITE_ML_RECOVERY_PILOT_ENABLED=false`. No se modifica `.env`, `.env.local` ni el entorno habitual. Vite necesita reiniciar/reconstruir tras cambiar su bandera. El backend permanece con `ML_REJECTIONS_API_ENABLED=false` y `ML_REJECTIONS_BATCHES_ENABLED=false` en el runtime local.

La revision visual se hizo en un servidor Vite separado en 5176, con bandera solo de ese proceso y todas las rutas API interceptadas con fixtures. No se inicio/migro un backend de QA, no hubo llamadas reales a proveedores ni una sesion con credenciales del usuario. No se incluyen fixtures de demostracion como fallback en el producto: si la API no esta preparada, el piloto informa que no esta habilitado.

Para integrar una prueba con API real se requiere preparar primero una base descartable con datos exclusivamente sinteticos, migraciones/permisos ML-11 y resultados de los lotes ML-10. Habilitar las dos banderas no constituye autorizacion para restaurar datos reales, entrenar o activar un modelo. El nombre *_test tampoco anonimiza datos.

## Verificacion y limites

Se probaron los contratos, ausencia de solicitudes con bandera/permisos incompletos, separacion de gestion/piloto, desconocidos, señal de seguridad, paginacion, errores y recuperacion, foco/teclado, cancelacion por perdida de permisos y respuesta tardia de otra sesion. **57 pruebas del Recuperador pasan**, incluidas 26 nuevas del piloto. Backend: **184 regresiones API/PostgreSQL/ETL/permisos pasan**, con comprobacion de los nuevos campos seguros. [Detalle y fallos globales heredados](../../quality/ml12-validation-2026-11-25.md).

Chrome con fixtures comprueba escritorio 1366px, movil 390px sin overflow horizontal, tema claro/oscuro, detalle/foco, estado vacio y API apagada. Todas las solicitudes observadas son GET; ninguna a operaciones de proveedor. Capturas y arnes en `.local/ml12/` ignorado, no en Git. Se inspeccionaron visualmente y se redujeron repeticiones de texto.

Build TypeScript/Vite y Ruff pasan. Lint no presenta errores nuevos; conserva advertencias de otros modulos. La advertencia existente Starlette/TestClient sigue documentada en ML-11. La comprobacion global de frontend tambien descubre fallos ajenos al piloto: se comparan contra el commit previo `120849c` en un checkout aislado ignorado; el resultado completo se registra en la nota de QA indicada en tasks. No se modifica ese codigo ni se relajan sus pruebas para esconderlos.

Comandos focalizados:

~~~powershell
npm.cmd --prefix frontend run test -- src/features/recovery/RecoveryPilot.test.tsx src/features/recovery/generalRecovery.test.tsx src/features/recovery/recovery.test.tsx src/features/recovery/paykuRecovery.test.tsx --maxWorkers=1
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Las pruebas PostgreSQL usan la misma guarda/base descartable de ML-11; no copiar su configuracion hacia QA/original. No hubo nuevas migraciones o datos de QA en este piloto.

## Sesion de validacion que debe realizar el socio

Con un ejecutivo y datos sinteticos, comprobar si puede: identificar que esta en pruebas; encontrar un caso sin clasificacion; explicar que dato falta; interpretar una señal de seguridad sin acusar a la persona; distinguir corte de estado actual; volver a la gestion existente; y reconocer que no hay una probabilidad ni aprobacion operativa disponible.

Registrar tiempo por tarea, errores, explicacion del usuario y puntos de confusion, sin datos personales. No confundir satisfaccion con mejora causal en recuperacion. El socio debe validar contratos/privacidad/enlaces/cobertura con su entorno completo y acordar la aprobacion humana real antes de mostrar resultados operativos. No se ha observado aun a ejecutivos usando esta entrega; claridad y utilidad con ellos siguen siendo hipotesis.

ML-12 queda preparado como piloto sintetico de consulta, sin afirmar despliegue o modelo validado. ML-13/14 no se inician automaticamente. Rama local, sin skills incluidas, entrenamiento, modelos cargados o push.
