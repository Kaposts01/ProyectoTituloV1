# Topología de Comunicaciones — SynkmetriX

**Última actualización:** 2026-10-20
**Ítem cubierto:** 7 (topología de comunicaciones)

---

## Mapa general de comunicaciones

```mermaid
graph LR
    subgraph CLIENT["Cliente"]
        BROWSER[Navegador\nReact SPA]
    end

    subgraph CRM["CRM Local"]
        VITE[Vite :5173\ndev / build]
        API[FastAPI :8000\nuvicorn]
        SCHED[APScheduler\nin-process]
    end

    subgraph DB["Base de datos"]
        PG[(PostgreSQL :5433\nDocker)]
    end

    subgraph PROV_OUT["Proveedores — ingesta saliente"]
        VP_API[VirtualPOS\nhttps://api.virtualpos.cl]
        TK_API[Toku\nhttps://api.toku.cl]
        PK_API[Payku\nhttps://app.payku.cl/api]
    end

    subgraph PROV_IN["Proveedores — webhooks entrantes"]
        VP_WH[VirtualPOS\nPayout events]
        TK_WH[Toku\nSubscription events]
        PK_WH[Payku\nTransaction events]
    end

    BROWSER -->|HTTPS GET/POST\nJWT cookie + CSRF| VITE
    VITE -->|proxy /api/v1\nHTTP local| API
    SCHED -->|in-process call| API
    API -->|psycopg3 TCP :5433| PG
    API -->|HTTPS REST GET\nhttpx + retry| VP_API
    API -->|HTTPS REST GET\nhttpx + retry| TK_API
    API -->|HTTPS REST GET\nhttpx + retry| PK_API
    API -->|HTTPS REST POST\nWrite service| VP_API
    API -->|HTTPS REST POST\nWrite service| TK_API
    VP_WH -->|HTTPS POST\nHMAC-SHA256| API
    TK_WH -->|HTTPS POST\nHMAC-SHA256| API
    PK_WH -->|HTTPS POST\ntoken en query| API
```

---

## Tabla de canales de comunicación

| Canal | Protocolo | Dirección | Auth | Idempotencia |
|-------|-----------|-----------|------|--------------|
| Browser → Vite → API | HTTPS (dev: HTTP local) | Saliente del navegador | JWT HttpOnly + CSRF token | — |
| API → VirtualPOS (lectura) | HTTPS REST | Saliente | API Key en header | `(source, resource_type, external_id)` en `source_records` |
| API → Toku (lectura) | HTTPS REST | Saliente | API Key en header | `(source, resource_type, external_id)` en `source_records` |
| API → Payku (lectura) | HTTPS REST | Saliente | API Key Bearer | `(source, resource_type, external_id)` en `source_records` |
| API → VirtualPOS (escritura) | HTTPS REST | Saliente | API Key en header | `write_runs` + flag `VPOS_WRITES_ENABLED` |
| API → Toku (escritura) | HTTPS REST | Saliente | API Key en header | `write_runs` + flag `TOKU_WRITES_ENABLED` |
| VirtualPOS → API (webhook) | HTTPS POST | Entrante | HMAC-SHA256 sobre body | `stg_vpos_webhook_events.id` único |
| Toku → API (webhook) | HTTPS POST | Entrante | HMAC-SHA256 + `toku_event_id` | `stg_toku_webhook_events.toku_event_id` |
| Payku → API (webhook) | HTTPS POST | Entrante | Token en query param | `stg_payku_webhook_events.id` único |
| API → PostgreSQL | psycopg3 TCP | Saliente | usuario/password | Constraints UNIQUE en tablas |
| APScheduler → API | In-process Python | Interna | N/A | Idempotencia del conector |

---

## Diagrama de secuencia — autenticación del operador

```mermaid
sequenceDiagram
    participant B as Navegador
    participant A as FastAPI
    participant DB as PostgreSQL

    B->>A: POST /api/v1/auth/login {username, password}
    A->>DB: SELECT user WHERE username=?
    DB-->>A: User + password_hash
    A->>A: Argon2.verify(password, hash)
    alt Credenciales válidas
        A->>A: JWT.encode(user_id, roles, exp=8h)
        A-->>B: Set-Cookie: session=<JWT> (HttpOnly, Secure, SameSite=Lax)
        A-->>B: X-CSRF-Token: <token>
        B->>A: GET /api/v1/auth/me (cookie automática)
        A-->>B: {username, roles, permissions}
    else Credenciales inválidas
        A-->>B: 401 Unauthorized
    end
```

---

## Diagrama de secuencia — write con CSRF

```mermaid
sequenceDiagram
    participant B as Navegador
    participant A as FastAPI
    participant WS as Write Service
    participant P as Proveedor

    B->>A: GET /api/v1/virtualpos/subscriptions/{id}
    A-->>B: datos + X-CSRF-Token en respuesta

    B->>A: POST /api/v1/virtualpos/write/charge-subscription\n{sub_id, ...} + Cookie JWT + X-CSRF-Token header
    A->>A: Verificar JWT (válido, no expirado)
    A->>A: Verificar CSRF token
    A->>A: Verificar permiso 'virtualpos.write'
    A->>A: Verificar VPOS_WRITES_ENABLED=true
    A->>WS: execute_charge(sub_id)
    WS->>DB: INSERT write_run status='started'
    WS->>P: POST /subscriptions/{id}/charge (HTTPS)
    P-->>WS: {status: approved/rejected, code}
    WS->>DB: UPDATE write_run status='completed'\n+ response_payload
    WS-->>A: WriteResult
    A-->>B: {status, result}
```

---

## Diagrama de secuencia — recepción de webhook Toku

```mermaid
sequenceDiagram
    participant T as Toku
    participant A as FastAPI
    participant DB as PostgreSQL
    participant BG as BackgroundTask

    T->>A: POST /api/v1/webhooks/toku/subscription\nX-Toku-Signature: hmac-sha256=<sig>\n{event_type, data, id}

    A->>A: Verificar HMAC-SHA256\nhmac(secret, raw_body) == sig
    alt Firma inválida
        A-->>T: 401 Unauthorized
    else Firma válida
        A->>DB: INSERT stg_toku_webhook_events\n{toku_event_id, payload, signature_verified=true}
        A-->>T: 200 OK (inmediato — <200ms)
        A->>BG: invalidar_cache(keys=['dashboard', 'toku'])
        BG->>BG: cache.clear(pattern)
    end
```

---

## Puertos y endpoints expuestos

| Puerto | Servicio | Acceso | Notas |
|--------|---------|--------|-------|
| `:8000` | FastAPI (uvicorn) | `127.0.0.1` solamente | No expuesto públicamente en local |
| `:5173` | Vite dev server | `localhost` | Solo en desarrollo; en producción sirve build estático |
| `:5433` | PostgreSQL (Docker) | `localhost` | Interno; credenciales en `.env` |
| `443` (futuro) | HTTPS público | Internet | Requerido para activar webhooks en producción |

---

## Restricciones y notas de seguridad

- Las credenciales de proveedores (API Keys) se leen desde `.env` en runtime; nunca se almacenan en git ni se exponen en logs.
- El JWT viaja solo como cookie HttpOnly: el JavaScript del navegador no puede accederlo.
- El CSRF token se requiere en todas las mutaciones (POST/PUT/DELETE) para proteger contra ataques cross-site.
- Los webhooks verifican firma criptográfica antes de persistir; un webhook sin firma válida retorna 401 y no escribe nada.
- Las escrituras externas requieren `*_WRITES_ENABLED=true` en `.env` como segunda capa de control; por defecto están deshabilitadas.
- Los payloads de proveedores son sanitizados (se eliminan PAN/CVV/tokens de tarjeta) antes de persistir en `source_records`.

---

*Documento generado como parte de la Fase 2 — Datos y comunicaciones.*
