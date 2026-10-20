# Diagrama de Componentes — SynkmetriX

**Última actualización:** 2026-10-20
**Ítem cubierto:** 5 (diagrama de componentes)

---

## Diagrama principal

```mermaid
graph TB
    subgraph BROWSER["Navegador (React SPA)"]
        UI_DASHBOARD[Dashboard & KPIs]
        UI_CHANNELS[Exploradores por canal]
        UI_CORE[Vista consolidada Core]
        UI_ADMIN[Administración de usuarios]
        UI_VPOS[Recuperador VirtualPOS]
    end

    subgraph FASTAPI["FastAPI (uvicorn :8000)"]
        subgraph API_LAYER["Capa API"]
            ROUTER_AUTH[/api/v1/auth]
            ROUTER_SYNC[/api/v1/etl]
            ROUTER_CORE[/api/v1/core]
            ROUTER_VPOS[/api/v1/virtualpos]
            ROUTER_TOKU[/api/v1/toku]
            ROUTER_PAYKU[/api/v1/payku]
            ROUTER_TCH[/api/v1/tch]
            ROUTER_WEBHOOKS[/api/v1/webhooks]
            ROUTER_ADMIN[/api/v1/admin]
        end

        subgraph SERVICES["Servicios"]
            SVC_AUTH[auth_service\nJWT + Argon2]
            SVC_CACHE[cache_service\nTTL in-memory]
            SVC_MATCH[client_match_detector]
            SVC_VPOS_WRITE[virtualpos_write_service]
            SVC_TOKU_WRITE[toku_write_service]
        end

        subgraph CONNECTORS["Connectors (ingesta)"]
            CONN_VPOS[virtualpos_client\nhttpx + retry]
            CONN_TOKU[toku_client\nhttpx + retry]
            CONN_PAYKU[payku_client\nhttpx + retry]
        end

        subgraph ETL["ETL Core (Layer 3)"]
            ETL_VPOS[etl_virtualpos_core]
            ETL_TOKU[etl_toku_core]
            ETL_PAYKU[etl_payku_core]
            ETL_TCH[etl_tch_core]
        end

        subgraph WEBHOOKS_RECV["Receptores de Webhook"]
            WH_TOKU[webhooks_toku\nHMAC-SHA256]
            WH_VPOS[webhooks_virtualpos\nHMAC payout]
            WH_PAYKU[webhooks_payku\ntoken query]
        end

        SCHEDULER[APScheduler\nSync programada]
    end

    subgraph POSTGRES["PostgreSQL 17 (:5433)"]
        subgraph STG["Staging / Raw"]
            SOURCE_RECORDS[(source_records)]
            STG_VPOS[(vp_subscriptions\nvp_charges\nvp_transactions)]
            STG_TOKU[(t_subscriptions\nt_transactions)]
            STG_PAYKU[(p_subscriptions\np_transactions)]
            STG_TCH[(tch_dues\ntch_memberships)]
            STG_WEBHOOKS[(stg_toku_webhook_events\nstg_vpos_webhook_events\nstg_payku_webhook_events)]
        end

        subgraph CORE_DB["Core (Layer 3)"]
            CORE_CLIENTS[(core_clients\ncore_client_attributes)]
            CORE_SUBS[(core_subscriptions)]
            CORE_CHARGES[(core_charges)]
            CORE_PAYMENTS[(core_payments)]
            CORE_MATCH[(client_match_candidates)]
        end

        subgraph OPS_DB["Operacional"]
            SYNC_RUNS[(sync_runs)]
            ETL_RUNS[(etl_runs)]
            WRITE_RUNS[(write_runs)]
            USERS[(users\nroles\nuser_roles)]
        end
    end

    subgraph PROVIDERS["Proveedores externos"]
        P_VPOS[VirtualPOS API\nhttps]
        P_TOKU[Toku API\nhttps]
        P_PAYKU[Payku API\nhttps]
        P_TCH[Reportes Excel\n.xlsx manual]
    end

    BROWSER <-->|HTTPS + JWT cookie\n+ CSRF| FASTAPI
    SCHEDULER -->|dispara| CONNECTORS
    CONNECTORS <-->|HTTPS REST| PROVIDERS
    CONNECTORS -->|upsert| SOURCE_RECORDS
    SOURCE_RECORDS -->|materializa| STG_VPOS
    SOURCE_RECORDS -->|materializa| STG_TOKU
    SOURCE_RECORDS -->|materializa| STG_PAYKU
    P_TCH -->|carga manual POST| ROUTER_TCH
    ROUTER_TCH -->|upsert| STG_TCH
    ETL_VPOS & ETL_TOKU & ETL_PAYKU & ETL_TCH -->|transforma| CORE_DB
    STG_VPOS -->|lee| ETL_VPOS
    STG_TOKU -->|lee| ETL_TOKU
    STG_PAYKU -->|lee| ETL_PAYKU
    STG_TCH -->|lee| ETL_TCH
    ROUTER_WEBHOOKS --> WH_TOKU & WH_VPOS & WH_PAYKU
    WH_TOKU & WH_VPOS & WH_PAYKU -->|persiste| STG_WEBHOOKS
    SVC_MATCH -->|lee/escribe| CORE_MATCH
    ROUTER_SYNC -->|ejecuta| ETL_VPOS & ETL_TOKU & ETL_PAYKU & ETL_TCH
    ROUTER_SYNC --> SVC_MATCH
    SVC_VPOS_WRITE & SVC_TOKU_WRITE -->|registra| WRITE_RUNS
    SVC_VPOS_WRITE -->|llama| CONN_VPOS
    SVC_TOKU_WRITE -->|llama| CONN_TOKU
    SVC_AUTH -->|lee/escribe| USERS
    SVC_CACHE -.->|cache TTL| ROUTER_CORE & ROUTER_VPOS & ROUTER_TOKU
    CONNECTORS -->|registra| SYNC_RUNS
    ETL_VPOS & ETL_TOKU & ETL_PAYKU & ETL_TCH -->|registra| ETL_RUNS
```

---

## Descripción de componentes principales

### Capa de presentación (React SPA)

| Componente | Función |
|------------|---------|
| `Dashboard & KPIs` | Resumen general, KPIs multi-canal, alertas operativas |
| `Exploradores por canal` | Tablas y fichas para VirtualPOS / Toku / Payku / TCH con filtros |
| `Vista consolidada Core` | Búsqueda y fichas de `core_clients`, suscripciones y pagos unificados |
| `Recuperador VirtualPOS` | Vista especializada para cargos rechazados y reintento de cobros |
| `Administración` | CRUD de usuarios, roles y permisos |

### API (FastAPI)

| Componente | Función |
|------------|---------|
| `auth_service` | Login/logout, JWT HttpOnly cookie, CSRF, Argon2 |
| `cache_service` | Cache en memoria con TTL (5 min); invalidada por sync y webhooks |
| `client_match_detector` | Detecta candidatos de match cross-canal por RUT y email (EPIC-C) |
| `APScheduler` | Dispara sincronizaciones periódicas sin broker externo |
| Connectors | Clientes HTTP async para VirtualPOS, Toku, Payku |
| ETL Core | Transforma staging → `core_*` para cada proveedor |
| Receptores webhook | Reciben eventos de proveedor, verifican firma, persisten en staging |

### Base de datos (PostgreSQL)

| Capa | Tablas representativas | Propósito |
|------|------------------------|-----------|
| Staging/Raw | `source_records`, `vp_*`, `t_*`, `p_*`, `tch_*` | Datos de origen preservados, trazables, saneados |
| Staging Webhooks | `stg_*_webhook_events` | Eventos recibidos de proveedores pendientes de procesar |
| Core | `core_clients`, `core_subscriptions`, `core_charges`, `core_payments` | Modelo centralizado independiente de proveedor |
| Identidad | `core_client_attributes`, `client_match_candidates` | Atributos personales + candidatos de deduplicación |
| Operacional | `sync_runs`, `etl_runs`, `write_runs`, `users` | Trazabilidad de operaciones y autenticación |

---

*Documento generado como parte de la Fase 1 — Arquitectura base.*
