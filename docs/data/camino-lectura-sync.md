# Camino de lectura de una sync manual (sandbox, CRM-14D)

> Medido el 2026-11-13 en `crm_sandbox` con la rama `fix/toku-sandbox-sync` levantada en el puerto 8013 con
> `APP_ENV=sandbox` (solo lecturas hacia los proveedores; ninguna escritura). Solo conteos: sin datos personales.
> Canales habilitados en sandbox: VirtualPOS (cuenta `virtualpos1`) y Toku. Payku no está habilitado en sandbox y TCH
> se carga por archivo Excel (no se recarga aquí); sus conteos no cambian y no se listan por etapa.

## 1. Cómo se disparó

1. `POST /api/v1/etl/full-sync` con `{"providers": ["virtualpos", "toku"]}` (usuario temporal de
   `scripts/sandbox/ephemeral_user.py`, borrado al terminar). En sandbox el job `sync_all_channels` del scheduler no
   está registrado (`POST /scheduler/jobs/sync_all_channels/run` responde 404 `job_not_found`), así que la sync manual
   usa este endpoint.
2. `POST /api/v1/etl/core/virtualpos` y luego `POST /api/v1/etl/core/toku`: el ETL Core no corre dentro de la sync
   porque `SYNC_CORE_ETL_ENABLED` está apagada (valor por defecto).

| Corrida | Tabla | Id | Estado | Registros |
|---|---|---|---|---|
| Sync global VirtualPOS + Toku | `etl_runs` | `be47a637-beb5-45c8-ac3f-a032094ee772` | `completed` | 9 061 (`records_upserted`) |
| Sync VirtualPOS 1 | `sync_runs` | `12ec0c16-bbb0-46c7-bf3a-5e04b1017e84` | `completed` (aviso: 5 suscripciones omitidas por duplicado activo) | 9 procesados |
| Sync Toku | `sync_runs` | `bdf0e7cb-0978-4f89-b389-c68fa4ac751a` | `completed` | 9 procesados |
| ETL Core VirtualPOS | `etl_runs` | `4740dbca-7b55-4048-ac30-b033b1cb0156` | `completed` | 22 |
| ETL Core Toku | `etl_runs` | `a69831de-acb8-4f92-a421-24c599250da5` | `completed` | 9 |

`sync_runs.etl_run_id` queda vacío en esta ruta: solo el orquestador `sync_all_channels` fija la corrida global
(`current_run_id`). La correlación se hace por hora (las dos `sync_runs` caen dentro de la ventana de `be47a637`).

## 2. Diagrama del camino

```text
 Proveedor (API, solo GET)
   VirtualPOS: /clients /plans /subscriptions /payments  (+ cargos derivados de suscripciones)
   Toku:       /customers /subscriptions /invoices /transactions /payment-methods
               (/organization/payments NO se pide en sandbox: CRM-14B)
        |
        v
 [1] fetch            app/integrations/{virtualpos,toku}/client.py
        |             -> resource_stats en sync_runs (records/pages/inserted/updated/unchanged por recurso)
        v
 [2] staging          source_records (source, resource_type, external_id)  payload saneado, upsert idempotente
        |
        v
 [3] normalización    channel_store.store_{vp,toku}_resources (extractores por recurso)
 [4] tablas canal     vp_clients vp_plans vp_subscriptions vp_charges vp_payments
        |             tk_customers tk_subscriptions tk_invoices tk_transactions tk_payment_methods (tk_payments)
        v
 [5] consolidación    channel_consolidation.consolidate_to_centralized
        |             -> clients plans subscriptions charges payments payment_methods external_identities
        |             -> status_change_events (cambios de estado detectados)
        v
 [6] ETL Core         core_vp_etl / core_toku_etl (manual en sandbox)
        |             -> core_clients core_subscriptions core_charges core_payments core_client_attributes
        v
 [7] indicadores      GET /api/v1/dashboard/general (dashboard_general.py): lee las centralizadas
                      subscriptions/charges/payments (+ tablas TCH); core_* alimenta recuperación, rechazos
                      y exportaciones (recovery_*.py, export_queries.py, charge_rejection_display.py)
```

## 3. Conteos por etapa y canal

**Fetch** (lo leído del proveedor en esta corrida, de `sync_runs.resource_stats`; nuevos/actualizados/sin cambio):

| Canal | Recurso | Leídos | Páginas | Nuevos | Actualizados | Sin cambio |
|---|---|---|---|---|---|---|
| VirtualPOS 1 | client | 30 | 1 | 0 | 0 | 30 |
| VirtualPOS 1 | plan | 8 | 1 | 0 | 0 | 8 |
| VirtualPOS 1 | subscription | 18 | 1 | 0 | 3 | 15 |
| VirtualPOS 1 | payment | 41 | 1 | 3 | 0 | 38 |
| VirtualPOS 1 | charge (derivado, sin llamada propia) | 1 469 | 0 | 0 | 3 | 1 466 |
| Toku | customer | 34 | 1 | 0 | 0 | 34 |
| Toku | subscription | 37 | 1 | 0 | 0 | 37 |
| Toku | invoice | 51 | 1 | 9 | 0 | 42 |
| Toku | transaction | 0 | 1 | 0 | 0 | 0 |
| Toku | payment_method | 0 | 1 | 0 | 0 | 0 |
| Toku | payment | omitido (`not_available_in_sandbox`) | 0 | — | — | — |

**Etapas siguientes** (filas en `crm_sandbox` antes → después; Δ = filas nuevas):

| Etapa | Tabla | VirtualPOS 1 | Toku |
|---|---|---|---|
| [2] staging | `source_records` client/customer | 26 → 26 | 234 → 234 |
| [2] staging | `source_records` plan | 8 → 8 | — |
| [2] staging | `source_records` subscription | 18 → 18 | 257 → 257 |
| [2] staging | `source_records` payment | 38 → 41 (Δ3) | 2 947 → 2 947 |
| [2] staging | `source_records` charge / invoice | 1 469 → 1 469 | 3 288 → 3 297 (Δ9) |
| [2] staging | `source_records` transaction | — | 3 499 → 3 499 |
| [2] staging | `source_records` payment_method | — | 200 → 200 |
| [3-4] canal | `vp_clients` / `tk_customers` | 25 → 25 | 234 → 234 |
| [3-4] canal | `vp_plans` | 8 → 8 | — |
| [3-4] canal | `vp_subscriptions` / `tk_subscriptions` | 13 → 13 | 257 → 257 |
| [3-4] canal | `vp_charges` / `tk_invoices` | 1 469 → 1 469 | 3 288 → 3 297 (Δ9) |
| [3-4] canal | `vp_payments` / `tk_payments` | 38 → 41 (Δ3) | 2 947 → 2 947 |
| [3-4] canal | `tk_transactions` | — | 3 499 → 3 499 |
| [3-4] canal | `tk_payment_methods` | — | 200 → 200 |
| [5] consolidación | `clients` | 25 → 25 | 234 → 234 |
| [5] consolidación | `external_identities` | 25 → 25 | 234 → 234 |
| [5] consolidación | `plans` | 8 → 8 | — |
| [5] consolidación | `subscriptions` | 13 → 13 | 257 → 257 |
| [5] consolidación | `charges` | 1 469 → 1 469 | 3 288 → 3 297 (Δ9) |
| [5] consolidación | `payments` | 38 → 41 (Δ3) | 3 499 → 3 499 |
| [5] consolidación | `payment_methods` | — | 200 → 200 |
| [5] consolidación | `status_change_events` | 13 → 20 (Δ7) | 7 044 → 7 053 (Δ9) |
| [6] Core | `core_subscriptions` | 13 → 13 | 257 → 257 |
| [6] Core | `core_charges` | 1 469 → 1 469 | 3 288 → 3 297 (Δ9) |
| [6] Core | `core_payments` | 38 → 41 (Δ3) | 2 947 → 2 947 |
| [6] Core | `core_client_attributes` | 79 → 79 | 894 → 894 |
| [6] Core | `core_clients` (común a todos los canales) | 849 → 849 | (misma tabla) |

Sin cambios en Payku ni TCH (no se sincronizaron). `etl_runs` pasó de 2 a 5 filas y `sync_runs` de 8 a 10.

## 4. Lectura de los conteos

- **Idempotencia.** Lo ya conocido vuelve como `unchanged` y no crea filas: solo crecen las tablas con registros
  nuevos (3 pagos de VirtualPOS, 9 facturas de Toku), y el mismo Δ se propaga por staging, canal, consolidación y Core.
- **Toku: `payments` centralizadas = `tk_transactions`.** La consolidación de Toku arma `payments` desde las
  transacciones (3 499), no desde `tk_payments` (2 947); `core_payments` sí sale de `tk_payments`.
- **Toku sandbox ve otra organización.** Las llaves `TOKU_SANDBOX_*` leen 34 clientes, 37 suscripciones y 51 facturas,
  0 transacciones y 0 medios de pago (docs/tasks.md, hallazgos 2026-10-28). Las filas de Toku previas en `crm_sandbox`
  vienen de cargas anteriores y no se tocan; la detección de bajas por desaparición (`SYNC_REMOVAL_DETECTION_ENABLED`)
  está apagada, así que no se marcan bajas por las suscripciones que esta llave no ve.
- **Indicadores.** `GET /api/v1/dashboard/general` lee `subscriptions`, `charges` y `payments` centralizadas; los Δ de
  la etapa [5] son los que pueden mover el resumen. No se midió el resumen antes/después en esta corrida.
- **VirtualPOS: «5 suscripciones omitidas por duplicado activo».** Aviso conocido de la restricción
  `uq_vp_sub_active_plan_client`; no hace fallar la corrida.
