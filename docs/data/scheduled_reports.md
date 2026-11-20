# Reportes automáticos por correo (REP-02)

Resumen semanal y cierre mensual enviados por correo. Decisiones del usuario: d251 = b (semanal más cierre mensual), d252 = b (HTML con cifras agregadas más CSV agregado adjunto) y destinatarios «solo a mí», en sandbox y producción, como dato del `.env`. Plan: `docs/planes/REP-02_reportes_correo.md`. Son distintos de las alertas (`docs/data/alerts.md`): comparten el SMTP, pero tienen sus propias banderas, tabla y tareas.

## Qué se envía

| Reporte | Cuándo (America/Santiago) | Período que reporta | Clave de período |
|---|---|---|---|
| Resumen semanal | lunes 07:30 | la última semana completa (lunes a domingo) | `weekly:2026-W47` (semana ISO reportada) |
| Cierre mensual | primer día hábil del mes, 07:45 | el mes calendario anterior | `monthly:2026-10` |

Cada correo lleva un HTML (tablas con estilos en línea; sin JavaScript, imágenes ni enlaces) y un CSV adjunto con las columnas `periodo,canal,activas,altas,bajas,cobros_aprobados,cobros_rechazados,churn,mrr,recuperacion`. El semanal adjunta la semana reportada y la anterior; el mensual, los últimos 13 meses. El HTML muestra el período, el período anterior, y el estado de las sincronizaciones calculado al armar el correo. Asunto: `[SynkmetriX · <ambiente>] Resumen semanal …` o `Cierre mensual <mes año>`.

Fuente de cada cifra (una sola por cifra): altas, bajas, activas, cobros aprobados y rechazados, y churn salen de `app/services/report_figures.py` (`auto_period_data`, la misma de `/reports/automatic`, REP-01); el MRR, de `dashboard_general._mrr_by_channel` (foto al armar el correo: no hay MRR histórico, por eso solo se llena el período más reciente); la recuperación, de `charge_recoveries` (reintentos cobrados y cerrados en el período); el estado de sincronizaciones, de `sync_runs._compute_health`.

## Qué NO lleva (datos personales)

Solo cifras agregadas por canal. Nunca nombres, RUT, correos, teléfonos ni ids de socios o suscripciones; tampoco mensajes de error. Lo comprueba una prueba que siembra socios con esos datos y verifica que no aparecen en el HTML, el CSV, el texto ni el asunto (ni patrones de RUT o correo, ni `<script`, ni URLs).

**Mínimo de agregación.** Una cifra de un canal que salga de 1 a 4 socios se muestra como `<5` (el 0 se muestra tal cual). Para que no se pueda restar, el total de una columna con alguna cifra enmascarada sale como `—`; el churn sale como `—` si sus insumos (bajas o activas iniciales) son pequeños; el MRR se enmascara si el canal tiene menos de 5 clientes activos. **Cruce entre períodos.** Como activas(t) − activas(t−1) = altas(t) − bajas(t), una cifra pequeña oculta se despejaría restando períodos vecinos del correo o del CSV. Por eso, si en algún período mostrado juntos (semana actual y anterior; los 13 meses del CSV) altas, bajas o activas de un canal están enmascaradas, las activas de ese canal salen como `<5` en todos esos períodos, y el total de activas como `—` donde un canal quedó oculto (`protect_series`). Costo: un canal con alguna cifra pequeña pierde la columna de activas en esa ventana. El semáforo de 5 es `MIN_GROUP` en `app/services/scheduled_reports.py`.

## Variables de entorno (solo nombres; `.env.example` las lleva sin valores)

| Variable | Efecto |
|---|---|
| `REPORTS_WEEKLY_ENABLED` | enciende el semanal (apagada por defecto) |
| `REPORTS_MONTHLY_ENABLED` | enciende el mensual (apagada por defecto) |
| `REPORT_EMAIL_TO` | destinatarios, lista separada por comas (mismo parser que `ALERT_EMAIL_TO`). Sin valor no se envía nada. Solo en el `.env` real |
| `REPORT_WEEKLY_HOUR`, `REPORT_MONTHLY_HOUR` | hora (0-23) de Chile; opcionales, por defecto 7 (minutos fijos: 30 y 45) |

Reutiliza `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD`, `ALERT_SMTP_STARTTLS` y `ALERT_EMAIL_FROM`; sin `ALERT_SMTP_HOST` no se envía. Son independientes de `ALERTS_ENABLED`. **Sandbox/qa:** el programador solo corre con `SANDBOX_SCHEDULER_ENABLED=true`; `Settings` rechaza arrancar si `REPORT_EMAIL_TO` tiene más de una dirección, y el asunto lleva el ambiente. Como producción y sandbox pueden compartir el `.env`, ampliar la lista en producción exige una variable propia del sandbox o quitar el segundo destinatario ahí.

## Idempotencia, reintentos y envío tardío

Tabla `report_dispatches` (migración `20261120_0085`), una fila por `(report_kind, period_key)`, única: `status` (`sending`, `sent`, `failed`), `attempts`, `recipients_count` (cantidad, nunca direcciones), `error_class` (nombre de la clase, nunca el mensaje), `created_at`, `updated_at`, `sent_at`.

- Antes de enviar se reserva la fila con `INSERT … ON CONFLICT DO NOTHING`; luego pasa a `sent` o `failed`. Un período se envía una sola vez aunque el programador corra dos veces.
- Un fallo se reintenta hasta 3 intentos en total (el job espera 2 minutos entre intentos). Un `sending` con más de 30 minutos (proceso caído a medio envío) se reintenta. Agotados los 3 intentos no se reintenta más: hay que mirar la fila y el log.
- Envío tardío: las tareas tienen `misfire_grace_time` de 6 h y `coalesce`. Como `register_jobs` reemplaza los jobs del almacén al arrancar, un reinicio no recupera por sí solo una ejecución vencida; por eso 2 minutos después de arrancar corre `report_catch_up`, que envía lo vencido si estamos dentro de las 6 h posteriores a la hora programada (la tabla evita el doble envío).
- El mensual corre un chequeo diario a las 07:45 y solo actúa el primer día hábil (lunes a viernes sin feriados chilenos). Los feriados están en `app/core/business_days.py` para 2026 y 2027; **hay que actualizar la tabla cada año** (sin el año, se usa lunes a viernes y queda un aviso en el log). El 21 de junio y el 17 de septiembre de 2027 conviene confirmarlos con el decreto oficial.
- Los jobs son `report_weekly`, `report_monthly` y `report_catch_up` (`GET /api/v1/scheduler/jobs`). No escriben en `sync_runs` ni `etl_runs`.

## Envío de prueba (sin esperar al calendario)

`POST /api/v1/scheduler/reports/test` con `{"kind": "weekly"}` o `{"kind": "monthly"}`. Solo administrador, con CSRF. Ignora las banderas `REPORTS_*` (no la falta de destinatario o de SMTP), usa la clave `test:<marca de tiempo>` (no consume el envío real del período) y responde solo la cantidad de destinatarios (200), `409` con el motivo si falta configuración, o `502` con el nombre de la clase del error.

Probar en sandbox sin correo real: levantar el SMTP de depuración (`scripts/maintenance/debug_smtp_server.py --port 1025`, ver `docs/data/alerts.md`), con `APP_ENV=sandbox`, `ALERT_SMTP_HOST=127.0.0.1`, `ALERT_SMTP_PORT=1025`, `ALERT_SMTP_STARTTLS=false` y `REPORT_EMAIL_TO` con una dirección ficticia, y llamar al endpoint con el backend sandbox. El correo (con su CSV) queda en la consola o en `--out-dir`; no sale nada de este equipo. El botón del frontend (paso 7 del plan) queda para una tanda posterior.

## Ventana de puesta en marcha

Sandbox primero con el envío de prueba. En producción: migración 0085 antes de reiniciar, fuera de 02:00 a 04:30, y encender las banderas después de revisar la prueba. Rollback: apagar las banderas; `downgrade` de la 0085 elimina la tabla.

## Pruebas

`tests/test_scheduled_reports.py` (períodos con cambio de hora, mínimo de agregación, CSV, sin datos personales, envío), `tests/test_report_jobs.py` (banderas, idempotencia, reintentos, primer día hábil, registro), `tests/test_business_days.py`, `tests/test_report_settings.py` (configuración y migración) y `tests/test_report_test_endpoint.py`. Todo con SMTP simulado y destinatarios ficticios.
