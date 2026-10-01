# Operations Overview

## Scheduler

APScheduler registra una sincronizacion diaria de canales y expone ejecuciones y progreso SSE. TCH se consolida cuando sus datos Excel ya fueron cargados; la carga Excel no esta automatizada por scheduler.

## Sincronizaciones y ETL

- VirtualPOS, Toku y Payku sincronizan datos desde API hacia staging saneado.
- TCH se carga mediante ETL desde reportes Excel.
- La consolidacion transforma tablas por canal hacia entidades CRM iniciales.
- `sync_runs` y `etl_runs` registran ejecuciones; `write_runs` registra operaciones mutables autorizadas.

## Writes y recovery

Las escrituras de proveedores se realizan solo por API interna, permisos, CSRF y banderas locales. El recuperador VirtualPOS expone seguimiento de canceladas, reintentos y tarjetas vencidas.

## Logs y salud

- Los procesos registran logs locales bajo `logs/`.
- `GET /health` expone el estado de la API.
- Metricas, alertas y tracing de produccion: NO DETERMINADO.

## Referencias tecnicas

- [Motor scheduler](../../app/scheduler/engine.py)
- [Job de sincronizacion](../../app/scheduler/jobs/sync_all.py)
- [Bus SSE](../../app/scheduler/event_bus.py)
- [Servicios](../../app/services/)
- [Scripts](../../scripts/)
- [API principal](../../app/main.py)
- [Operacion local](../../README.md)
