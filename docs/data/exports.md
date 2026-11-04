# Exportación de datos a CSV (EXP-01 a EXP-05)

Contrato de la exportación desde cada vista (Clientes, Suscripciones, Cobros, Pagos). Decisiones del usuario: D22 (solo `admin` y `jefatura` exportan con datos personales), D23 (CSV que abre en Excel, respeta filtros y búsqueda, más la opción «exportar todo»).

## Resumen técnico

- Servicio común: `app/services/exporter.py` (CSV en streaming, UTF-8 con BOM, anti-inyección de fórmulas, auditoría).
- Consultas: `app/services/export_queries.py` (SQL con cursor del lado del servidor: `stream_results` + `yield_per=2000`; nunca se arma el archivo en memoria. Los cobros de TCH son 1,47 M de filas).
- Rutas: `app/api/v1/routes/export.py`, montadas en `/api/v1/export`.
- El recuperador (`/api/v1/recovery/*/export`) sigue con su propio contrato y permiso (`virtualpos.recovery.export`); solo comparte `csv_safe` y el cuerpo de auditoría.

## Endpoints (contrato para el frontend, EXP-04)

Todos son `GET`, requieren sesión (cookie) y no necesitan CSRF. La descarga se hace navegando o con `fetch` + `blob`.

| Endpoint | Descripción |
|---|---|
| `GET /api/v1/export/{entity}` | Descarga el CSV. `entity` ∈ `clientes`, `suscripciones`, `cobros`, `pagos`. |
| `GET /api/v1/export/{entity}/count` | Devuelve `{"entity", "rows", "canales", "include_pii"}` con los mismos parámetros (salvo `all`, `offset`, `limit`). Sirve para mostrar «N filas» en el botón antes de descargar. |

Parámetros (query string, todos opcionales):

| Parámetro | Valores | Notas |
|---|---|---|
| `canal` | `virtualpos`, `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch` | Sin `canal`: todos los canales a los que el usuario tiene permiso de vista. Un `canal` sin permiso responde 403. |
| `query` | texto (máx. 200) | Búsqueda del listado. |
| `filter_field` | `all` (por defecto) y por entidad: clientes `rut`, `name`, `last_name`, `platform`, `email`, `phone`; suscripciones `id`, `rut`, `client`, `platform`, `status`; cobros `id`, `subscription_id`, `status`; pagos `id`, `charge_id`, `status` | Otro valor responde 422. |
| `status` | texto | Estado exacto (sin distinguir mayúsculas). |
| `date_from`, `date_to` | `YYYY-MM-DD` | Sobre `fecha_alta` (clientes), `fecha_inicio` (suscripciones), `fecha_cobro` (cobros) o `fecha_pago` (pagos). Inclusivos. |
| `amount_min`, `amount_max` | número ≥ 0 | No aplica a clientes (422). |
| `all` | `true`/`false` (por defecto `false`) | `true` ignora la paginación (no los filtros). |
| `offset`, `limit` | enteros (`limit` 1 a 1000, por defecto 50) | Solo sin `all`: exporta esa «página» de la misma consulta. |

Respuesta de la descarga:

- `Content-Type: text/csv; charset=utf-8`.
- Header de descarga: `Content-Disposition: attachment; filename="<entidad>[-<canal>]-AAAAMMDD.csv"` (fecha de Chile). Ejemplo: `cobros-tch-20261029.csv`.
- `Cache-Control: no-store`. El cuerpo empieza con el BOM UTF-8.
- Errores: 401 sin sesión, 403 sin permiso de vista del canal (o sin ningún canal permitido), 422 parámetros inválidos. Se validan antes de empezar el stream, así que un error nunca llega como CSV truncado.
- Si la conexión se corta a mitad del stream, el archivo queda incompleto y la auditoría registra `status = aborted`.

Para saber si el CSV llevará columnas personales, el frontend puede leer `include_pii` de `/count` o la lista de permisos del usuario (`export.pii`). No existe parámetro para pedir PII: lo decide el permiso.

## Permisos

- Exportar sin datos personales: el permiso de VISTA del recurso, por canal (el mismo del listado). Se filtra en el servidor; no existe forma de exportar un canal sin su permiso.

  | Entidad | VirtualPOS | Toku | Payku | TCH |
  |---|---|---|---|---|
  | clientes | `virtualpos.clients.view` | `toku.customers.view` | `payku.clients.view` | `tch.clientes.view` |
  | suscripciones | `virtualpos.subscriptions.view` | `toku.subscriptions.view` | `payku.subscriptions.view` | `tch.suscripciones.view` |
  | cobros | `virtualpos.charges.view` | `toku.invoices.view` | `payku.transactions.view` (ciclos `p_cycles`, d124 b) | `tch.transacciones.view` |
  | pagos | `virtualpos.payments.view` | `toku.transactions.view` | `payku.transactions.view` | no aplica (en TCH cada transacción es un cobro) |

- Vistas unificadas (d124, opción c; migración `20261102_0064`): `general.subscriptions.view` equivale al permiso de vista de suscripciones de los cuatro canales, y `general.charges.view` al de cobros y pagos de todos los canales (en la vista y en la exportación). Sin el permiso general, cada canal sigue exigiendo el suyo (compatibilidad mientras la migración no esté aplicada y para roles parciales). La migración los otorga solo a los roles que ya tenían todos los permisos de canal equivalentes.
- Incluir columnas con datos personales: además `export.pii`. La migración `20261029_0044` lo asigna solo a `admin` y `jefatura`. `soporte`, `ejecutivo` y `coordinador` exportan sin esas columnas. **La migración la aplica el usuario** (ningún agente corre Alembic); hasta entonces nadie, salvo quien reciba el permiso a mano, exporta con datos personales (`seed_permissions` ya se lo da a `admin` al sembrar).

## Columnas por entidad

Las columnas marcadas «PII» solo aparecen con `export.pii`; sin él ni siquiera se seleccionan de la base (viajan como NULL y se omiten del encabezado).

- **clientes**: `canal`, `id_externo`, `estado`, `fecha_alta`, PII: `rut`, `nombre`, `correo`, `telefono`, `direccion` (TCH: dirección, comuna y ciudad juntas). `id_externo` en TCH es el identificador interno, nunca el RUT.
- **suscripciones**: `canal`, `id_suscripcion`, `estado`, `estado_secundario` (misma regla de la vista: inactiva, Nunca Cobrado, incobrable, cobrable), `fecha_inicio`, `fecha_termino`, `monto`, `moneda`, `ultimo_cobro`, PII: `rut_cliente`, `nombre_cliente`.
- **cobros**: `canal`, `id_cobro`, `id_suscripcion`, `estado`, `fecha_cobro`, `periodo` (solo TCH), `monto`, `moneda`, `motivo_rechazo` (solo TCH), PII: `rut_cliente`, `nombre_cliente`.
- **pagos**: `canal`, `id_pago`, `id_cobro`, `estado`, `fecha_pago`, `monto`, `moneda`, PII: `rut_cliente`, `nombre_cliente`.

`canal` toma los valores `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch`. Fechas y montos se exportan tal como están guardados (texto ISO y monto sin formato), para que Excel no los reinterprete.

## Diferencias deliberadas con los listados (supuestos)

- **Clientes** se exporta una fila por registro de cliente por canal, no agrupado por RUT como la vista general (agrupar entre canales no se puede hacer con cursor sin cargar todo). Solo entran clientes con RUT, igual que la vista. La búsqueda se evalúa por registro.
- **Cobros y pagos** buscan por id, id de suscripción/cobro y estado (los campos que ofrecen los listados por canal); no buscan por RUT.
- El orden de las filas es estable (canal y luego identificador), no el orden de pantalla.
- La sección «cobros» de TCH exporta las transacciones del Excel (todas, aceptadas y rechazadas).
- El cruce con el cliente (columnas PII de cobros y pagos) se hace por la suscripción o por el id de cliente del registro; si el canal no trae esa relación, las columnas quedan vacías.

## Seguridad

- Anti-inyección de fórmulas: toda celda de texto que empiece por `=`, `+`, `-`, `@`, tabulación o retorno de carro lleva un apóstrofo delante (`csv_safe`).
- Sin datos personales por defecto; los permisos por canal se aplican en el servidor.
- Los mensajes de error y la auditoría no incluyen contenido.

## Auditoría

Cada descarga escribe una fila en `write_runs` al terminar (o cortarse) el stream: `source = "export"`, `resource_type = <entidad>`, `external_id = "export/<entidad>"`, `operation = "export_csv"`, `status = completed | aborted`, `requested_by_user_id`, `started_at`/`finished_at` y `request_payload` con `user_id`, `username`, `endpoint`, `rows` (filas realmente entregadas), `pii_included` y `filters` (`canales`, `all`, `offset`/`limit`, estado, fechas, montos y búsqueda). **Nunca el contenido.** El texto de búsqueda solo se guarda cuando el campo no puede ser un dato personal (`id`, `status`, `platform`, `subscription_id`, `charge_id`); en los demás se guarda solo su largo (`query_len`), porque podría ser un RUT, un nombre o un correo.

## Pruebas

`tests/test_exporter.py` (servicio), `tests/test_export_endpoints.py` (endpoints, PII, permisos por canal, filtros, paginación, auditoría), `tests/test_export_streaming.py` (cursor del lado del servidor, reparto de paginación, 50.000 filas sintéticas con tope de tiempo y memoria) y `tests/test_export_permissions.py` (permiso `export.pii`, migración 0044 y permisos fantasma).

## Botón «Exportar» en el frontend (EXP-04)

Componente `frontend/src/features/shared/ExportButton.tsx` (mapeo en `exportMapping.ts`, mensajes de error y umbral en `exportSupport.ts`). Una sola interacción en todas las listas: menú con «Esta vista (con filtros)» (envía `offset`/`limit` de la página mostrada, máximo 1.000) y «Todo el listado (con los filtros activos, sin paginación)» (`all=true`). Antes de descargar consulta `/count` y muestra «N filas» y si el archivo llevará datos personales (`include_pii`); si «todo el listado» supera 200.000 filas muestra un aviso dentro de la página y el botón pasa a «Descargar de todos modos» (nunca `window.confirm`). La descarga usa `fetch` con cookie de sesión (`getBlob` en `api.ts`) y guarda el archivo con el nombre del `Content-Disposition`.

Errores: 403 «Tu rol no puede exportar este recurso.»; 401 sesión expirada; 409 conflicto temporal; 422 filtros no válidos; 5xx fallo del servidor. La interfaz no se bloquea (solo el propio botón mientras descarga). Accesible: `aria-haspopup`/`aria-expanded`, `role="menu"`, flechas y Escape, foco a la confirmación y de vuelta al botón, `role="status"`/`alert` para los avisos.

| Vista | Entidad | Canal | Filtros que se envían |
|---|---|---|---|
| Clientes consolidados | `clientes` | todos los permitidos | `filter_field` + `query` |
| Suscripciones consolidadas | `suscripciones` | todos los permitidos | `filter_field` + `query` |
| VirtualPOS clientes / suscripciones / cargos / transacciones | `clientes` / `suscripciones` / `cobros` / `pagos` | `virtualpos`, `virtualpos1` o `virtualpos2` según el selector «VP 1 / VP 2» | filtros por columna: texto -> `filter_field`+`query`; estado -> `status`; montos -> `amount_min`/`amount_max`; fechas -> `date_from`/`date_to` |
| Toku clientes / suscripciones / deudas / transacciones | `clientes` / `suscripciones` / `cobros` / `pagos` | `toku` | campo + búsqueda; el estado va como `status` |
| Payku clientes / suscripciones / transacciones | `clientes` / `suscripciones` / `pagos` | `payku` | ídem |
| TCH clientes / suscripciones / transacciones | `clientes` / `suscripciones` / `cobros` | `tch` | nombre -> `filter_field=name`+`query`; estado -> `status`; período `AAAA-MM` -> `date_from`/`date_to` del mes completo |

Sin botón: planes de VirtualPOS y Payku y métodos de pago de Toku (no existen en el contrato), fichas de detalle y paneles de resumen. El orden de la pantalla no se envía (el backend ordena por canal e identificador).

Filtros que el contrato no puede expresar (búsqueda por RUT en cobros y pagos, campos de monto o fecha como texto, estado secundario, una segunda búsqueda de texto de VirtualPOS, montos en clientes) no se envían: el botón los lista en un aviso antes de confirmar y el archivo sale sin ellos. El botón se oculta solo si el usuario no tiene el permiso de vista de la tabla «Permisos» para ese canal y entidad. El permiso `export.pii` solo sirve de pista (texto del menú); el backend decide.

## Exportación en segundo plano (EXP-06, d114 opción b)

Para listados completos grandes. `GET /export/{entidad}/count` agrega `background` (true si las filas superan `EXPORT_BACKGROUND_THRESHOLD_ROWS`, 50.000 por defecto) y `background_threshold`. Con `background=true`, el botón «Exportar» (solo en «Todo el listado») ofrece «Generar en segundo plano» y:

1. `POST /export/{entidad}/jobs` (mismos parámetros que la exportación, `X-CSRF-Token`; 202) crea el job con los mismos permisos de vista y la misma regla de `export.pii`. Máximo `EXPORT_JOB_MAX_ACTIVE_PER_USER` (2) jobs en cola o corriendo por usuario: `429 too_many_export_jobs`.
2. `GET /export/jobs/{id}` devuelve el estado (`queued`, `running`, `completed`, `failed`, `expired`), filas estimadas y escritas, caducidad y `download_url`. `GET /export/jobs` lista los 20 últimos del usuario. Un job ajeno responde 404.
3. `GET /export/jobs/{id}/download` entrega el CSV (`409 export_job_not_ready` si no terminó; `410 export_job_expired` si caducó).

Reglas: reutiliza las consultas (`export_queries.iter_rows`) y el CSV (`exporter.csv_stream`) de la exportación directa; el archivo se escribe en `EXPORT_JOB_DIR` (vacío = carpeta temporal del sistema) y caduca a las `EXPORT_JOB_TTL_HOURS` (24) horas: se borra el archivo y el job queda `expired` (la limpieza corre al crear, listar, consultar o descargar). La tabla `export_jobs` (migración `20261102_0065`) guarda solo los filtros auditables (`ExportFilters.audit()`: la búsqueda de un campo que puede ser dato personal se reduce a su largo); los logs llevan id, entidad y contadores. La generación y cada descarga quedan en `write_runs` (`export/{entidad}/jobs` y `export/{entidad}/jobs/download`). Los jobs corren en un pool de hilos del proceso: si el servidor se reinicia, un job en curso no se reanuda: a las 2 horas sin terminar queda `failed` (`stale:not_finished`) y libera el cupo.
