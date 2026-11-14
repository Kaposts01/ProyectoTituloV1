# Capítulo 5. Modelo de datos e integración por canal

> **Estado:** borrador S6 (DOC-14), revisable. Sin datos personales: las cifras son agregados ya publicados en la
> documentación del proyecto. Lo dudoso se marca [verificar].
> **Fuentes:** `docs/data/` (en especial `centralized-model.md`, `sync-idempotency.md`, `status-history.md`,
> `toku-reports-load.md`, `webhooks.md`), `docs/integrations/` (fichas y revisiones por proveedor), ADR-001,
> `app/models/`, `app/services/` y `app/integrations/` en `master` (commit `248d515`).

## 5.1 Propósito del capítulo

El capítulo describe cómo se representa la información de socios, suscripciones, cobros y pagos, y cómo cada canal de
recaudación se proyecta sobre esa representación. Primero se presenta el modelo conceptual y sus principios; luego, el
modelo físico por capas; después, la integración de cada canal con sus particularidades; y al final, los mecanismos
transversales de idempotencia, trazabilidad e historial de cambios.

## 5.2 Modelo conceptual

El dominio se describe con un conjunto pequeño de conceptos independientes del proveedor
(`docs/data/centralized-model.md`):

| Concepto | Significado en el dominio |
| --- | --- |
| Cliente (socio o donante) | Persona que aporta de forma recurrente o puntual |
| Suscripción | Compromiso recurrente de un cliente con un plan o monto |
| Cobro programado o cuota | Obligación o intento planificado de cobro en un período |
| Pago o transacción | Resultado informado por el proveedor: pagado, rechazado, pendiente |
| Plan | Oferta recurrente (monto fijo o variable, frecuencia) |
| Plataforma | Canal o cuenta de procedencia del dato |
| Liquidación | Agrupación financiera del proveedor hacia la organización (contrato común pendiente) |

La distinción entre **cobro** y **pago** es central: un cobro puede tener varios intentos (pagos), de los cuales uno
puede ser exitoso y otros rechazados. No todos los proveedores exponen ambos conceptos (sección 5.5), por lo que el
modelo admite cobros sin pagos y pagos sin cobro asociado.

Tres principios gobiernan el modelo:

1. **El identificador externo se conserva siempre.** Toda fila centralizada lleva su `source` y su `external_id`, con
   unicidad sobre ese par.
2. **El RUT no es una clave transversal** (ADR-001). Es un atributo personal y una señal de comparación; dos registros
   con el mismo RUT en canales distintos son candidatos a la misma persona, no la misma persona.
3. **El dato del proveedor y el dato central se mantienen separados.** El proveedor nunca escribe en las tablas
   centrales; estas se derivan por procesos idempotentes que pueden repetirse.

## 5.3 Modelo físico por capas

### 5.3.1 Capa Raw

`source_records` (`app/models/source_record.py`) guarda, por cada recurso leído, el contenido saneado en JSONB, el
contexto de la sincronización y las fechas de primera y última observación. Su restricción
`uq_source_record (source, resource_type, external_id)` es la base de la idempotencia de la ingesta.
`source_record_observations` (`app/models/core.py`) guarda un hash por cada versión distinta del contenido, lo que
permite saber cuándo cambió un recurso sin almacenar copias completas.

Antes de persistir, `app/services/payload_sanitization.py` elimina las credenciales de pago conocidas (número de
tarjeta, PAN, CVV o CVC, códigos de seguridad). La misma tabla se usa además, con valores de `source` reservados, para
marcas operativas sin datos personales (métricas por corrida, marcas de consolidación y de ETL Core).

### 5.3.2 Capa de canal

Cada proveedor tiene tablas tipadas propias, con su vocabulario original:

| Canal | Tablas de API | Tablas de reportes |
| --- | --- | --- |
| VirtualPOS (dos cuentas) | `vp_clients`, `vp_plans`, `vp_subscriptions`, `vp_charges`, `vp_payments` | `vp_report_files`, `vp_report_payments`, `vp_report_subscriptions` |
| Toku | `tk_customers`, `tk_subscriptions`, `tk_invoices`, `tk_transactions`, `tk_payments`, `tk_payment_methods` | `tk_report_*` (archivos, productos, medios de pago, intentos, deudas, inscripciones, clientes, pagos, liquidaciones, códigos de respuesta) |
| Payku | `p_clients`, `p_plans`, `p_subscriptions`, `p_transactions`, `p_cycles` | `p_report_files`, `p_report_transactions`, `p_report_settlements` |
| TCH | — (sin API) | `tch_clientes`, `tch_suscripciones`, `tch_transacciones`, `tch_recaudacion_mensual`, catálogos (`tch_bancos`, `tch_tipos_mandato`, `tch_origenes`, `tch_centros_costo`, `tch_rechazos_motivo`) y `tch_file_loads` |

Las tablas de reportes se mantienen **separadas** de las de API por decisión explícita (DEC-19): la sincronización por
API sobrescribe sus tablas en cada corrida y mezclaría orígenes con distinta frescura.

### 5.3.3 Capa centralizada

Como se explicó en el capítulo 4, conviven dos modelos centralizados:

- **Modelo operativo** (`app/models/crm.py`): `clients`, `plans`, `subscriptions`, `charges`, `payments`,
  `payment_methods`, todos con unicidad `(source, external_id)`. Lo alimenta la consolidación
  (`app/services/channel_consolidation.py`) mediante `INSERT ... ON CONFLICT DO UPDATE`.
- **Modelo Core** (`app/models/core.py`):
  - `core_clients`: solo un identificador interno y marcas de tiempo. No guarda datos personales.
  - `external_identities`: vínculo de cada identidad de proveedor con su cliente Core, con el motivo del vínculo.
  - `core_client_attributes`: atributos (RUT, correo) por fuente, usados para detectar candidatos.
  - `client_match_candidates`: pares de clientes candidatos a ser la misma persona, con nivel de evidencia, para
    revisión manual.
  - `core_subscriptions`: estado, último estado de pago, monto, moneda, fechas de inicio y término, motivo de rechazo
    de la suscripción y últimos cuatro dígitos de la tarjeta con su procedencia (API o reporte), restringidos por
    `CHECK` a cuatro dígitos.
  - `core_charges`: período de referencia, fecha de vencimiento, monto, estado de origen y el último rechazo (código,
    motivo, fecha y pago asociado).
  - `core_payments`: estado de origen, fecha, monto, y código y motivo de rechazo.
  - `core_subscription_signals`: señales derivadas de reportes (sección 5.5.2).
  - `data_catalog_mappings`: catálogo de correspondencias campo de origen → campo Core, como documentación ejecutable.

### 5.3.4 Tablas operativas y de auditoría

| Propósito | Tablas |
| --- | --- |
| Corridas de sincronización y ETL | `sync_runs`, `etl_runs`, `sync_cursors` |
| Escrituras a proveedores | `write_runs` |
| Webhooks | `webhook_events` (cola con `dedupe_key` única) y tablas históricas `stg_*_webhook_events` |
| Historial de cambios | `status_change_events` (solo inserción), `rejection_reason_catalog`, `payment_rejection_details` |
| Operaciones gestionadas | `billing_change_requests` y eventos, `vp_managed_charges`, `subscription_cancellation_requests` y eventos, `subscription_manual_tasks` y eventos, `charge_recoveries` |
| Identidad y permisos | `users`, `roles`, `permissions` |

## 5.4 Del dato crudo al modelo central

El flujo por registro tiene tres transformaciones, cada una idempotente:

```text
respuesta de API ──sanear──> source_records ──extraer──> tabla de canal ──consolidar / ETL Core──> modelo central
```

1. **Saneamiento y almacenamiento crudo** (`app/services/read_only_provider_sync.py`,
   `app/services/source_record_store.py`): escritura en lote que solo reescribe una fila si su contenido cambió.
2. **Extracción a la tabla de canal** (`app/services/channel_store.py`): extractores por proveedor que convierten el
   contenido en columnas tipadas.
3. **Consolidación y ETL Core**: la consolidación lleva cada canal al modelo operativo; los ETL `core_*_etl` llevan
   cada canal al modelo Core en un orden fijo (atributos del cliente → suscripciones → cobros → pagos → rechazos).
   Las sentencias usan una guarda `IS DISTINCT FROM` (`app/services/upsert_guard.py`) para que un dato idéntico no
   genere una escritura ni una marca de actualización falsa.

## 5.5 Integración por canal

Cada proveedor tiene un contrato distinto. La tabla resume las diferencias que más influyeron en el modelo; las
subsecciones detallan cada canal.

| Aspecto | VirtualPOS | Toku | Payku | TCH |
| --- | --- | --- | --- | --- |
| Acceso | API v3 | API REST | API REST (V1 y V3) | Planilla Excel |
| Autenticación | JWT HS256 estático firmado con la llave secreta (`app/integrations/virtualpos/auth.py`) | Llave en encabezado `x-api-key` | Tokens más firma HMAC por solicitud (`app/integrations/payku/auth.py`) | Sesión de administrador en el CRM |
| Cuentas | Dos (`virtualpos1`, `virtualpos2`) | Una | Una | Una |
| Cobro como recurso | Sí (`charges`) | Sí (`invoices`) | No: ciclos dentro de la suscripción (V3) | Cuota por período |
| Ambiente de pruebas | Sandbox propio | Mismo host que producción, con llaves de prueba (DEC-26) | Sandbox pendiente de activación (DEC-10) | Excel sintético |
| Webhooks | Sí, sin firma salvo payouts [verificar, TER-01] | Sí, con secreto | Sí, con token en la URL | No |

### 5.5.1 VirtualPOS

VirtualPOS es el canal con más suscripciones y opera con **dos cuentas** de comercio, que el sistema trata como dos
plataformas (`virtualpos1` y `virtualpos2`). El conjunto de plataformas válidas está acotado en
`app/services/channel_store.py` (`_VP_PLATFORMS`) y la consolidación omite con aviso cualquier valor desconocido, lo que
cerró una brecha de idempotencia (SYNC-GAP-01).

Las tablas de canal usan unicidad `(platform, external_id)` y un índice parcial que impide dos suscripciones activas
del mismo cliente al mismo plan. Dos particularidades del contrato marcaron el modelo:

- **Monto vigente.** En los planes de monto fijo (más de 6000 suscripciones) el monto no se puede editar, y el
  proveedor genera por adelantado cobros programados hasta varios años en el futuro. Por eso el monto de una
  suscripción en el CRM es el **monto vigente**: el del último cobro pagado o en proceso con fecha hasta hoy, en hora de
  Chile; en su defecto, el de la suscripción y luego el del plan (`app/services/vp_current_amount.py`, decisión
  registrada en `docs/tasks.md` §1.5; su registro como ADR está pendiente, DEC-13).
- **Vínculo pago → suscripción.** El pago trae el RUT del cliente, no la suscripción. El ETL Core
  (`app/services/core_vp_etl.py`) solo vincula un pago cuando ese RUT corresponde a exactamente una suscripción en la
  misma plataforma; con cero o más de una, el pago queda sin suscripción en lugar de adivinar.

Las diferencias observadas entre la documentación y el sandbox (por ejemplo, que `internal_code` no es idempotente o
que ciertos filtros de fecha se ignoran) se registran con identificadores `VP-Cxx` en `docs/integrations/virtualpos/`
y se incorporaron a los pedidos de TER-01.

### 5.5.2 Toku

Toku expone clientes, suscripciones, facturas (`invoices`, equivalentes a cobros), transacciones, pagos y medios de
pago. En el ETL Core (`app/services/core_toku_etl.py`) las facturas se materializan como cobros y los pagos como pagos;
las transacciones fallidas alimentan el último rechazo de cada cobro y, solo con una bandera, se materializan como
pagos fallidos (RJ-15).

La API no basta para responder preguntas de negocio como «¿esta suscripción está realmente activa?». Por eso se
incorporaron los **reportes** que el usuario descarga del backoffice y carga por la interfaz (DEC-20,
`app/services/toku_report_import.py`). Con ellos `app/services/toku_report_signals.py` calcula, en
`core_subscription_signals`, las señales de actividad efectiva, racha de cuotas impagas, tarjeta bloqueada y tarjeta
vencida, con reglas acordadas con el usuario:

- **Suscripción activa** = no eliminada y con medio de pago cobrable (DEC-18).
- **Racha** medida por cuotas impagas «en firme», no por intentos (DEC-16).
- **Precedencia**: el reporte manda para estado y medio de pago cuando es más reciente que la última lectura por API;
  la API manda para montos y facturas (DEC-23).
- El campo del reporte que contiene el RUT se guarda solo como hash más el identificador de suscripción resuelto
  (DEC-17).

### 5.5.3 Payku

Payku no tiene un recurso de cobro. La aproximación adoptada (PK-06) toma los ciclos de cobro del arreglo `paid[]` de
la API V3 de suscripciones, guardados en `p_cycles`, como cobros del modelo Core; los pagos se vinculan a su ciclo
**solo** a través de `paid[].transactions[]`, sin inferencias (`app/services/core_payku_etl.py`). Si no hay datos V3,
las transacciones se proyectan directamente como pagos.

Los estados de Payku se normalizan a una taxonomía común (`active`, `suspended`, `cancelled`, `pending_enrollment`;
`app/services/payku_status.py`, PK-PAR-07). Las transacciones rechazadas llegan con monto cero y sin código de rechazo;
como respaldo, el motivo se deriva del último estado de pago de la suscripción (PK-PAR-06).

La principal limitación del canal es el **historial**: los filtros de fecha de transacciones devuelven cero
resultados incluso en rangos con datos, por lo que la cobertura histórica no está certificada (PK-01, PK-05). Un
importador de reportes del proveedor (`app/services/payku_report_import.py`) complementa comisiones, neto y
liquidaciones. Las preguntas abiertas al proveedor se listan en TER-01.

### 5.5.4 TCH

TCH representa mandatos de débito bancario y no tiene API: el administrador carga una planilla Excel desde la interfaz
(`POST /api/v1/tch/import-report`), el archivo se procesa en segundo plano y se elimina al terminar
(`docs/integrations/tch.md`). Cada carga se registra en `tch_file_loads` por el hash SHA-256 de su contenido, sin
guardar datos del reporte, lo que evita cargar dos veces el mismo archivo.

Cada cuota de `tch_transacciones` se identifica por la clave ficha, período y cuota (decisión D13): un rechazo y un pago
posterior de la misma cuota son intentos del mismo cobro, no dos cobros (DEC-04). En el modelo Core, cada cuota es un
cobro con su período real y su último intento es un pago (`app/services/core_tch_etl.py`, TCH-PAR-12).

TCH introduce una tensión con ADR-001: `tch_clientes` tiene unicidad por RUT, porque el reporte no trae otro
identificador del cliente. Esto se acepta como identificador **del proveedor** (nota de 2026-10-25 en ADR-001), no como
clave transversal.

## 5.6 Mecanismos transversales

### 5.6.1 Idempotencia

| Nivel | Mecanismo | Evidencia |
| --- | --- | --- |
| Raw | Unicidad `(source, resource_type, external_id)` y reescritura solo si el contenido cambió | `source_record_store.py` |
| Canal | Unicidad por identificador externo (y plataforma en VirtualPOS; clave de cuota en TCH) | `docs/data/sync-idempotency.md` |
| Central | Unicidad `(source, external_id)` con `ON CONFLICT DO UPDATE` y guarda `IS DISTINCT FROM` | `channel_consolidation.py`, `upsert_guard.py` |
| Webhooks | `dedupe_key` única: id del evento en Toku; hash de canal, tipo, recurso, estado y ventana de 5 minutos en los demás | `webhook_intake.py` |
| Candidatos de identidad | Par ordenado único `(client_id_a, client_id_b)` | `client_match_detector.py` |

Las pruebas de idempotencia y de forma de los contenidos se concentran en la suite de `tests/` (por ejemplo,
`tests/test_sync_gap04_payload_shapes.py` y `tests/test_etl_tch.py`).

### 5.6.2 Trazabilidad

Las filas centralizadas de VirtualPOS, Toku y Payku se vinculan a su registro crudo mediante `source_record_id`. En TCH
el vínculo sigue vacío porque su carga no pasa por `source_records`; existe un script de relleno
(`scripts/maintenance/backfill_source_record_ids.py`) cuya ejecución está pendiente [verificar] (SYNC-GAP-03).

### 5.6.3 Historial de cambios

Las tablas centrales guardan solo el último estado. Para saber qué cambió, la consolidación compara cada valor nuevo con
el anterior y registra un evento en `status_change_events` (`app/services/status_events.py`, decisión D7: en el código
y no en un *trigger*). Los eventos son de alta, cambio de estado, cambio de monto, cambio de motivo de rechazo y
eliminación, y no guardan datos personales. Esta tabla alimenta el resumen diario de cambios y los avisos en tiempo
casi real descritos en el capítulo 4.

### 5.6.4 Motivos de rechazo

Cada canal informa los rechazos de forma distinta (códigos numéricos, textos libres o nada). La función
`format_rejection_reason` (`app/services/rejection_format.py`) aplica una regla común: si el código está en el catálogo
del canal, manda el texto del catálogo; si no, el texto crudo del proveedor; si no, el código; y si no hay nada,
«No informado por <canal>». Nunca se inventan códigos ni textos, y los valores crudos se conservan en las tablas Core.

## 5.7 Limitaciones del modelo a la fecha

- La identidad transversal está implementada a nivel de modelo y detección, pero el flujo de fusión reversible está
  incompleto (CORE-04).
- La convivencia de dos modelos centralizados obliga a verificar la paridad de indicadores entre ambos.
- La cobertura histórica de Payku y el historial de cargos de algunas suscripciones de VirtualPOS son incompletos por
  limitaciones de los proveedores (`docs/architecture/integrations.md`).
- La taxonomía común de estados y montos entre canales es parcial.
- Las respuestas pendientes de los proveedores (TER-01) pueden obligar a ajustar claves de cobro (Payku) o filtros de
  lectura (VirtualPOS y Toku); lo no respondido al corte se documentará como trabajo futuro en el capítulo 11.
