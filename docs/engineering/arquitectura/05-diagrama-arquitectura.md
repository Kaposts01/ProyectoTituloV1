# Diagrama de Arquitectura — SynkmetriX

**Última actualización:** 2026-10-20
**Ítem cubierto:** 9 (diagrama de arquitectura formal — reemplaza el ASCII de overview.md)

---

## Arquitectura de capas (vista canónica)

```mermaid
graph LR
    subgraph EXT["Fuentes externas"]
        VP[VirtualPOS\nREST API]
        TK[Toku\nREST API]
        PK[Payku\nREST API]
        TC[TCH\nExcel .xlsx]
        WH_IN[Webhooks entrantes\nVP / Toku / Payku]
    end

    subgraph L1["Layer 1 — Ingesta"]
        CONN[Connectors\nvirtualpos_client\ntoku_client\npayku_client]
        WH_RCV[Receptores webhook\nHMAC-SHA256 / token]
        ETL_XLS[Parser Excel\npandas + openpyxl]
        SCHED[APScheduler\nsync periódica]
    end

    subgraph L2["Layer 2 — Staging"]
        SR[(source_records\nraw JSONB saneado)]
        CANAL[(tablas de canal\nvp_* / t_* / p_* / tch_*)]
        STG_WH[(stg_*_webhook_events)]
    end

    subgraph L3["Layer 3 — Core centralizado"]
        CC[(core_clients\n+ core_client_attributes)]
        CS[(core_subscriptions)]
        CP[(core_charges\n+ core_payments)]
        CM[(client_match_candidates\nADR-001)]
    end

    subgraph OPS["Operacional (transversal)"]
        SR_OPS[(sync_runs)]
        ETL_OPS[(etl_runs)]
        WR_OPS[(write_runs)]
        USR[(users + roles)]
    end

    subgraph API["FastAPI :8000"]
        REST[Routers REST\n/auth /etl /core\n/virtualpos /toku\n/payku /tch /admin]
        WR[Write services\n+ WRITES_ENABLED flag]
        CACHE[Cache TTL 5 min\nin-memory]
    end

    subgraph FE["Frontend React/Vite :5173→build"]
        SPA[SPA TypeScript\nRecharts dashboards\nexploradores + fichas]
    end

    VP & TK & PK -->|HTTPS REST| CONN
    TC -->|POST upload| ETL_XLS
    WH_IN -->|POST signed| WH_RCV
    SCHED -->|dispara| CONN
    CONN -->|upsert idempotente| SR
    SR -->|materializa| CANAL
    ETL_XLS -->|upsert| CANAL
    WH_RCV -->|persiste| STG_WH
    CANAL -->|ETL Core| CC & CS & CP
    CC & CS & CP --> CM
    CONN --> SR_OPS
    CANAL --> ETL_OPS
    WR --> WR_OPS
    REST --> CANAL & CC & CS & CP & CM
    REST --> WR
    WR -->|escribe via connector| VP & TK
    CACHE -.->|acelera| REST
    SPA <-->|HTTPS + JWT cookie\n+ CSRF| REST
    REST --> USR

    classDef external fill:#E8F4FD,stroke:#2980B9
    classDef layer1 fill:#EBF5FB,stroke:#1A5276
    classDef layer2 fill:#FEF9E7,stroke:#B7950B
    classDef layer3 fill:#EAFAF1,stroke:#1E8449
    classDef ops fill:#F9F9F9,stroke:#888
    classDef api fill:#F5EEF8,stroke:#6C3483
    classDef fe fill:#FEF5E7,stroke:#CA6F1E

    class VP,TK,PK,TC,WH_IN external
    class CONN,WH_RCV,ETL_XLS,SCHED layer1
    class SR,CANAL,STG_WH layer2
    class CC,CS,CP,CM layer3
    class SR_OPS,ETL_OPS,WR_OPS,USR ops
    class REST,WR,CACHE api
    class SPA fe
```

---

## Arquitectura de despliegue (vista infraestructura — desarrollo local)

```mermaid
graph TD
    subgraph LOCAL["Máquina local (Windows 11)"]
        subgraph DOCKER["Docker Desktop"]
            PG[(PostgreSQL 17\ncrm_projectotitulo-postgres-1\n:5433\nvolumen: crm_projectotitulo_postgres_data)]
        end

        subgraph PYTHON["Python 3.14.5 (venv)"]
            UVICORN[uvicorn\n127.0.0.1:8000\nFastAPI app]
        end

        subgraph NODE["Node.js"]
            VITE[Vite dev server\n:5173\nproxy → :8000]
        end

        ENV[".env\ncredenciales locales\n(no versionado)"]
    end

    BROWSER_DEV[Navegador\ndesarrollo]
    BROWSER_DEV <-->|http://localhost:5173| VITE
    VITE <-->|proxy /api/v1| UVICORN
    UVICORN <-->|psycopg3| PG
    UVICORN <-->|httpx| VP_API[VirtualPOS API]
    UVICORN <-->|httpx| TK_API[Toku API]
    UVICORN <-->|httpx| PK_API[Payku API]
    ENV -.->|carga vars| UVICORN
```

---

## Flujo de datos — resumen de capas

```mermaid
sequenceDiagram
    participant P as Proveedor
    participant C as Connector / Parser
    participant S as Staging (L2)
    participant E as ETL Core
    participant D as Core DB (L3)
    participant A as FastAPI
    participant U as Operador (UI)

    U->>A: POST /etl/full-sync
    A->>C: dispara sync
    C->>P: GET /subscriptions?page=N
    P-->>C: payload JSON
    C->>C: sanitizar (elimina PAN/CVV)
    C->>S: upsert source_records
    C->>S: upsert tablas de canal
    A->>E: POST /etl/core/{provider}
    E->>S: lee tablas de canal
    E->>D: upsert core_clients / subscriptions / charges / payments
    A-->>U: { status: completed, counts: {...} }
    U->>A: GET /api/v1/core/clients
    A->>D: query core_clients + atributos
    A-->>U: lista socios consolidada
```

---

## Principios arquitectónicos activos

| Principio | Implementación |
|-----------|---------------|
| Separación de capas | Connectors → Staging → ETL → Core; ningún proveedor escribe en Core directamente |
| Idempotencia | Clave `(source, resource_type, external_id)` en `source_records`; re-sync es segura |
| Trazabilidad | `sync_runs`, `etl_runs`, `write_runs` registran toda operación con timestamps y conteo |
| Sin merge automático | `client_match_candidates` requiere revisión manual (ADR-001) |
| Writes controlados | Flag `*_WRITES_ENABLED` por proveedor; toda escritura externa queda en `write_runs` |
| PII mínima | PAN/CVV eliminados antes de staging; RUT/email tratados como atributos, no claves |

---

*Documento generado como parte de la Fase 1 — Arquitectura base.*
*Este diagrama reemplaza el ASCII de `docs/architecture/overview.md`.*
