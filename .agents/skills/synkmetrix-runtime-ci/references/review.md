# Casos de revision de entorno y CI

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Levantar servidores con Docker sin virtualizacion | Causa concreta y alternativa decidida antes de cambiar base | Crear silenciosamente otro CRM vacio |
| Cambiar las API keys en .env | Proceso recargado y presencia verificada sin imprimir claves | UI usa configuracion cacheada o logs revelan token |
| CI falla al aplicar migraciones | Reproduccion aislada con cadena y dependencias bloqueadas | Saltar migraciones o reemplazar PostgreSQL por SQLite |

Una comprobacion de puerto debe distinguir una instancia del proyecto de otro servicio del equipo. Las comprobaciones de login imprimen solo estados y conteos, nunca cookies o contrasenas.
