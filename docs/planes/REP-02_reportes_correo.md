# REP-02: reportes automáticos por correo (plan)

Pedido del usuario (2026-11-19): «reportes automaticos por correo». Decisiones: d251 = b (resumen semanal más cierre mensual), d252 = b (HTML con cifras agregadas más CSV agregado adjunto), destinatarios: «Solo a mí», en sandbox y producción, configurados como dato. Planner en sonnet, solo lectura. Sin implementar.

## 0. Destinatarios

Variable nueva `REPORT_EMAIL_TO`, lista separada por comas con el mismo parser que `ALERT_EMAIL_TO` (`alerts.parse_recipients`). Solo en el `.env` real; nunca en código, documentos ni pruebas. `.env.example` la lleva vacía. Sin valor no se envía nada. Sumar destinatarios después es ampliar la lista.

## 1. De dónde sale cada cifra (se reutiliza lo existente)

- Activas por canal, altas y bajas, MRR, churn, cobros y comparación con el mes previo: `build_general_summary(db, month, channels)` en `app/services/dashboard_general.py` (KPI por canal con delta, `_mrr_by_channel`, `_charge_cells`).
- Churn de mes cerrado: `channel_churn.closed_month_churn` y `unified_churn_rate`.
- Cobros aprobados y rechazados: `charge_stats.charge_rejection_stats` y `rejected_month_kpi`.
- Recuperación: `charge_recovery.py` y `recovery_payku.py`, `recovery_toku.py`, `recovery_tch.py` (confirmar la función agregada del recuperador).
- Estado de sincronizaciones: `sync_runs._compute_health(db, now)`, la que ya usan las alertas.
- Altas y bajas por rango (semana): `reports._auto_period_data(db, dfrom, dto)` en `app/api/v1/routes/reports.py` (REP-01).

Falta: extraer `_auto_period_data` y sus ayudantes a `app/services/report_figures.py` (hoy viven en una ruta); adaptadores `weekly_figures` y `monthly_figures` que devuelven solo cifras; confirmar que `_auto_period_data` y `build_general_summary` coinciden en altas y bajas (si no, una sola fuente por cifra, declarada en el pie).

## 2. Diseño

- `app/services/scheduled_reports.py`: `build_weekly` y `build_monthly` devuelven asunto, HTML, CSV y clave de período (`weekly:2026-W47`, `monthly:2026-10`). HTML con estilos en línea y tablas, sin JS ni imágenes externas. CSV: `periodo,canal,activas,altas,bajas,cobros_aprobados,cobros_rechazados,churn,mrr,recuperacion`.
- Envío: `send_report` en `alerts.py`, refactorizando `_send` para aceptar destinatarios y adjuntos con el mismo SMTP, timeout y log (solo el nombre de la clase de la excepción).
- Tareas en `app/scheduler/jobs/report_jobs.py`, registradas en `engine.register_jobs` (zona `America/Santiago`): semanal lunes 07:30 (después de las sincronizaciones de 02:00 y 04:00); mensual con un chequeo diario a las 07:45 que corre solo el primer día hábil (lunes a viernes sin feriados chilenos, tabla en `app/core/business_days.py`; sin el año, lunes a viernes con aviso en el log).
- Banderas propias, separadas de `ALERTS_ENABLED`: `REPORTS_WEEKLY_ENABLED` y `REPORTS_MONTHLY_ENABLED`, apagadas por defecto.
- Idempotencia: tabla de envíos con único `(report_kind, period_key)`; se inserta `sending` con `ON CONFLICT DO NOTHING` antes de enviar y se pasa a `sent` o `failed`; hasta 3 intentos; `sending` de más de 30 minutos se reintenta; `misfire_grace_time` de 6 h y `coalesce=True` si el backend estuvo caído.
- Envío de prueba: `POST /api/v1/scheduler/reports/test` (`kind=weekly|monthly`), solo administrador, con `period_key` `test:<timestamp>`. Botón junto a las tareas programadas en Administración › Sincronizaciones.
- No escribe en `sync_runs` ni `etl_runs` (aparecería como canal).

## 3. Configuración nueva (agregar los nombres a `.env.example`)

`REPORTS_WEEKLY_ENABLED`, `REPORTS_MONTHLY_ENABLED`, `REPORT_EMAIL_TO`, `REPORT_WEEKLY_HOUR` y `REPORT_MONTHLY_HOUR` (opcionales). Reutiliza `ALERT_SMTP_*` y `ALERT_EMAIL_FROM`. Sandbox: solo corre con `SANDBOX_SCHEDULER_ENABLED=true`; se valida en `Settings` que en sandbox `REPORT_EMAIL_TO` tenga una sola dirección; el asunto lleva el ambiente (`[SynkmetriX · sandbox]`).

## 4. Migración

Tabla `report_dispatches`: `id` uuid, `report_kind`, `period_key`, `status`, `attempts`, `recipients_count` (cantidad, no direcciones), `error_class` (nombre de la clase), `created_at`, `sent_at`; único `(report_kind, period_key)`. Número: la siguiente libre sobre `20261118_0083` en el momento de implementar (AUTH-04 también propone una migración; la que se integre primero toma la 0084).

## 5. Pruebas (sin SMTP real)

`tests/test_scheduled_reports.py` y `tests/test_report_jobs.py`: SMTP simulado como en `tests/test_alerts.py`; sin bandera, sin destinatarios o sin host no envía; idempotencia (mismo período una vez, fallo se reintenta); primer día hábil (mes que empieza en sábado, domingo, lunes y feriado); fronteras de semana y mes en `America/Santiago` con cambio de hora; **sin datos personales**: se siembran socios con nombre, RUT, correo y teléfono reconocibles y se comprueba que ni el HTML ni el CSV los contienen, ni patrones de RUT o correo, ni `<script` o URLs externas; tope de un destinatario en sandbox; el envío de prueba exige administrador.

## 6. Orden de trabajo

1. Backend: extraer `report_figures.py` sin cambiar comportamiento (pruebas de reportes en verde).
2. Backend: `business_days.py` y pruebas.
3. Backend: configuración, `.env.example`, migración y modelo.
4. Backend: `scheduled_reports.py` y `send_report` con adjuntos, con pruebas (incluida la de datos personales).
5. Backend: tareas, registro en el programador e idempotencia.
6. Backend: endpoint de prueba.
7. Frontend: botón de prueba.
8. Docs: `docs/data/scheduled_reports.md` y nota en la documentación de alertas.

Ventana: sandbox primero con el correo del usuario y un envío de prueba; en producción, migración antes de reiniciar, fuera de 02:00 a 04:30; las banderas se encienden después de revisar la prueba.

## 7. Riesgos y preguntas abiertas

- MRR y churn son sensibles aunque estén agregados; el correo viaja por el SMTP de las alertas.
- Un canal con muy pocos socios podría hacer identificable a alguien: conviene un mínimo de agregación.
- Feriados chilenos: tabla que hay que actualizar cada año.
- Por definir con el usuario (valores por defecto propuestos): si el backend estuvo caído, se envía tarde dentro de 6 h; el CSV lleva 13 meses; horas 07:30 y 07:45; el estado de sincronizaciones se calcula al armar el correo.
