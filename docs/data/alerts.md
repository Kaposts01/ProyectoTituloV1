# Alertas por correo de sincronización (SYNC-D-08, L5-ALERTAS)

> Código: `app/services/alerts.py`, `app/services/billing_alerts.py` (BILL-22), `app/services/ops_alerts.py` y
> `app/services/business_alerts.py` (d139), `app/scheduler/jobs/alert_jobs.py` (job `alerts_check`),
> `app/api/v1/routes/health.py` (heartbeat). Scripts: `scripts/maintenance/send_test_alert.py`,
> `scripts/maintenance/debug_smtp_server.py`, `scripts/maintenance/heartbeat_check.py`.
> Pruebas: `tests/test_alerts.py`, `tests/test_billing_alerts.py`, `tests/test_l5_alerts.py`.
> **Estado: listo y probado con un servidor SMTP falso en memoria y con el SMTP de depuración local. Apagado por defecto
> (`ALERTS_ENABLED=false`). Nunca se envió un correo real.**
> Decisión D15: las alertas van por correo; el destinatario se define SOLO por variable de entorno, nunca en el código ni en documentos.

## Inventario de alertas

El job corre cada 15 minutos (minutos :02, :17, :32 y :47, hora de Chile). Cada fuente se registra con
`register_condition_provider(kind, evaluate, describe, enabled)`; todas comparten la deduplicación, el recordatorio
cada 6 h y el aviso «Recuperado». `alerts.active_kinds()` devuelve las que se evalúan con la configuración actual.

**Paquete mínimo (d138):** con solo `ALERTS_ENABLED=true` quedan activas `sync_fail`, `core_lag`, `cancellation_stuck`,
`billing_stuck` y `billing_reconciliation`. Todo lo demás queda detrás de su propia bandera.

| Kind (clave) | Condición | Bandera | Por defecto (con `ALERTS_ENABLED=true`) |
|---|---|---|---|
| `sync_fail:<canal>` | 2 o más corridas fallidas seguidas, **o** 2 o más días sin sync exitosa, **o desde el PRIMER fallo** si la última corrida de una fuente del canal falló por configuración o credencial (d139a: «Configuracion incompleta», «not configured», 401/403, `Bearer` vacío). Los demás fallos mantienen el umbral de 2 | — | Activa |
| `core_lag:<canal>` | `core_lag_hours` > 24 h (VirtualPOS, Toku, Payku) | — | Activa |
| `cancellation_stuck` | Bajas en `requires_reconciliation`, o `applying` más de 30 min | — | Activa |
| `billing_stuck` | Cambios de cobro en `requiere_conciliacion`, o `aplicando` más de 30 min | — | Activa |
| `billing_reconciliation:queue` | Cobros del CRM o `write_runs` en conciliación fuera de una solicitud en conciliación (BILL-22) | — | Activa |
| `billing_reconciliation:stale` | Algún elemento de la cola de conciliación abierto hace más de 24 h (PI-05) | — | Activa |
| `billing_reconciliation:swept` | Solicitudes barridas de `aplicando` a `requiere_conciliacion` en las últimas 24 h | — | Activa |
| `webhook_failed` | Eventos de webhook en `failed` en las últimas 24 h | `WEBHOOK_PROCESSOR_ENABLED` | Apagada |
| `webhook_lag` | Evento pendiente más viejo que `ALERT_WEBHOOK_LAG_MINUTES` (60) | `WEBHOOK_PROCESSOR_ENABLED` | Apagada |
| `webhook_silence:<canal>` | Canal que ya recibió webhooks lleva `ALERT_WEBHOOK_SILENCE_HOURS` h sin recibir | `ALERT_WEBHOOK_SILENCE_HOURS` > 0 | Apagada |
| `removal_aborted:<canal>` | Bajas por desaparición abortadas por superar el umbral (SYNC-D-13) | `SYNC_REMOVAL_DETECTION_ENABLED` | Apagada |
| `report_stale:toku` | Último reporte Toku cargado hace más de `REPORT_MAX_AGE_DAYS` (7) días, ninguno cargado, o algún tipo con datos (fecha de generación) de más de 7 días (DEC-21) | `ALERT_REPORT_AGE_ENABLED` | Apagada |
| `report_stale:tch` | Último Excel TCH cargado hace más de 7 días, o ninguno cargado | `ALERT_REPORT_AGE_ENABLED` | Apagada |
| `write_failed` | `write_runs` en `failed` en las últimas 24 h (los de `reconciliation_required` ya los avisa `billing_reconciliation`) | `ALERT_WRITE_FAILED_ENABLED` | Apagada |
| `business_rejection_rate:<canal>[:<YYYY-MM>]` | Panel: «Tasa de rechazo global elevada» (> 40 %, 3 meses) o «Alta tasa de rechazo» (> 50 %) del mes actual o anterior | `ALERT_BUSINESS_ENABLED` | Apagada |
| `business_churn:<canal>` | Panel: «Churn rate elevado» (> 20 %) | `ALERT_BUSINESS_ENABLED` | Apagada |
| `business_rejection_streak:<canal>` | Panel: «Racha de rechazos» (más de 20 suscripciones activas con 2+ rechazos seguidos) | `ALERT_BUSINESS_ENABLED` | Apagada |
| `business_no_recent_charge:<canal>` | Panel: «Sin cobro reciente» (> 40 % de activas sin cobro exitoso en 6 meses) | `ALERT_BUSINESS_ENABLED` | Apagada |

Notas:

- **Alertas de negocio (d139d):** no repiten ningún cálculo. `business_alerts` llama a las mismas funciones del panel
  (`staging._general_dashboard`, `_vp_centralized_dashboard`, `_toku_centralized_dashboard`, `_payku_centralized_dashboard`)
  y toma solo las de severidad `alta`. Como esos tableros son pesados, se reevalúan como máximo cada
  `ALERT_BUSINESS_EVAL_MINUTES` (60). Si un tablero falla, se conservan sus últimas condiciones (no se envía un «Recuperado» falso).
  De las de rechazo por canal y mes solo cuentan el mes actual y el anterior: el panel muestra toda la historia.
- Si se apaga la bandera de una fuente con una condición ya avisada, el siguiente chequeo envía su «Recuperado».
- **etl_run fallido (d139b):** `POST /etl/full-sync` ya no deja `completed` cuando falla un canal: queda `partial` (algún canal
  sincronizó) o `failed` (ninguno), con `channels_failed`, igual que el job nocturno. Así lo ven `/sync-runs/health` y el reintento.

## Deduplicación y recuperación

- Una alerta por condición al activarse. Mientras siga activa, **un recordatorio como máximo cada 6 horas**.
- Al normalizarse se envía un aviso «Recuperado» (una sola vez). Si vuelve a fallar, sale una alerta nueva de inmediato.
- Si el envío falla (SMTP caído), la alerta se reintenta en el siguiente chequeo (15 min); no hay reintentos dentro del mismo chequeo.
- El estado vive en `source_records` (`source='alert_state'`, `resource_type='condition'`, `external_id=<clave>`), **sin migración**.
  El payload solo guarda `active`, `since`, `last_sent_at` y `last_resolved_at`.

## Contenido del correo (sin datos personales)

Asunto: `[SynkmetriX · <ambiente>] Alerta|Recordatorio|Recuperado: <condición>`. Cuerpo en español con canal, condición, desde cuándo
(hora de Chile), contadores y un enlace **relativo** al panel. Nunca se incluyen `error_message`, ids de suscripción, RUT, correos,
nombres de archivo ni textos libres. Los fallos del SMTP solo dejan en el log el nombre de la clase de la excepción.

## Variables de entorno (solo nombres; vacías o en su valor por defecto en `.env.example`)

| Variable | Uso |
|---|---|
| `ALERTS_ENABLED` | `true` para encender (por defecto `false`) |
| `ALERT_EMAIL_TO` | **Obligatoria.** Destinatarios separados por coma, con o sin espacios (d140): `a@dominio, b@dominio`. Todos reciben todo. Cada elemento se valida (forma `x@dominio.tld`); los inválidos se omiten y el log solo dice cuántos. Los repetidos se envían una vez. Si no queda ninguno válido no se envía nada |
| `ALERT_EMAIL_FROM` | Remitente (si está vacío se usa `ALERT_SMTP_USER`) |
| `ALERT_SMTP_HOST` | Servidor SMTP. Obligatoria; si falta no se envía y queda un aviso en el log |
| `ALERT_SMTP_PORT` | Puerto (587 por defecto; el 465 usa SMTP sobre SSL) |
| `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD` | Autenticación (solo si el servidor la exige; ambas deben estar definidas) |
| `ALERT_SMTP_STARTTLS` | `true` por defecto: usa STARTTLS en puertos distintos de 465 |
| `ALERT_WEBHOOK_LAG_MINUTES`, `ALERT_WEBHOOK_SILENCE_HOURS` | Umbrales de webhooks (RT-13) |
| `ALERT_BUSINESS_ENABLED`, `ALERT_BUSINESS_EVAL_MINUTES` | Alertas de negocio (apagadas; 60 min entre recálculos) |
| `ALERT_REPORT_AGE_ENABLED` | Reportes Toku/TCH viejos (apagada) |
| `ALERT_WRITE_FAILED_ENABLED` | Escrituras fallidas (apagada) |
| `HEARTBEAT_MAX_SYNC_AGE_HOURS` | Horas sin sync exitosa para que el heartbeat diga `degraded` (36) |

Timeout de conexión: 10 s. Con `ALERTS_ENABLED=false` el job no abre ninguna sesión ni conexión.

## Probar en sandbox con un SMTP de depuración (d137)

Primero siempre en **sandbox** (`APP_ENV=sandbox`, base `crm_sandbox`), nunca contra `crm`. No hace falta instalar nada:
Python 3.12+ ya no trae `smtpd` y `aiosmtpd` no está en el venv, así que el repo trae un servidor de depuración con la biblioteca estándar.

1. **Levantar el SMTP de depuración** (otra terminal; escucha solo en este equipo, imprime cada correo y no reenvía nada):

   ```powershell
   .venv\Scripts\python.exe scripts\maintenance\debug_smtp_server.py --port 1025
   # opcional: guardar cada correo como .eml
   .venv\Scripts\python.exe scripts\maintenance\debug_smtp_server.py --port 1025 --out-dir $env:TEMP\alertas
   ```

   (Si se prefiere `aiosmtpd`, `python -m aiosmtpd -n -l localhost:1025` es equivalente, pero requiere instalarlo.)

2. **Variables del backend sandbox** (en el `.env` de sandbox, nunca en Git):

   ```
   APP_ENV=sandbox
   ALERTS_ENABLED=true
   ALERT_EMAIL_TO=alerts@example.test, otra@example.test
   ALERT_EMAIL_FROM=crm-sandbox@example.test
   ALERT_SMTP_HOST=127.0.0.1
   ALERT_SMTP_PORT=1025
   ALERT_SMTP_STARTTLS=false
   ALERT_SMTP_USER=
   ALERT_SMTP_PASSWORD=
   ```

   El servidor de depuración no habla STARTTLS ni AUTH: por eso `ALERT_SMTP_STARTTLS=false` y usuario/clave vacíos.
   Para que el job corra solo en sandbox también hace falta `SANDBOX_SCHEDULER_ENABLED=true`.

3. **Correo de prueba por el pipeline real** (`send_test_alert.py`; dry-run por defecto, se niega fuera de sandbox salvo `--allow-non-sandbox`):

   ```powershell
   $env:PYTHONPATH='.'; .venv\Scripts\python.exe scripts\maintenance\send_test_alert.py           # dry-run: imprime el aviso
   $env:PYTHONPATH='.'; .venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --send    # lo envía al SMTP de depuración
   $env:PYTHONPATH='.'; .venv\Scripts\python.exe scripts\maintenance\send_test_alert.py --send --full-check  # chequeo completo contra crm_sandbox
   ```

4. Opcional: provocar una condición real en `crm_sandbox` (p. ej. un `sync_run` fallido de Payku por configuración) y esperar el siguiente tick, o usar `--full-check`.
5. Recién con eso verificado, configurar el SMTP real en producción (sección «Qué debe hacer el usuario»).

Pruebas automáticas: `pytest tests/test_alerts.py tests/test_l5_alerts.py` (SMTP falso en memoria y el SMTP de depuración en
`127.0.0.1` con puerto efímero; destinatarios ficticios `@example.test`).

## Heartbeat (d139c)

DEC-11 (hosting) sigue pendiente, así que se implementó la mitad local:

- **Endpoint `GET /api/v1/health/heartbeat`**, sin sesión, para un monitor externo. Solo metadatos: `status`
  (`ok` | `degraded` | `error`), `problems` (`sync_stale`, `scheduler_stopped`), `environment`, `database`,
  `sync.last_success_at` y `sync.channels.<canal>` (último sync exitoso por canal; TCH desde `etl_runs`), y
  `scheduler.expected`, `scheduler.running`, `scheduler.last_job_success_at` (último job del scheduler terminado sin
  excepción, en memoria del proceso) y `scheduler.last_etl_run_success_at`. Sin datos personales, mensajes de error ni ids.
  `degraded` si la última sync exitosa tiene más de `HEARTBEAT_MAX_SYNC_AGE_HOURS` h o el scheduler debería correr y no corre;
  `503` con `status=error` si la base no responde. Respuesta con `Cache-Control: no-store`.
- **Script `scripts/maintenance/heartbeat_check.py`** para el Programador de tareas de Windows: consulta el endpoint y, si el
  backend no responde (conexión rechazada, timeout, 5xx o respuesta ilegible), envía un correo por el mismo SMTP de las
  alertas. Con `--alert-on-degraded` también avisa si responde `degraded`. Misma deduplicación (aviso, recordatorio cada 6 h,
  «Recuperado»), con estado en un JSON local (`--state-file`, por defecto en `%TEMP%`). Respeta `ALERTS_ENABLED`; `--dry-run`
  solo imprime. Código de salida: 0 sano, 1 degradado, 2 caído.

  Tarea programada sugerida (cada 10 min; ajustar rutas):

  ```powershell
  $repo = "C:\ruta\al\repo"
  $action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\python.exe" `
    -Argument "scripts\maintenance\heartbeat_check.py --url http://localhost:8000" -WorkingDirectory $repo
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName "SynkmetriX heartbeat" -Action $action -Trigger $trigger
  ```

  La tarea necesita `PYTHONPATH` apuntando al repo (o un `.cmd` que lo defina) y las variables `ALERT_*` en su `.env`.
  Límite: si se apaga el mismo PC que corre el backend, la tarea tampoco corre; el monitor realmente externo queda para DEC-11.

## Qué debe hacer el usuario

Nada de esto lo hace un agente.

1. Probar en sandbox con el SMTP de depuración (sección anterior).
2. Definir en su `.env` real (nunca en Git ni en el chat): `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD`,
   `ALERT_SMTP_STARTTLS`, `ALERT_EMAIL_FROM` y `ALERT_EMAIL_TO` (uno o varios correos separados por coma).
3. Encender `ALERTS_ENABLED=true` (paquete mínimo). Encender las banderas extra que quiera (`ALERT_BUSINESS_ENABLED`,
   `ALERT_REPORT_AGE_ENABLED`, `ALERT_WRITE_FAILED_ENABLED`).
4. **Reiniciar el backend** (no se recarga solo). Las alertas no requieren migración (la 20261103_0068 es del permiso d136).
5. Verificar: el job `alerts_check` aparece en `GET /api/v1/scheduler/jobs`; `GET /api/v1/health/heartbeat` responde `ok`.
6. Opcional: registrar `heartbeat_check.py` en el Programador de tareas.

## Límites conocidos

- El job depende de que el backend (y el PC) estén encendidos; el heartbeat local mitiga, pero el monitor externo real depende de DEC-11.
- Un canal que oscila entre fallar y recuperarse genera una alerta y un «recuperado» cada vez (sin supresión de oscilaciones).
- El primer fallo de configuración se reconoce por el texto saneado de `sync_runs.error_message` (solo se clasifica; nunca se copia).
- La salud de TCH se evalúa desde `etl_runs`; sus cargas dependen de que alguien suba el Excel.
- Las bajas atascadas no tienen pantalla todavía (MGT-15): el enlace apunta a la API de consulta.
- `scheduler.last_job_success_at` vive en memoria: tras reiniciar el backend vuelve a `null` hasta el primer job.
