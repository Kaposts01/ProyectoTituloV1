# SEC-01: inventario de datos personales y su tratamiento

> S6, 2026-11-10. Revisado contra el código de `master` (`248d515`, incluye el PR #10): modelos en `app/models/`,
> migraciones en `alembic/versions/`, servicios y rutas en `app/`, y el ETL de TCH (`scripts/etl_tch.py`). **No** se
> consultaron filas de ninguna base ni se leyó el `.env`. Este documento no contiene datos personales: solo nombres de
> tablas, columnas, permisos y archivos. Es la base del capítulo de privacidad de la memoria (Ley 19.628 y Ley 21.719,
> vigente desde el 2026-12-01).
>
> **Leyenda.** «Claro»: texto plano en PostgreSQL (no hay cifrado por columna en ningún modelo; la protección es la del
> servidor y la base). «Hash»: HMAC-SHA256 con pepper, irreversible sin el pepper. «Saneado»: pasó por
> `sanitize_payload` (`app/services/payload_sanitization.py`), que **solo quita credenciales de pago** (PAN, CVV, BIN,
> token, número de cuenta, firmas) y **no quita** nombre, correo, RUT ni teléfono. «No verificado»: deducido del código,
> sin mirar datos.

## 1. Dónde se guarda cada dato personal

### 1.1 Tablas de canal (staging por proveedor)

| Tabla.columna | Dato | Canal (origen) | Forma | Notas |
|---|---|---|---|---|
| `vp_clients.first_name`, `last_name`, `email`, `phone_number`, `social_id`, `gender_id`, `birth_date`, `private_note` | nombre, correo, teléfono, RUT, género, nacimiento, nota libre | VirtualPOS API (cuentas `virtualpos1`/`virtualpos2`) | claro | `app/models/vp.py` |
| `vp_clients.cards` | marca, tipo, emisor, últimos 4, vencimiento | VirtualPOS API | claro, sin PAN | `channel_store._card_summaries` solo conserva esos campos |
| `vp_subscriptions.client_social_id`, `vp_payments.client_social_id` | RUT | VirtualPOS API | claro | |
| `vp_subscriptions.card_type`, `card_brand`, `card_last4` | tarjeta enmascarada | VirtualPOS API | claro; CHECK de exactamente 4 dígitos | VP-PAR-07 |
| `vp_*.raw_payload` | JSON del proveedor | VirtualPOS API | saneado (conserva datos personales) | |
| `vp_report_payments.card_last4`, `vp_report_subscriptions.card_*` | tarjeta enmascarada | reporte PAT del portal VP | claro; CHECK de 4 dígitos | el parser nunca lee nombre, correo, RUT, teléfono ni dirección |
| `vp_report_*.seller_code_hash` | código de vendedor con forma de RUT | reporte PAT | **hash** (pepper `VP_REPORT_HASH_PEPPER`; sin pepper no se guarda) | `app/models/vp_report.py` |
| `tk_customers.name`, `email`, `phone_number`, `government_id` | nombre, correo, teléfono, RUT | Toku API | claro | `app/models/toku_channel.py` |
| `tk_payments.government_id` | RUT | Toku API | claro | |
| `tk_*.raw_payload` | JSON del proveedor | Toku API | saneado | |
| `tk_report_{products,payment_methods,attempts,debts}.product_key_hash` | «ID Producto» (contiene el RUT) | reportes Toku | **hash** (pepper `TOKU_REPORT_HASH_PEPPER`) más el `sub_` resuelto (DEC-17) | sin pepper el importador se niega antes de abrir el archivo (`toku_report_import.py`) |
| `tk_report_customers` | solo estado del cliente | reportes Toku | sin datos personales | TK-PAR-07 |
| `tk_report_payment_methods.card_type`, `card_brand`, `issuer_bank` | tipo y marca de tarjeta | reportes Toku | claro | no son identificadores por sí solos |
| `p_clients.name`, `email`, `phone`, `rut` | nombre, correo, teléfono, RUT | Payku API | claro | `app/models/payku_channel.py` |
| `p_transactions.description` | texto libre del cobro | Payku API | claro | puede traer nombres (no verificado) |
| `p_*.raw_payload` | JSON del proveedor | Payku API | saneado | |
| `p_report_*` | sin datos personales | reportes del portal Payku | `row_key` = sha256 de voucher, orden, fecha y monto | `app/models/payku_report.py` |
| `tch_clientes.rut`, `nombre`, `apellido`, `fecha_nacimiento`, `profesion`, `tipo_persona`, `telefono`, `email`, `direccion`, `comuna`, `ciudad`, `region` | identidad, contacto y domicilio | Excel de TCH (`scripts/etl_tch.py`, `POST /api/v1/tch/import-report`) | claro | el canal con más datos por persona |
| `tch_suscripciones.cliente_rut`, `banco_nombre`, `tipo_cuenta` | RUT y banco | Excel TCH | claro | |
| **`tch_suscripciones.numero_cuenta`** | **número de cuenta bancaria** | Excel TCH (`etl_tch.py`, columna «número cuenta») | **claro** | ver riesgo R1 |
| `tch_suscripciones.captador`, `razon_baja` | nombre del captador, motivo libre | Excel TCH | claro | `titular_distinto` es solo un indicador: no se guarda el RUT ni el nombre del titular |
| `tch_*.raw_payload` | fila del Excel | Excel TCH | saneado | quita `numero_cuenta` solo si el encabezado normaliza exactamente a esa clave |

### 1.2 Tablas canónicas, Core y trazabilidad

| Tabla.columna | Dato | Origen | Forma | Notas |
|---|---|---|---|---|
| `clients.first_name`, `last_name`, `email`, `phone_number`, `social_id`, `gender_id`, `birth_date`, `private_note`, `cards` | identidad, contacto, tarjeta enmascarada | consolidación de los cuatro canales (`channel_consolidation.py`) | claro | copia derivada: se reescribe en cada consolidación |
| `clients.external_id` (`source='tch'`) | **RUT** (la llave del canal TCH es el RUT) | consolidación TCH | claro | también en `source_records.external_id` de TCH (`tch_source_records.py`) |
| `subscriptions.client_social_id` | RUT | consolidación | claro | |
| `clients`/`subscriptions`/`charges`/`payments`/`payment_methods.raw_payload` | JSON | consolidación | saneado | |
| `core_client_attributes.attribute_value` | RUT, correo, teléfono por canal | ETL Core | claro | base de la identidad centralizada (ADR-001) |
| `core_subscriptions.card_last4` | últimos 4 | ETL Core | claro; CHECK de 4 dígitos | |
| `client_match_candidates.match_signals`, `notes` | coincidencias (booleanos), nota libre | detector de duplicados | claro | `match_signals` no guarda valores, solo si coinciden |
| `source_records.payload`, `source_record_observations.payload_sanitized` | JSON del proveedor | sync de VP, Toku y Payku | saneado (conserva datos personales); `payload_hash` sha256 | las marcas internas (`sync_metrics`, `alert_state`, `removal_guard`, `core_etl`, `consolidation_mark`) no llevan datos personales |

### 1.3 Webhooks, escrituras, operación y usuarios

| Tabla.columna | Dato | Forma | Notas |
|---|---|---|---|
| `webhook_events.payload_masked` | aviso del proveedor | **enmascarado** (`webhook_intake.mask_pii`: claves de identidad, contacto, domicilio, tarjeta, IP y user agent; objetos de persona reducidos a su id; RUT, correo y teléfono también por expresión regular). Payku y VP sin firma guardan solo ids y estado (`minimal_payload`) | cola vigente desde la migración 0049 |
| `stg_vpos_webhook_events.payload`, `source_ip` | payload crudo, IP | **claro, sin enmascarar** | histórico: no se escribe desde la 0049, pero las filas previas siguen (riesgo R2) |
| `stg_toku_webhook_events.payload`, `source_ip` | payload crudo, IP | **claro** | ídem |
| `stg_payku_webhook_events.payload`, `raw_body`, `headers`, `source_ip` | payload crudo, cuerpo, cabeceras, IP | **claro** | ídem |
| `write_runs.request_payload`, `response_payload`, `error_message` | lo enviado al proveedor (puede llevar datos del socio al editar o crear) y auditoría de exportaciones (usuario, filtros, filas, si incluyó PII) | claro; errores con `safe_error_message` | no verificado si toda escritura omite contacto |
| comentarios de `billing_change_requests`, `subscription_cancellation_requests`, `subscription_manual_tasks` y sus `*_events.detail` | notas libres de operadores | claro | pueden contener datos si el operador los escribe |
| `users.username` | identificador del usuario del CRM | claro | no hay columna de correo; `password_hash` con argon2 (pwdlib) |
| `export_jobs.file_path` | ruta del CSV, que puede llevar PII | n/a | los filtros quedan en versión auditable (la búsqueda libre solo como largo) |

Las tablas de sincronización (`sync_cursors`, `sync_runs`, `etl_runs`) no guardan datos personales: solo fechas, páginas,
conteos y el tipo de error.

## 2. Quién lo ve (permisos y roles)

Control en FastAPI (`app/core/security.py`: `require_permissions`, `require_role`, `require_source_access`); catálogo
y roles en `app/services/rbac.py`.

| Rol | Ve datos personales en pantalla | Exporta datos personales |
|---|---|---|
| `admin` | sí (todos los permisos) | sí |
| `jefatura` | según los `.view` que tenga en la base | sí (`export.pii`, migración 0044) |
| `soporte` | **sí, en todos los canales**: recibe todos los permisos `.view` (`virtualpos.clients.view`, `toku.customers.view`, `payku.clients.view`, `tch.clientes.view`) | no (sin `export.pii`) |
| `ejecutivo` | **sí, en todos los canales** (todos los `.view`) | no; solo el CSV de mandatos TCH, que usa lista blanca sin RUT, contacto ni cuenta |
| `coordinador` | lo que defina la base (el código solo le garantiza lectura de bajas y tareas) | no |

- El Recuperador general muestra RUT y nombre solo con el permiso de ver clientes del canal (`recovery_pii.can_view_pii`).
- `core.identity.read/review/merge` da acceso a la identidad centralizada (atributos por canal).

## 3. Por dónde sale

| Salida | ¿Lleva datos personales? | Control |
|---|---|---|
| CSV general (`/export/{clientes,suscripciones,cobros,pagos}`) | RUT, nombre, correo, teléfono y dirección (TCH) **solo con `export.pii`**; sin el permiso esas columnas se seleccionan como NULL | auditoría en `write_runs`; en segundo plano, archivo en disco del servidor que caduca a las `EXPORT_JOB_TTL_HOURS` (24 h) y se borra cuando alguien vuelve a usar exportaciones (`purge_expired`) |
| CSV del Recuperador VirtualPOS (`recovery.py`, `_export`) | RUT, nombre, correo, teléfono | **lo decide `virtualpos.recovery.export`, no `export.pii`** (riesgo R4) |
| CSV de mandatos TCH (tareas manuales) | no (lista blanca) | `subscriptions.manual_tasks.confirm` |
| Correos de alertas (`alerts.py`, `billing_alerts.py`, `business_alerts.py`, `ops_alerts.py`) | **no**: solo canal, condición, contadores y horas; nunca `error_message`, ids de suscripción ni texto libre. Lo único personal son los destinatarios (`ALERT_EMAIL_TO`) | regla dura en la docstring de `alerts.py`; el cuerpo lo declara |
| Webhooks entrantes | se guardan enmascarados (sección 1.3) | firma por canal |
| Webhooks salientes | no existen (solo `return_url`/`callback_url` hacia VirtualPOS al crear una suscripción) | — |
| Logs de la aplicación | no se encontró ningún `logger.*` que imprima RUT, correo, nombre ni teléfono; los errores van como nombre de clase o mensaje saneado; `sync_metrics` solo lleva fases y conteos | el filtro de `app/core/log_redaction.py` solo oculta secretos de URL (`?k=` de Payku), **no** datos personales. Los `logger.exception` imprimen el traceback (no verificado que nunca arrastre valores) |
| Escrituras a proveedores | el socio que se crea o edita viaja al proveedor | bandera local explícita y guardas por canal |
| Archivos fuera de la base | reportes descargados de los portales (`*.xlsx`, `docs/Reportes_*/`, `reports/`) traen datos personales | ignorados en `.gitignore`; no deben subirse ni adjuntarse |

## 4. Retención

- **No hay retención automática de datos personales.** Lo único que se borra solo: los CSV caducados
  (`purge_expired`), las corridas vacías del barrido de cobros y claves antiguas de cobros TCH.
- Sugerida en documentación, sin job: `webhook_events` 30 días (`done`/`ignored`) y 90 días (`failed`), y vaciar las
  `stg_*` (`docs/data/webhooks.md`); historia de estados 24 meses (`docs/data/status-history.md`).
- Bajas: una suscripción que el proveedor deja de devolver se marca (`removed_at`), no se borra; el cliente sigue.
- Respaldos: BCK-01a (PR #8, sin integrar al 2026-11-10) agrega el respaldo local con copia en disco externo y nube
  cifrada (d156). Un respaldo es una copia completa con todos los datos personales: su retención y su cifrado son parte
  de esta política.
- La política de retención, rectificación y eliminación sigue pendiente (`docs/architecture/security.md`, ADR-001).

## 5. `crm_sandbox` con datos reales (QA-04)

El informe de QA del 2026-11-05 encontró en `crm_sandbox` un cliente de VirtualPOS creado contra el sandbox del
proveedor con datos de una persona real y luego sincronizado. **Decisión del usuario (d163): mantener `crm_sandbox`
como está y aplicar la regla 14 del runbook** (`docs/operations/sandbox-testing-and-decisions.md`):

- `crm_sandbox` se trata como base con datos personales: sin capturas, CSV ni extractos de Socios, Cobros o
  Suscripciones en informes, fichas o PR, salvo filas sintéticas reconocibles (`DEMO-`, `TEST`, «AmigoPrueba»);
- las exportaciones de prueba se descargan al scratchpad y se borran al terminar;
- nadie anonimiza ni borra esas filas por su cuenta (decisión «siempre con el usuario»);
- al crear datos en los sandboxes de los proveedores solo se usan nombres, RUT y correos sintéticos (`example.test`).

Consecuencia: el sandbox **no** sirve como fuente de capturas para la memoria ni para la demo sin SEC-02.

## 6. Necesidad de SEC-02 (modo demo)

La demo en vivo será sobre la producción local (d161), que tiene datos reales de todos los canales. Hoy **no existe**
ningún modo de enmascaramiento de presentación (no hay `demo_mode` en `app/` ni en `frontend/src`): lo único que
oculta datos es el permiso (`export.pii`, `can_view_pii`), y el rol de solo lectura (`soporte`, `ejecutivo`) igual ve
RUT, nombre, correo y teléfono. SEC-02 debe:

- enmascarar en la respuesta de la API (no solo en el front) RUT, nombres, correos, teléfonos, dirección, número de
  cuenta y nota libre en listados, fichas, búsqueda, Recuperador e identidad;
- forzar las columnas personales a NULL en todas las exportaciones (incluida la del Recuperador, que no pasa por
  `export.pii`);
- cubrir `raw_payload` si alguna vista lo muestra (vista de staging);
- tener pruebas que verifiquen que, encendido, ninguna pantalla ni CSV muestre el dato en claro.

## 7. Riesgos

| ID | Riesgo | Severidad | Mitigación propuesta |
|---|---|---|---|
| R1 | `tch_suscripciones.numero_cuenta` guarda el número de cuenta bancaria en claro | Alta | confirmar si la operación lo necesita; si no, dejar de cargarlo o guardar solo los últimos dígitos (requiere migración, fuera del congelamiento solo con decisión) |
| R2 | `stg_*_webhook_events` conservan payloads crudos, cabeceras e IP sin enmascarar y sin purga | Media | vaciar o purgar las `stg_*` (ya sugerido en `docs/data/webhooks.md`); decisión del usuario porque borra datos |
| R3 | `raw_payload` y `source_records.payload` de todos los canales conservan datos personales del proveedor (el saneador solo quita credenciales) | Media | aceptado por diseño (auditoría y reproceso); documentar en la memoria y considerarlo en la retención |
| R4 | El CSV del Recuperador VirtualPOS incluye datos personales con `virtualpos.recovery.export`, sin pasar por `export.pii` | Media | alinear con `export.pii` (cambio pequeño de código, con prueba) |
| R5 | `soporte` y `ejecutivo` ven datos personales de todos los canales por heredar todos los `.view` | Media | revisar el mínimo necesario con la jefatura; SEC-02 para la demo |
| R6 | Sin retención automática ni política aprobada (Ley 21.719 desde el 2026-12-01) | Media | definir la política y un job de purga (fuera de S6) |
| R7 | `crm_sandbox` con datos reales (QA-04) | Media | regla 14 vigente por decisión d163 |
| R8 | CSV de exportación en segundo plano quedan en disco hasta que alguien vuelve a usar exportaciones | Baja | purga periódica por el scheduler |
| R9 | Notas libres de operadores y `p_transactions.description` pueden contener datos personales | Baja | indicarlo en la interfaz; SEC-02 las enmascara |
| R10 | Tracebacks de `logger.exception` podrían arrastrar valores | Baja (no verificado) | revisar en MET-02 o al definir la retención de logs |
