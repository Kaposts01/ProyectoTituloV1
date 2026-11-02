# Reportes PAT de VirtualPOS (VP-PAR-02 / RJ-04)

> Sprint 5A. Importador de los reportes `TransaccionesPAT-VirtualPOS-*.csv` y `SuscriptoresPAT-VirtualPOS-*.csv` del portal.
> Origen del diseño: `docs/planning/auditoria-2026-10-29/` (paridad CRM vs reportes, glosa de rechazo) y decisión **D6**
> (el histórico de glosas de VirtualPOS sale de estos reportes, con `capture_source = 'report_pat'`).
> Patrón seguido: importador de reportes de Toku (`toku_report_parser.py`, `toku_report_import.py`, TK-17/TK-18).

## 1. Diseño del modelo (por qué tablas propias)

Se evaluaron dos caminos para guardar lo que hoy solo vive en `raw_payload` o que no existe en el CRM:

| Opción | Efecto |
|---|---|
| A. Columnas nuevas en `vp_charges` / `vp_payments` / `vp_subscriptions` | Toca tablas grandes y calientes (`ALTER TABLE` sobre cientos de miles de filas en `crm`), las reescribe el sync nocturno (`upsert` que reemplaza la fila) y obliga a decidir qué fuente gana en cada columna. |
| **B. Tablas propias `vp_report_*` (elegida)** | Solo `CREATE TABLE` de tablas vacías: la migración no toca datos existentes y es reversible (`DROP TABLE`). El sync no las pisa. Cada fila conserva `source_generated_at` y el archivo que la cargó (trazabilidad y guarda de frescura). El ETL Core puede leerlas después sin cambiar `vp_*`. |

Se eligió B por ser la menos invasiva. Tablas (migración `20261029_0045`, modelo `app/models/vp_report.py`):

* `vp_report_files`: un archivo cargado. `file_sha256` **único** (el mismo archivo no se carga dos veces), `report_type`
  (`transacciones` | `suscriptores`), `filename` (solo el nombre), `rows_*`, rango de fechas (`window_start/end`), `generated_at`,
  `loaded_at`, `status` (`running` | `completed` | `failed`), `error_label` técnico y `uploaded_by_user_id`. **Sin contenido ni datos personales.**
* `vp_report_payments`: un cobro (clave `Id cargo`, `charge_external_id`, único). Guarda el `UUID transacción`
  (`payment_external_id`), código y glosa de rechazo, medio de pago por cobro (Débito/Crédito/Prepago), fecha de autorización,
  comisión, abono, fecha de abono, alias POS, hash del código de vendedor, origen de la suscripción y del cargo, y los últimos 4 dígitos.
* `vp_report_subscriptions`: una suscripción (clave `Id de suscripción`). Estado, fechas de alta y cancelación, plan, contadores de cargos,
  canal/origen, alias POS, hash del código de vendedor, tipo/marca/últimos 4 de la tarjeta y **motivo de rechazo de la suscripción**.

### Datos sensibles: decisiones

* **Nunca se leen** nombre, apellido, correo, RUT, teléfono, nacimiento, género ni dirección del cliente (el parser lee solo las columnas
  de la firma por posición).
* **Últimos 4 dígitos (`card_last4`)**: el proyecto ya los guarda en `vp_subscriptions.raw_payload.payment_method.last4CardDigit`, por eso se
  guardan. Un `CHECK` (`^[0-9]{4}$`) y la columna `VARCHAR(4)` impiden guardar más de 4 dígitos; el parser descarta cualquier valor que no
  sean exactamente 4 dígitos. Nunca PAN completo ni CVV.
* **Código de vendedor**: en el portal tiene forma de RUT (identificador de una persona). Se guarda solo como `seller_code_hash`
  (HMAC-SHA256 con el pepper `VP_REPORT_HASH_PEPPER`), nunca en claro. Sin pepper el campo queda NULL (y se avisa); el resto de la carga sigue.
  Nota: `vp_subscriptions.raw_payload.seller_id` ya contiene ese valor en claro (hallazgo previo al importador, no cambia con esta tarea).
* No hay `raw_payload` en ninguna de las tres tablas.

## 2. Columnas de los reportes y mapeo

Encabezados medidos con una lectura que solo imprime la fila de encabezados (2026-10-29). Los 74 archivos locales de
`CRM_reportes\VirtualPOS` (40 `TransaccionesPAT`, 34 `SuscriptoresPAT`) tienen exactamente el mismo encabezado por tipo, son
UTF-8 con BOM y delimitador coma. Hay **columnas con nombre parecido** (`Id suscripción` vs `ID suscripción interno`) y el `Id suscripción`
trae un **tabulador final** (el parser lo limpia). Las fechas son `dd/mm/aaaa` (cobro) o `dd/mm/aaaa hh:mm` (autorización, abono, alta)
en hora de Chile.

### 2.1 `TransaccionesPAT-VirtualPOS-*.csv` (33 columnas) -> `vp_report_payments`

| Columna del reporte | Destino | Nota |
|---|---|---|
| `Id cargo` | `charge_external_id` (único) | clave; = `vp_charges.external_id` |
| `UUID transacción` | `payment_external_id` | = `vp_payments.external_id`; 1 a 1 con el cobro; vacío en cancelados |
| `Id suscripción` | `subscription_external_id` | sin el tabulador final |
| `Estado del cargo` | `charge_status` | pagado / rechazado / cancelado / procesando |
| `Fecha programada de cargo` | `scheduled_date` | |
| `Número de cargo`, `Total de cargos programados` | `charge_number`, `charges_total` | «Cargo 3 de 12» |
| `Monto de cargo`, `Moneda de cargo` | `amount`, `currency` | |
| `Código` y `Glosa de autorización/error/rechazo` | `response_code`, `response_text` | **solo si el cobro está `rechazado`** (en un pagado la columna trae el código de autorización) |
| `Medio de pago` | `payment_medium` | Débito / Crédito / Prepago (por cobro) |
| `Final número tarjeta` | `card_last4` | solo si son exactamente 4 dígitos |
| `Fecha de autorización` | `authorized_at` | |
| `Total comisión (imp. incl.)`, `Total abono`, `Fecha de abono` | `processing_fee`, `payout_amount`, `payout_date` | |
| `Alias POS` | `pos_alias` | |
| `Código de vendedor` | `seller_code_hash` | HMAC (forma de RUT); nunca en claro |
| `Origen de la suscripción`, `Origen del cargo` | `subscription_origin`, `charge_origin` | |
| Nombre, apellido, email y RUT del cliente | **no se leen** | datos personales |
| `Plan suscrito`, `Estado de suscripción`, `Costo de despacho`, `Id plan`, `Id cargo comercio`, `Fecha de suscripción`, `ID suscripción interno`, `Cód. de nómina` | no se guardan | ya están en `vp_*` o vienen vacías |

### 2.2 `SuscriptoresPAT-VirtualPOS-*.csv` (40 columnas) -> `vp_report_subscriptions`

| Columna del reporte | Destino |
|---|---|
| `Id de suscripción` | `subscription_external_id` (único) |
| `Estado de suscripción` | `status` (ACTIVA, CANCELADA, SUSCRIPCION_FALLIDA, SUSCRIBIENDO) |
| `Fecha de suscripción`, `Fecha de cancelación` | `subscribed_at`, `canceled_at` |
| `Id de plan` | `plan_external_id` |
| `Total de cargos programados / autorizados / rechazados / pendientes / en proceso / cancelados` | `charges_total`, `charges_authorized`, `charges_rejected`, `charges_pending`, `charges_processing`, `charges_canceled` (del corte del reporte) |
| `Canal/Origen`, `Alias POS` | `channel_origin`, `pos_alias` |
| `Código de vendedor` | `seller_code_hash` (HMAC) |
| `Tipo tarjeta`, `Marca`, `Últimos 4 dígitos pan` | `card_type` (TD/TC/TP), `card_brand`, `card_last4` |
| `Motivo de rechazo` | `rejection_reason` (suscripción fallida; texto del procesador, con RUT/correos/números largos redactados) |
| Nombre, apellido, email, RUT, teléfono, nacimiento, género, dirección, comuna, región, `Num serie POS`, `Plan suscrito`, `Fecha/Número/Monto/Estado próximo cargo`, `Moneda`, despacho, `ID suscripción interno` | no se leen ni se guardan |

## 3. Cómo se importa (reglas)

* **Tipo por firma de columnas**, no por nombre. Tolera encabezado desplazado (hasta 10 líneas), delimitador `,` `;` o tabulador, UTF-8 con/sin BOM,
  cp1252 y mojibake, y columnas duplicadas (gana la primera por posición). Un archivo ajeno o con columnas faltantes falla con los **nombres** de
  columnas, nunca con valores.
* **Fecha del reporte** (`generated_at`): el número de 10 dígitos del nombre (`...-1792546479.csv` es un epoch). Conviene **no renombrar** los archivos; si
  no se puede leer se usa «ahora» y el resumen avisa `generated_at_fallback_now`.
* **Idempotencia y frescura:** el `sha256` del archivo es único (mismo contenido = `409`/«YA CARGADO», aunque cambie el nombre). Las filas se
  actualizan por clave con `INSERT ... ON CONFLICT DO UPDATE` y cada columna solo cambia si el archivo es igual o más nuevo que el dato guardado, así
  el resultado no depende del orden. Una transacción por archivo; si falla, rollback completo y `vp_report_files.status = 'failed'` con una etiqueta técnica.
* **Plataforma (virtualpos1/virtualpos2):** los PAT no la traen. Se deduce de `vp_charges` (`Id cargo`), `vp_payments` (`UUID`) y `vp_subscriptions`
  (`Id suscripción`; en suscripciones también por sus cobros). Todas las señales coinciden -> `resolved`; discrepan -> `ambiguous`; ninguna -> `unresolved`.
  **Las filas ambiguas o sin resolver no escriben glosa ni vínculo** (no se fuerza nada). `reconcile` las reevalúa cuando el sync trae el dato.
* **Glosa (D6, RJ-04):** por cada cobro `rechazado` con plataforma resuelta se escribe `payment_rejection_details` con `capture_source = 'report_pat'`
  (`source` = plataforma, `code`/`reason` del reporte, `acquirer_code` si el código es `-2xxx`, `payment_external_id` = UUID, `rejected_at` = fecha programada
  a las 00:00 de Chile). Si la API (RJ-06) ya guardó una glosa real de ese cobro, **la API manda** y no se duplica; si la API dejó solo un marcador
  (`code = ''`), la glosa del reporte lo reemplaza. Las glosas nuevas entran a `rejection_reason_catalog` y emiten `reason_changed` (`status_events`), como RJ-06.
  Ojo: el texto del reporte («Excede límite de reintentos de rechazo») difiere del catálogo local para `-11`; el catálogo registra ambas redacciones hasta resolver RJ-03.
* **Vínculo pago -> cobro:** `UUID transacción` -> `Id cargo` (1 a 1) con `UPDATE` explícito solo donde está NULL: `vp_payments.charge_external_id` y
  `core_payments.charge_id`. Un UUID asociado a más de un cobro no se vincula. Desde VP-PAR-06 el sync nocturno ya no reescribe
  `vp_payments.charge_external_id` a NULL, y el ETL Core repite este cruce en cada corrida (pagados y rechazados), así que los `core_payments`
  creados después de la carga también se vinculan.

## 4. Qué cubre y qué no

* **Cubre** los cobros programados de 2025-02-24 a 2026-10-26 y las suscripciones dadas de alta entre 2025-02 y 2026-10 (cortes de los reportes locales): 83.009 filas
  de cobros y 8.894 de suscripciones sin contar solapes entre archivos (86.541 `Id cargo` únicos según la auditoría); ~23.8 mil rechazos con código y glosa.
* **No cubre** el histórico **anterior a 2025-02** (no existe reporte ni la API devuelve esos cobros), ni lo posterior al corte de cada archivo (hay que exportar y
  cargar reportes nuevos; las glosas de cobros nuevos las captura RJ-06 por API). Las columnas que el portal exporta vacías (despacho, próximo cargo, nómina) no aportan.
* No cambia KPIs ni dashboards: solo agrega tablas y rellena `payment_rejection_details` y los vínculos; los consumidores existentes no leen `vp_report_*`.
* Hechos: VP-PAR-03/05 (motivo con código y `-2122`; los otros `-2xxx` no tienen glosa documentada), VP-PAR-06 (vínculo) y VP-PAR-09
  (motivo y últimos 4 de suscripción, solo en lectura). Pendientes relacionados: VP-PAR-07 (promover estos campos a `core_*`), VP-PAR-12 (2 cobros con plataforma discordante entre el Sheet y el CRM aparecerán como `ambiguous`).

## 5. Cómo cargar

**Por la interfaz/API** (una por archivo; solo `admin`): `POST /api/v1/imports/virtualpos-reports`, multipart con el campo `report` (`.csv`, máx. 100 MB) y cabecera
`X-CSRF-Token`. Respuestas: `200` resumen (filas nuevas/actualizadas/omitidas/obsoletas, plataformas, glosas, vínculos); `409 already_loaded` o `load_in_progress`;
`413`; `422 invalid_format`; `500 import_failed` (con etiqueta técnica). Cada intento queda en `write_runs` (`source = virtualpos`, `operation = import_report`) con tipo,
nombre, sha256 y contadores, sin contenido. No hay pantalla todavía (frontend).

**Por lotes con el script** (recomendado para las ~74 cargas históricas):

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir "C:\Users\Usuario\Downloads\CRM_reportes\VirtualPOS"            # dry-run (solo lectura)
.venv\Scripts\python.exe scripts\maintenance\import_vp_reports.py --dir "C:\Users\Usuario\Downloads\CRM_reportes\VirtualPOS" --apply    # carga
```

Requisitos para `--apply` en `crm` (lo ejecuta el usuario): migraciones `20261029_0045` y `20261029_0046` aplicadas, respaldo previo, y opcionalmente
`VP_REPORT_HASH_PEPPER` en el `.env` (sin él se carga igual pero sin `seller_code_hash`; cambiarlo después invalida la correlación de los hashes ya guardados).
Si aparece el mismo reporte en `Downloads` y en `CRM_reportes\VirtualPOS`, el segundo se omite por sha256.

## 6. Efecto sobre `crm` al ejecutarlo (estimación sobre datos sintéticos; no se ha tocado `crm`)

* **Migraciones 0045/0046:** solo `CREATE TABLE` (3 tablas vacías) y un permiso asignado a `admin`. No tocan filas existentes; `downgrade` borra las tablas y el permiso.
* **Qué se llena:** `vp_report_files` (~74 filas), `vp_report_payments` (~86 mil), `vp_report_subscriptions` (~9 mil), `payment_rejection_details` (+~23.8 mil filas `report_pat`,
  menos las que la API ya capturó), `rejection_reason_catalog` y eventos `reason_changed` (decenas), `vp_payments.charge_external_id` (~72.8 mil donde hoy es NULL) y
  `core_payments.charge_id` (donde el cobro existe en `core_charges`). El código y la glosa llegan a `core_payments.rejection_*` y `core_charges.latest_rejection_*` en la
  **próxima corrida del ETL Core de VirtualPOS** (o al ejecutarla a mano).
* **Cuánto tarda:** con 81.000 cobros sintéticos, ~50 s la carga + ~1 s la reconciliación (≈1.600 filas/s); 9.000 suscripciones, ~5 s. El lote completo debería tardar de 2 a 5 minutos
  en `crm` (más filas en `vp_*`, mismo orden de magnitud). La prueba de volumen es opt-in: `VP_PERF_TEST=1 pytest tests/test_vp_report_import.py -k performance`.
* **Verificación sugerida después (conteos, sin datos personales):**
  `SELECT platform_status, count(*) FROM vp_report_payments GROUP BY 1;` (lo esperado: casi todo `resolved`);
  `SELECT capture_source, count(*) FROM payment_rejection_details WHERE source LIKE 'virtualpos%' GROUP BY 1;`;
  `SELECT count(*) FROM vp_payments WHERE charge_external_id IS NOT NULL;`.
