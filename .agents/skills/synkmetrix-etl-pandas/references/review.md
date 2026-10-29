# Casos de revision de ETL

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Cargar reporte TCH proporcionado por ruta | Hojas compatibles, comparacion con cargas existentes y corrida trazada | Reimportacion innecesaria o borrar historia con un solo archivo |
| Reprocesar dos ventanas con cargos repetidos | Mismos hechos finales y conteos explicados | Deduplicar por archivo o eliminar intentos legitimos |
| Core con dos clientes que comparten RUT | No asignar una suscripcion arbitrariamente; conservar ambiguedad | Primer match determina identidad |

Los logs de pruebas usan IDs sinteticos y conteos. No guardar archivos reales, payloads sensibles ni capturas personales en fixtures versionadas.
