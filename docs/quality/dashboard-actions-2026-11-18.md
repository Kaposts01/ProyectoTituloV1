# Dashboard: prioridades, detalle y siguientes pasos — 2026-11-18

Cuatro indicadores principales: Ingreso total, Socios totales, Cobrabilidad y No cobrado. Los ocho restantes se conservan bajo Mas indicadores. Valores, series, metas ausentes, distincion null/cero y comparaciones de mes parcial mantienen el contrato existente.

Ver detalle muestra valor, definicion, canales y fecha de calculo desde la misma respuesta del Dashboard; Ingreso incorpora el desglose por canal sin recalcular el total. Accesos autorizados a registros preservan mes/canales y acotan fechas por el ultimo calculo y el dia de Chile. Payku abre Pagos; No cobrado de Toku conserva todos los estados relacionados para no excluir facturas impagas/vencidas. Se explicitan las diferencias de base de Toku y de controles mensuales/fechas de TCH. Socios enlaza suscripciones actuales, con aviso de que no reconstruyen el stock historico ni identifican personas unicas.

Los listados muestran contexto y retorno al Dashboard, restaurando mes/canales. Un enlace guardado con canales obtiene tambien el conjunto completo permitido por el servidor para el selector. Se retira el serializador obsoleto de Suscripciones que borraba esos parametros. Los permisos generales de listado, ya admitidos por backend, funcionan en las vistas; no conceden acceso a fichas de proveedor, cuyos enlaces se condicionan al permiso especifico.

Que revisar identifica datos desactualizados/no confirmados, actualizaciones en curso, importe no cobrado y fechas incompletas. Cada caso ofrece una vista de revision o una instruccion al administrador segun permisos; no dispara sincronizaciones, reintentos de cobro ni escrituras.

Validacion: 159 pruebas en 15 archivos pasan; lint sin errores (avisos anteriores) y TypeScript/build pasan. Chrome QA local verifica 4/12 tarjetas, detalle/foco/Escape, enlaces a Pagos y Suscripciones, retorno al mismo contexto, alertas, teclado, temas y 320/390px. El ingreso total real de octubre se concilia con la suma de los importes por canal de la API (sin exponer filas personales); el total visible coincide. La navegacion de prueba bloquea escrituras API. Capturas agregadas en .local/dashboard-ux-*.png, ignoradas.

Solo rama local, sin push. Sin cambios backend, migraciones, datos ni skills personales versionadas.
