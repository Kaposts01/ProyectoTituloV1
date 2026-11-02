# Alertas por correo de sincronización (SYNC-D-08)

> Código: `app/services/alerts.py`, `app/services/billing_alerts.py` (BILL-22), `app/scheduler/jobs/alert_jobs.py` (job `alerts_check`). Pruebas: `tests/test_alerts.py`, `tests/test_billing_alerts.py`.
> **Estado: listo y probado con un servidor SMTP falso en memoria. Apagado por defecto (`ALERTS_ENABLED=false`). Nunca se envió un correo real.**
> Decisión D15: las alertas van por correo; el destinatario se define SOLO por variable de entorno, nunca en el código ni en documentos.

## Qué avisa (condiciones)

El job corre cada 15 minutos (minutos :02, :17, :32 y :47, hora de Chile) y evalúa:

| Clave | Condición | Umbral |
|---|---|---|
| `sync_fail:<canal>` | Canal degradado o en falla | 2 o más corridas fallidas seguidas, **o** 2 o más días sin una sincronización exitosa (`consecutive_failures`, `days_without_success` de `/sync-runs/health`) |
| `core_lag:<canal>` | ETL Core atrasado | `core_lag_hours` mayor a 24 h (VirtualPOS, Toku, Payku) |
| `webhook_failed` | Eventos de webhook en `failed` | Al menos uno recibido o procesado en las últimas 24 h |
| `cancellation_stuck` | Solicitudes de baja atascadas | `requires_reconciliation`, o `applying` sin actividad por más de 30 min |
| `billing_stuck` | Solicitudes de cambio de cobro atascadas | `requiere_conciliacion`, o `aplicando` sin actividad por más de 30 min |
| `billing_reconciliation:queue` | Cobros del CRM o `write_runs` en conciliación fuera de una solicitud en conciliación (BILL-22) | Al menos uno (cola de BILL-10); bloquean su suscripción |
| `billing_reconciliation:stale` | Cola de conciliación abierta demasiado tiempo (BILL-22, PI-05) | Algún elemento (solicitud, cobro o `write_run`) abierto hace más de 24 h |
| `billing_reconciliation:swept` | Solicitudes barridas por `billing_sweep_applying` (BILL-22) | Al menos una pasada de `aplicando` a `requiere_conciliacion` por el barrido en las últimas 24 h |

## Deduplicación y recuperación

- Una alerta por condición al activarse. Mientras siga activa, **un recordatorio como máximo cada 6 horas**.
- Al normalizarse se envía un aviso «Recuperado» (una sola vez). Si vuelve a fallar, sale una alerta nueva de inmediato.
- Si el envío falla (SMTP caído), la alerta se reintenta en el siguiente chequeo (15 min); no hay reintentos dentro del mismo chequeo.
- El estado vive en `source_records` (`source='alert_state'`, `resource_type='condition'`, `external_id=<clave>`), **sin migración**.
  El payload solo guarda `active`, `since`, `last_sent_at` y `last_resolved_at`.

## Contenido del correo (sin datos personales)

Asunto: `[SynkmetriX · <ambiente>] Alerta|Recordatorio|Recuperado: <condición>`. Cuerpo en español con canal, condición, desde cuándo
(hora de Chile), contadores y un enlace **relativo** al panel (`/admin/sincronizaciones`, `/general/cambios-de-cobro`). Nunca se incluyen
`error_message`, ids de suscripción, RUT, correos ni textos libres. Los fallos del SMTP solo dejan en el log el nombre de la clase de la excepción.

## Variables de entorno (solo nombres; vacías en `.env.example`)

| Variable | Uso |
|---|---|
| `ALERTS_ENABLED` | `true` para encender (por defecto `false`) |
| `ALERT_EMAIL_TO` | **Obligatoria.** Destinatario(s), separados por coma. Si falta no se envía nada y queda un aviso en el log |
| `ALERT_EMAIL_FROM` | Remitente (si está vacío se usa `ALERT_SMTP_USER`) |
| `ALERT_SMTP_HOST` | Servidor SMTP. Obligatoria; si falta no se envía y queda un aviso en el log |
| `ALERT_SMTP_PORT` | Puerto (587 por defecto; el 465 usa SMTP sobre SSL) |
| `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD` | Autenticación (solo si el servidor la exige; ambas deben estar definidas) |
| `ALERT_SMTP_STARTTLS` | `true` por defecto: usa STARTTLS en puertos distintos de 465 |

Timeout de conexión: 10 s. Con `ALERTS_ENABLED=false` el job no abre ninguna sesión ni conexión.

## Cómo probar el envío sin correo real

1. Pruebas automáticas: `pytest tests/test_alerts.py` (SMTP falso en memoria; destinatario ficticio `alerts@example.test`).
2. Prueba manual local con un servidor de depuración que solo imprime los mensajes (no entrega nada):
   `python -m aiosmtpd -n -l localhost:1025` (si no está instalado, cualquier servidor de depuración equivalente), con
   `ALERTS_ENABLED=true`, `ALERT_EMAIL_TO=alerts@example.test`, `ALERT_SMTP_HOST=localhost`, `ALERT_SMTP_PORT=1025` y `ALERT_SMTP_STARTTLS=false`
   en el proceso del backend **sandbox** (nunca contra `crm`). Provocar una condición (p. ej. dos `sync_runs` fallidos en `crm_sandbox`) y esperar el siguiente tick.

## Qué debe hacer el usuario

Nada de esto lo hace un agente.

1. Definir en su `.env` real (nunca en Git ni en el chat): `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD`,
   `ALERT_SMTP_STARTTLS`, `ALERT_EMAIL_FROM` y `ALERT_EMAIL_TO` (su correo de destino).
2. Encender `ALERTS_ENABLED=true`.
3. **Reiniciar el backend** (no se recarga solo). No requiere migración.
4. Verificar: el job `alerts_check` aparece en `GET /api/v1/scheduler/jobs`; el primer correo llega cuando exista una condición activa.

## Límites conocidos

- Depende de que el backend (y el PC) estén encendidos; si el proceso está caído, no hay alertas (SYNC-D-18 / DEC-11).
- Un canal que oscila entre fallar y recuperarse genera una alerta y un «recuperado» cada vez (sin supresión de oscilaciones).
- La salud de TCH se evalúa desde `etl_runs`; sus cargas dependen de que alguien suba el Excel.
- Las bajas atascadas no tienen pantalla todavía (MGT-15): el enlace apunta a la API de consulta.
