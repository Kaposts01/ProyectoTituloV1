# Métricas de operación (MET-02)

Agregados de uso y operación de una ventana (por defecto dos semanas) calculados **solo con tablas que ya existen**, sin
migración nueva (d159). Script: `scripts/diagnostics/operation_metrics.py`. Pruebas: `tests/test_operation_metrics.py`
(base `crm_test`, datos sintéticos).

## Cómo se ejecuta

```powershell
# Desde la raíz del repo. --database es obligatorio.
$env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/operation_metrics.py --database crm_test
$env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/operation_metrics.py --database crm_test --days 14 --until 2026-11-21 --format markdown
```

- `--database NOMBRE` (obligatorio): la URL sale de `DATABASE_URL` cambiando **solo** el nombre de la base; nunca se
  imprime.
- Guarda (misma regla que `parity_check.py`, vía `readonly_guard.py`): si el nombre no termina en `_test` (`crm`,
  `crm_sandbox`) el script aborta con código 2 **antes de conectarse**, salvo `--read-only` explícito.
- Siempre corre en una transacción `READ ONLY` y con un filtro que solo deja pasar `SELECT`/`WITH`.
- `--days N` (por defecto 14) y `--until AAAA-MM-DD` (último día incluido, hora de Chile; por defecto, ahora). La
  ventana es `[fin - N días, fin)` en UTC.
- `--format table | markdown | json`.
- **Correrlo contra `crm` (producción local) lo decide el usuario.** No se ha ejecutado contra `crm`.

## Métricas

| Sección | Tabla | Qué mide | Criterio de la ventana |
|---|---|---|---|
| `sync_canales` | `sync_runs` (canales: sin `billing_*` ni `cancellation_*`) | Corridas por fuente y estado, duración media y máxima (s), registros procesados | `started_at` |
| `sync_frescura` | `sync_runs` | Horas desde la última corrida `completed` de cada fuente hasta el fin de la ventana; corridas `failed` en la ventana | último `completed` antes del fin |
| `jobs` | `sync_runs` (`billing_*`, `cancellation_*`) | Corridas de los jobs de facturación y bajas por fuente y estado | `started_at` |
| `etl_runs` | `etl_runs` | Corridas del ETL global por estado, duración media, corridas con algún canal fallido, registros | `started_at` |
| `escrituras` | `write_runs` | Escrituras a proveedores por fuente, operación y estado; duración media | `started_at` |
| `exportaciones` | `export_jobs` | Exportaciones por entidad, estado y si incluyen datos personales; filas escritas | `created_at` |
| `cambios_cobro` | `billing_change_requests` | Solicitudes de cambio de cobro creadas, por tipo, plataforma y estado **actual** | `created_at` |
| `cambios_cobro_eventos` | `billing_change_request_events` | Eventos de esas solicitudes (creada, aprobada, aplicada, fallida…) | `created_at` del evento |
| `bajas` | `subscription_cancellation_requests` | Bajas tramitadas por canal, código de motivo y estado **actual** | `created_at` |
| `bajas_eventos` | `subscription_cancellation_request_events` | Eventos de las bajas (created, completed, failed…) | `created_at` del evento |
| `alertas` | `source_records` (`source='alert_state'`) | Por tipo de condición (`sync_fail`, `core_lag`, …): condiciones cuyo último aviso cae en la ventana, recuperadas en la ventana y activas al momento de la consulta | `last_sent_at` / `last_resolved_at` del estado |

### Consulta tipo

Todas las secciones son agregaciones `GROUP BY` sobre columnas de categoría. Ejemplo (`sync_canales`):

```sql
SELECT source, status, count(*),
       avg(extract(epoch FROM finished_at - started_at)),
       max(extract(epoch FROM finished_at - started_at)),
       coalesce(sum(records_processed), 0)
FROM sync_runs
WHERE source NOT LIKE 'billing\_%' AND source NOT LIKE 'cancellation\_%'
  AND started_at >= :inicio AND started_at < :fin
GROUP BY source, status;
```

## Datos personales

La salida solo trae nombres de fuente, canal, estado, tipo, operación y motivo (códigos fijos), conteos y duraciones.
Nunca ids externos, RUT, correos, montos por socio, `error_message`, comentarios, payloads ni ids de usuario. De las
alertas solo se muestra el tipo de condición (la parte antes de `:`). Lo verifica
`test_output_has_no_personal_data_and_declares_limitations`.

## Limitación declarada (lo que no se puede medir sin migración)

1. **Inicios de sesión, sesiones y vistas por pantalla**: el CRM no guarda auditoría de acceso (no hay tabla de logins
   ni de vistas). No se puede medir uso por usuario ni frecuencia de uso sin agregar esa tabla.
2. **Correos de alerta enviados**: el estado de alertas guarda solo el último aviso por condición; los recordatorios
   intermedios (cada 6 h) no quedan. El conteo de `alertas` es una **cota inferior**.
3. **Tiempos de respuesta y errores HTTP de la API**: no se persisten.
4. **Estado histórico de una solicitud**: `cambios_cobro` y `bajas` muestran el estado actual de las creadas en la
   ventana; el recorrido está en las secciones `*_eventos`.

La salida del script repite estas limitaciones al final.
