# Estado de producción y cómo retomar (al 2026-11-14)

Documento operativo para retomar el trabajo. La fuente de verdad del plan sigue siendo `docs/tasks.md`; esta página
resume cómo está corriendo producción hoy y qué trampas conocidas hay. Sin secretos: solo nombres de variables.

## Servicios

| Servicio | Puerto | Cómo corre | Base |
|---|---|---|---|
| Backend de producción | 8000 | Ventana «CRM prod backend 8000»: `.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload` desde el checkout principal (`master`) | `crm` |
| Frontend de producción | 5173 | Vite (proxy `/api` al 8000) | — |
| Backend sandbox | 8001 | Ventana «CRM sandbox backend 8001»: `scripts\run_sandbox_backend.ps1` (`APP_ENV=sandbox`) | `crm_sandbox` |
| Frontend sandbox | 5174 | Vite (proxy `/api` al 8001) | — |
| PostgreSQL | 5433 | `crm_projectotitulo-postgres-1` (`compose.yaml`), publicado **solo** en `127.0.0.1` y `[::1]` (d221) | `crm`, `crm_sandbox`, `crm_test` |

`PRODUCTION_APP_URL` es `http://localhost:5173`; no hay URL pública.

## Estado tras OPS-11 (2026-11-14)

- Base `crm` en la revisión `20261104_0071`. Respaldos: `crm_20261114_1250.dump` (antes de la ventana) y
  `crm_20261114_1501.dump` (después del paso 8), en `C:\Users\Usuario\Downloads\CRM_backups`.
- `AUTH_JWT_SECRET` rotado el 14/11. Variables nuevas en el `.env`: `TOKU_REPORT_HASH_PEPPER` y
  `VP_REPORT_HASH_PEPPER` (respaldadas por el usuario en su gestor; cambiarlas invalida los hashes guardados),
  `ALERT_*` con `ALERTS_ENABLED=true`, `SYNC_CORE_ETL_ENABLED=true` (d215) y las `GOOGLE_OAUTH_*` (CRM-16B; el código
  aún no las lee y `GOOGLE_OAUTH_ENABLED=false`).
- Hecho: pasos 0 a 3, 5 a 12 y d220 (dependencias). OPS-11 cerrada. Detalle y conteos en `ops-11-guion.md`,
  «Resultado de la ventana». «Datos incompletos» quedó en 441 / 728 (las 728 son 421 de TCH, que esperan d223, y 307
  de Payku en estado `delete` sin fecha de baja en la fuente).
- **No hecho: paso 4 (recarga completa de TCH) y d211.** El ensayo no cuadró por la clave de deduplicación de
  `scripts/etl_tch.py` (historial y CARGOS con cuotas distintas). Ficha d223 (aprobada «a»: conciliar solo los meses
  con CARGOS). TCH queda con datos hasta 2026-09; octubre 2026 entra con esa recarga.

## Ramas y trabajo abierto

| Rama / ficha | Qué es | Condición |
|---|---|---|
| `feat/login-seguro` (d219) | Login endurecido y rate limit (CRM-16A/16D) | Ventana aparte: aplicar la migración `20261114_0080` **antes** del merge |
| `feat/payku-prueba-consumo` (d213 b) | Prueba de 1 CLP en Payku productivo | Confirmación del usuario en el chat antes de cada escritura |
| CRM-16B (d218 b) | Login con Google, solo `@techo.org` | Sin empezar; rama prevista `feat/google-oauth-16b` |
| d221 (resto) | `/docs` apagado en producción y cabeceras de seguridad | Pendiente (el Postgres local ya está hecho) |
| d217 | `.wslconfig` con 8 GB para Docker | El usuario corre `Downloads\limitar_memoria_docker.ps1`; reinicia Docker y baja también vpbase |
| Frontend | vite 8.2.4 y source-map-js 1.2.2 (solo desarrollo) | PR pendiente |
| Estados de cobro | Unificar los nombres de estado entre canales en el filtro de cobros | Propuesta de mapeo en la Bandeja |

## Trampas conocidas

- **`--reload` y merges:** un `git pull` en el checkout principal recarga el 8000 en caliente. Con migraciones,
  detener el 8000 **antes** del pull. Al detenerlo, matar el árbol (`taskkill /PID <ventana> /T /F`) y comprobar con
  `/health` y `Get-NetTCPConnection -LocalPort 8000`: un proceso hijo huérfano puede seguir atendiendo.
- **El `.env` no se recarga con `--reload`:** cada cambio exige reiniciar el 8000.
- **`localhost` y IPv6:** `DATABASE_URL` usa `localhost` y psycopg prueba `::1` primero; si Postgres no publica
  `[::1]`, la conexión queda colgada sin timeout (el backend no arranca y no da error).
- **Scripts fuera de la app:** `app/models/__init__.py` registra todos los modelos al importarse (PR #42); si vuelve
  un `NoReferencedTableError`, revisar eso antes de tocar el script.
- **PowerShell:** usar `$env:X = $null` para quitar variables (`Remove-Item Env:` está bloqueado en las sesiones de
  Claude) y `| Out-File -Encoding utf8` para logs (`*>` escribe UTF-16).
- **pytest local:** pasar `--basetemp` a una carpeta propia; `AppData\Local\Temp\pytest-of-Usuario` da Acceso denegado.
- **Reportes de Toku:** 9 de los 16 archivos de `CRM_reportes\Toku` son de tipos no soportados y el script los
  informa como error; es esperado. El cargador aplica «el más nuevo gana» por fila.
