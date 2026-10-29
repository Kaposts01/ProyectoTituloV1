# DASH-02 — Indicadores mensuales y graficos del dashboard general

Fecha: 2026-10-20. Referencias visuales proporcionadas por el usuario; confirmo que las cifras y categorias eran ejemplos de diseno, no metas ni datos institucionales.

## Implementacion

Servicio de solo lectura `app/services/dashboard_performance.py`, expuesto como campo adicional `performance` del dashboard general existente. Mantiene permiso dashboard.view y cache del contrato anterior. No agrega migraciones, escrituras ni llamadas a proveedores. Lee proyecciones centralizadas de canales online y tablas TCH; excluye las copias TCH centralizadas para no duplicar datos.

Componente React separado `GeneralPerformance`, modelo de calculo puro TypeScript y CSS responsivo. Selector mensual; tarjetas de KPI; graficos de ingresos por canal, acumulado frente a meta/proyeccion, base activa y movimientos; ventanas de 12 meses, ano seleccionado e historico; tabla accesible por grafico. El resumen operativo previo y sus filtros quedan disponibles en una seccion desplegable. Las alertas anteriores no se recalculan en esta entrega.

La meta anual es un escenario opcional en memoria del componente, distinto por ano, sin valor inicial ni persistencia. No reemplaza una meta institucional. No se agregan categorias de ingreso sin fuente ni se copian importes de las referencias.

## Definiciones

- Recaudacion: suma decimal de importes de pagos aceptados en CLP, con fecha no posterior al corte. Monedas distintas o ausentes, montos invalidos y fechas futuras/invalidas quedan fuera; se informa el conteo excluido.
- TCH: usa control mensual valido, con importe o cantidad observada, en el mes correspondiente; en otros meses usa detalle. No suma control y detalle del mismo mes. Controles futuros o completamente vacios no prueban actividad cero.
- Mes/canal sin observaciones: null en API y raya en tabla/tarjeta; un importe cero con evidencia se conserva como cero.
- Base activa: intervalos verificables de suscripciones por fuente, sin deduplicar personas. Inicio anterior/al corte y fin posterior o ausente cuando el estado actual es activo. Intervalos invalidos y bajas sin fecha verificable se excluyen. No equivale a socios unicos ni reconstruye reactivaciones no preservadas.
- Activaciones/bajas: inicios/terminos del mes dentro de esos intervalos; crecimiento neto = activaciones menos bajas. Corte del mes actual parcial, usando fecha America/Santiago.
- Churn: bajas de suscripciones pertenecientes a la base al inicio / base inicial. Excluye del numerador suscripciones creadas durante el mes; denominador cero es no disponible.
- Efectividad por monto: aceptado / (aceptado + rechazado). Son eventos observados y pueden incluir reintentos; no mide personas cobradas ni compromisos pendientes.
- Variacion: diferencia de recaudacion contra el mes calendario anterior, disponible solo cuando ambos tienen observaciones.
- Acumulado: suma observada del ano hasta el mes elegido. Senala huecos de cobertura y no incluye meses posteriores al elegido.
- Meta mensual/ritmo: meta anual de analisis / 12; diferencia anual = acumulado observado menos meta anual. No se compara sin meta ingresada.
- Proyeccion: promedio mensual observado multiplicado hacia los meses restantes, anclado en el acumulado elegido. Solo se muestra si hay observaciones desde enero y todos los meses considerados estan cerrados. Es escenario aritmetico, no modelo predictivo.

## Validacion

- 304 pruebas Python aprobadas en PostgreSQL aislado. Permanece aviso previo de deprecacion Starlette/httpx.
- 4 pruebas del modelo TypeScript con node:test, sin dependencias adicionales. `npm test` incorporado al CI existente.
- Ruff global sin errores. Frontend build y lint pasan; permanecen 11 avisos existentes y advertencia de bundle superior a 500 kB.
- Pruebas incluyen cambio de ano/mes, meses faltantes, cero real, mes parcial, fronteras de altas/bajas, churn por cohorte inicial, decimales, moneda/futuro, controles TCH invalidos/vacios y copias TCH por canal/centralizada.
- API autenticada responde 200. Conciliacion de septiembre TCH contra su control mensual coincide exactamente, sin publicar cifras en este informe.
- Revision visual en navegador dentro de la sesion del usuario: selector de mes, meta temporal, rango anual y tabla Ver datos. Se retiro la meta de prueba. CSS revisado a ancho de escritorio; no se certifica prueba en dispositivo movil real.
- Captura local ignorada: `.local/dashboard-general-kpis.png`. No se cambiaron datos operativos ni se sincronizaron proveedores.

## Limites

Los datos actuales tienen cobertura parcial por proveedor. Las proyecciones existentes no tienen historial completo de personas o reactivaciones; no se certifican socios unicos ni recaudacion institucional completa. Los controles TCH tienen granularidad mensual. Metas no persistentes y reportes anteriores mantienen sus contratos originales. Persisten las advertencias previas de frontend y el contrato pendiente de pagos Toku.
