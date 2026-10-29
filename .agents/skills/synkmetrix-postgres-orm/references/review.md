# Casos de revision de persistencia

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Conservar el mismo email para dos clientes del mismo canal | Ambas asociaciones sobreviven y conservan procedencia | UNIQUE por valor elimina una asociacion |
| Agregar columna obligatoria a una tabla poblada | Migracion nueva, estrategia para filas anteriores y compatibilidad durante despliegue | Editar una revision aplicada o bloquear el servicio sin evaluacion |
| Acelerar listado de cargos | Consulta y plan comparables, filtro y orden estables, indice justificado | Ordenar despues de paginar o indice que no sirve al predicado |

No usar `DELETE`, `TRUNCATE`, restauraciones o downgrade contra la base operativa para obtener una prueba verde. Los IDs sintéticos y secretos de pruebas no se toman de `.env` operativo.
