# BPMN Técnico — Flujos del Sistema

**Última actualización:** 2026-10-20
**Ítem cubierto:** 3 (diagrama BPMN — perspectiva técnica/sistema)

Cubre los 4 flujos internos principales del backend de SynkmetriX.
Para flujos desde la perspectiva del operador, ver [03-bpmn-operacional.md](./03-bpmn-operacional.md).

---

## Flujo 1 — Sincronización de datos de proveedor (API polling)

Aplica a VirtualPOS (2 cuentas), Toku y Payku. TCH usa el Flujo 4.

```mermaid
flowchart TD
    A([Inicio: Scheduler o POST /etl/full-sync]) --> B[Crear sync_run con status='running']
    B --> C[Connector lee endpoint del proveedor]
    C --> D{¿Rate limit o error?}
    D -->|Sí| E[Esperar backoff exponencial]
    E --> C
    D -->|No| F[Sanitizar payload\neliminar PAN/CVV/tokens]
    F --> G{¿Ya existe source_record?\nkey: source+resource_type+external_id}
    G -->|Sí, mismo hash| H[Omitir — sin cambio]
    G -->|No o hash distinto| I[Upsert source_record\n+ SourceRecordObservation]
    H --> J{¿Más páginas?}
    I --> J
    J -->|Sí| C
    J -->|No| K[Upsert tablas de canal\ne.g. vp_subscriptions, p_transactions]
    K --> L[Marcar sync_run status='completed']
    L --> M[Invalidar caché de dashboard]
    M --> Z([Fin])

    style A fill:#4A90D9,color:#fff
    style Z fill:#5CB85C,color:#fff
    style E fill:#F0AD4E,color:#fff
    style H fill:#999,color:#fff
```

**Garantías:**
- Idempotente: re-ejecutar produce el mismo resultado.
- `sync_runs` registra cada ejecución con timestamps y conteo de registros.
- Datos de tarjeta eliminados en `payload_sanitization.py` antes de persistir.

---

## Flujo 2 — Recepción de webhook

Aplica a Toku (HMAC-SHA256), VirtualPOS (HMAC en payout), Payku (token en query).

```mermaid
flowchart TD
    A([Proveedor envía POST /api/v1/webhooks/{provider}/{kind}]) --> B{¿Autenticación válida?}
    B -->|No — 401| E1([Retornar 401 Unauthorized])
    B -->|No configurada — 503| E2([Retornar 503 Service Unavailable])
    B -->|Sí| C[Persistir en tabla stg_*_webhook_events\ncon payload JSONB + source_ip]
    C --> D[Retornar 200 OK inmediatamente]
    D --> F[BackgroundTask: invalidar caché]
    F --> Z([Fin])

    E1 -.->|Log intento fallido| LOG[(stg_*_webhook_events\nno registrado)]
    style A fill:#4A90D9,color:#fff
    style Z fill:#5CB85C,color:#fff
    style E1 fill:#D9534F,color:#fff
    style E2 fill:#F0AD4E,color:#fff
```

**Tablas de staging:**
- `stg_toku_webhook_events` — con `toku_event_id` para idempotencia
- `stg_vpos_webhook_events` — con `signature_verified` (Boolean)
- `stg_payku_webhook_events` — con `raw_body` + headers filtrados

**Nota:** Los webhooks se reciben y persisten; el procesamiento hacia Core queda pendiente (sprint futuro).

---

## Flujo 3 — ETL hacia entidades Core (Layer 3)

Aplica a los 4 proveedores. Transforma tablas de canal hacia `core_*`.

```mermaid
flowchart TD
    A([Inicio: POST /etl/core/{provider} o schedule]) --> B[Crear etl_run status='running']
    B --> C[Leer tablas de canal del proveedor\ne.g. vp_subscriptions, t_subscriptions]
    C --> D{¿Existe core_client\npara este external_id?}
    D -->|No| E[Crear core_client con UUID]
    D -->|Sí| F[Usar core_client existente]
    E & F --> G[Upsert ExternalIdentity\nsource + resource_type + external_id]
    G --> H[Upsert core_subscription\ncon source + external_id]
    H --> I[Upsert core_charges\nvínculo a core_subscription]
    I --> J[Upsert core_payments\nvínculo a core_charge o suscripción]
    J --> K[Upsert core_client_attributes\nRUT, email, teléfono por fuente]
    K --> L[Commit transacción]
    L --> M{¿Error?}
    M -->|Sí| N[Rollback + etl_run status='failed']
    M -->|No| O[etl_run status='completed'\n+ conteo de registros]
    N --> Z([Fin con error])
    O --> Z2([Fin exitoso])

    style A fill:#4A90D9,color:#fff
    style Z fill:#D9534F,color:#fff
    style Z2 fill:#5CB85C,color:#fff
```

**Garantía de idempotencia:** `UNIQUE(source, external_id)` en `core_subscriptions`, `core_charges`, `core_payments`. Re-ejecutar es seguro.

---

## Flujo 4 — Carga ETL desde Excel TCH

```mermaid
flowchart TD
    A([Inicio: POST /etl/tch/import o CLI scripts/etl_tch.py]) --> B[Leer archivo .xlsx con openpyxl/pandas]
    B --> C{¿Formato válido?\nhojas esperadas presentes}
    C -->|No| E1([Error: formato inválido])
    C -->|Sí| D[Parsear filas con tipos explícitos\nRUT, nombre, monto, fecha, estado]
    D --> E[Sanitizar y normalizar\nstrip, uppercase RUT, parse fecha]
    E --> F[Upsert en tablas tch_*\ncon idempotencia por RUT+periodo]
    F --> G{¿Modo full?}
    G -->|Sí| H[Operación atómica:\nborra y recarga el periodo completo]
    G -->|No| I[Upsert incremental:\nsolo filas nuevas o modificadas]
    H & I --> J[Registrar etl_run con conteo]
    J --> K[Disponible para ETL Core → core_*]
    K --> Z([Fin])

    style A fill:#4A90D9,color:#fff
    style Z fill:#5CB85C,color:#fff
    style E1 fill:#D9534F,color:#fff
```

---

## Flujo 5 — Detección de match cross-canal (EPIC-C)

```mermaid
flowchart TD
    A([Inicio: POST /etl/core/detect-matches]) --> B[Scan core_client_attributes\ndonde attribute_type = 'rut']
    B --> C[JOIN por RUT normalizado\nvalidando checksum módulo 11]
    C --> D[Scan core_client_attributes\ndonde attribute_type = 'email']
    D --> E[JOIN por email normalizado\nlowercase + trim]
    E --> F[Merge señales por par de clientes\nnivel B = RUT, nivel C = email]
    F --> G{¿Par ya existe en\nclient_match_candidates?}
    G -->|Sí| H[Actualizar match_signals\ncon nuevas señales]
    G -->|No| I[Insertar candidato\nstatus='pending', a < b por UUID]
    H & I --> J[Retornar conteos\nB=N, C=N, inserted=N, skipped=N]
    J --> Z([Fin — sin merge automático])

    style A fill:#4A90D9,color:#fff
    style Z fill:#5CB85C,color:#fff
    style I fill:#9B59B6,color:#fff
```

**ADR-001:** Ningún merge automático. Los candidatos en `client_match_candidates` requieren revisión manual.

---

*Documento generado como parte de la Fase 1 — Arquitectura base.*
