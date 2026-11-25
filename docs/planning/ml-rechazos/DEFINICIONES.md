# Definiciones propuestas para rechazos y recuperacion

Fecha: 2026-11-24. Contrato para revisar antes de implementar ML-02/04. No altera definiciones financieras, ETL ni KPIs existentes.

## Entidades y relojes

- **Obligacion:** cuota/cobro que requiere pago, identificable dentro de fuente y cuenta. Un pago no es automaticamente una obligacion. Una suscripcion agrupa obligaciones, no permite asignar cualquier pago a cualquier rechazo.
- **Intento:** ejecucion informada por proveedor/reporte con resultado y fecha verificables. Un cargo programado futuro no es un intento observado. Un rechazo de transaccion Toku, un cargo VP y una fila mensual TCH no son unidades equivalentes sin adaptador documentado.
- **Evidencia:** codigo/glosa/estado con procedencia; puede referir a cargo, pago o ambos. `payment_rejection_details` conserva evidencias, pero su clave deduplica combinaciones: no asumir que contiene cada intento repetido historico.
- **Episodio P2:** comienza en el primer rechazo verificable de la misma obligacion (`t0`). Reintentos posteriores no generan multiples positivos independientes del mismo pago. El algoritmo de reconstruccion y la politica de nuevos episodios se aprobaran antes del dataset; episodios ambiguos se excluyen y contabilizan.
- **Fecha de evento:** declarada por fuente para rechazo/pago. **Deteccion:** momento en que CRM lo observa. **Disponibilidad:** primer instante en que el sistema podia usar el dato. **Calculo:** momento de emitir la recomendacion. Ninguno sustituye silenciosamente a los otros.
- **Corte de analisis (`as_of`):** instante explicito con zona horaria. **Cobertura efectiva:** intervalo de datos completos verificables por fuente y recurso; no basta con que una sync haya terminado ni con tomar el maximo de una fecha de pago.

Conservar UTC para instantes; presentar hora de Chile. Una fecha calendario sin hora no se convierte en una hora exacta ficticia. La granularidad mensual puede impedir demostrar un plazo de 30 dias.

## Objetivo P1

Pregunta: «¿Que motivo sostiene la evidencia del rechazo?». Salidas: familia/submotivo/gravedad, procedencia y estado de clasificacion. Las ocho familias son candidatas, no etiquetas ya disponibles.

La gravedad informada por proveedor es una dimension propia: un bloqueo puede ser temporal o permanente. Un desconocido devuelve `category=null`, no `ISSUER` por defecto. Regla, modelo y correccion humana deben ser distinguibles; conflictos requieren revision con historial.

La confianza estadistica de P1 no equivale a certeza del codigo oficial, probabilidad de recuperacion ni recomendacion de accion. El modelo puede abstenerse aunque proponga una clase dominante.

## Objetivo P2 a 30 dias

Pregunta propuesta: «Con informacion disponible al calcular, ¿se confirmara el pago completo de esta obligacion antes o al cumplirse 30 dias desde t0, bajo la gestion observada?». Si se calcula despues de t0, informar dias restantes; no reiniciar 30 dias cada vez que se consulta. No entrenar juntos pronosticos emitidos en momentos distintos sin definir poblacion y variables de cada momento.

| Estado de evidencia | Tratamiento para el dataset futuro |
|---|---|
| Positivo verificable | Pago atribuido a la misma obligacion, posterior o igual a t0 y dentro del plazo. Debe representar pago completo confirmado, no solicitud aceptada. |
| Negativo verificable | Ventana completa observable hasta t0+30 dias y ausencia comprobable de pago completo; cobertura y conciliacion suficientes. |
| Inmaduro | Aun no transcurren 30 dias para establecer un negativo. No etiquetar como cero. |
| Censurado/desconocido | Falta fuente, corte, conciliacion, vinculo o fecha; tampoco es cero. |
| Parcial, reversado o ambiguo | Conservar estado separado; politica de pago completo/neto por aprobar. No sumar monedas ni duplicar abonos entre episodios. |

Al comparar modelos se propone usar cohortes con 30 dias completos para ambos resultados, evitando que positivos tempranos y negativos recientes formen poblaciones sesgadas. La ausencia de pago solo es evidencia negativa si sabemos que podiamos observarlo.

No basta `charge_recoveries.status='cobrado'`: su flujo actual de VirtualPOS concilia una ventana de cuatro dias y observa estado; `observed_at`/`closed_at` no son necesariamente la fecha real del pago. Tampoco basta el estado actual de `core_charges` ni una fila `paid` sin enlace verificable y fecha util.

## Variables y particiones

Cada variable debe tener fuente, formula, instante de disponibilidad, nulos, granularidad y version. Los conteos historicos incluyen solo hechos anteriores al calculo; nunca resultado final, ultimo estado conocido en el futuro o numero total de reintentos posterior al rechazo.

No reconstruir retrospectivamente disponibilidad a partir de `updated_at` actual. Para un estudio retrospectivo con eventos anteriores a la primera captura, declarar la limitacion y no llamarlo validacion operativa punto en el tiempo. Mantener futuro estudio prospectivo como confirmacion.

Separar por tiempo de calculo; para cada fold, solo usar etiquetas ya maduras al ajuste. Aplicar una purga de ventanas de resultados solapadas. Si se evalua generalizacion a nuevas suscripciones, crear ademas particion por grupos restringidos: no afirmar generalizacion a personas nuevas sin identidad centralizada confirmada.

## Acciones y medicion

- La politica comprueba estado actual, autorizacion, mandato vigente, limites y datos recientes antes de habilitar cualquier flujo WR. Prediccion antigua no mantiene habilitada una accion.
- P2 no estima efecto de contactar, cambiar tarjeta o reintentar en un dia especifico. Esas estrategias requieren definicion y evidencia adicionales.
- Registrar propuesta mostrada, version/corte, decision humana y resultado observable. Un grupo con mayor probabilidad estimada no es comparable sin mas con otro no priorizado.
- Para atribuir impacto, diseñar evaluacion prospectiva controlada o un metodo justificado, respetando restricciones y sin privar de gestion obligatoria. Las primeras metricas seran cobertura, acuerdo de revision, abstencion y recuperacion observada con denominador/madurez documentados.
