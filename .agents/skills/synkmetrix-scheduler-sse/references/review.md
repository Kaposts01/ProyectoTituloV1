# Casos de revision de jobs y streaming

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Doble click en sincronizar | Una ejecucion efectiva o rechazo trazable segun contrato | Dos jobs que escriben la misma fuente |
| Recargar pagina durante sincronizacion | Reconectar y consultar estado durable aunque el bus no exista | Stream perdido interpretado como fallo del job |
| Dos workers arrancan mientras otro sincroniza | Propiedad/exclusion evaluada por instancia | Limpieza startup marca trabajo ajeno como fallido |

En una prueba de fallo de consolidacion, observa tanto `etl_runs` como el evento terminal. Un mensaje de error intermedio seguido de completed no certifica exito completo.
