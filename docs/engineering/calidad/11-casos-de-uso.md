# Casos de Uso — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Catálogo de casos de uso del sistema, clasificados por actor y dominio funcional.

---

## 1. Actores

| Actor | Descripción |
|-------|-------------|
| **Operador CRM** | Usuario interno que ejecuta sincronizaciones, revisa datos, gestiona duplicados |
| **Administrador** | Usuario con privilegios de escritura hacia proveedores y gestión de usuarios |
| **Sistema (scheduler)** | Proceso automatizado que dispara sincronizaciones periódicas |
| **Proveedor externo** | VirtualPOS, Toku, Payku — interactúan vía API o Excel |

---

## 2. Diagrama general

```mermaid
graph TD
    subgraph Actores
        OP[Operador CRM]
        ADM[Administrador]
        SCH[Sistema / Scheduler]
        PROV[Proveedor externo]
    end

    subgraph UC_SYNC["Sincronización"]
        S1[UC-S1: Sincronizar proveedor]
        S2[UC-S2: Ver estado de sync]
        S3[UC-S3: Re-ejecutar sync fallida]
    end

    subgraph UC_ETL["ETL Core"]
        E1[UC-E1: Ejecutar ETL por proveedor]
        E2[UC-E2: Ejecutar ETL global]
        E3[UC-E3: Ver resultado de ETL]
    end

    subgraph UC_CONS["Consulta"]
        C1[UC-C1: Buscar cliente por RUT]
        C2[UC-C2: Ver suscripciones de cliente]
        C3[UC-C3: Ver historial de pagos]
        C4[UC-C4: Ver candidatos de match]
    end

    subgraph UC_OPS["Operaciones]
        O1[UC-O1: Revisar candidatos de merge]
        O2[UC-O2: Ejecutar carga TCH Excel]
        O3[UC-O3: Ver rechazos por proveedor]
    end

    subgraph UC_ADM["Administración"]
        A1[UC-A1: Habilitar escrituras a proveedor]
        A2[UC-A2: Ver logs de escritura]
        A3[UC-A3: Gestionar webhooks]
    end

    OP --> S1
    OP --> S2
    OP --> S3
    OP --> E1
    OP --> E2
    OP --> E3
    OP --> C1
    OP --> C2
    OP --> C3
    OP --> C4
    OP --> O1
    OP --> O2
    OP --> O3
    ADM --> A1
    ADM --> A2
    ADM --> A3
    SCH --> S1
    SCH --> E2
    PROV --> S1
```

---

## 3. Catálogo detallado

### UC-S1 — Sincronizar proveedor

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM / Sistema |
| **Precondición** | Credenciales del proveedor configuradas en `.env`; Docker PostgreSQL activo |
| **Trigger** | Manual vía `POST /sync/{provider}` o automático por scheduler |
| **Flujo principal** | 1. Sistema autentica al proveedor. 2. Pagina todos los recursos (suscripciones, cargos, pagos). 3. Escribe en `source_records` con `(source, resource_type, external_id)`. 4. Upsert en tablas de canal (`vp_*`, `tk_*`, `p_*`). 5. Registra `SyncRun` con estado, conteo y errores. |
| **Flujo alternativo** | Proveedor devuelve error 5xx: reintento con backoff. Tras 3 intentos registra `SyncRun.status=failed`. |
| **Postcondición** | `source_records` y tablas de canal actualizados; `SyncRun` registrado |
| **Restricciones** | `*_WRITES_ENABLED=false` durante sync (lectura solo). TCH no tiene endpoint — se usa carga manual (UC-O2). |

### UC-S2 — Ver estado de sincronización

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Flujo** | Operador consulta `GET /sync/runs` o el dashboard → ve lista de runs con proveedor, fecha, duración, registros creados/actualizados, errores |
| **Dato clave** | `SyncRun.status`: `running`, `completed`, `failed`, `partial` |

### UC-S3 — Re-ejecutar sync fallida

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Precondición** | `SyncRun.status = 'failed'` o `'partial'` |
| **Flujo** | Operador inspecciona el error en logs → corrige la causa (credencial expirada, timeout) → re-ejecuta `POST /sync/{provider}` |
| **Idempotencia** | Las escrituras son idempotentes via `(source, resource_type, external_id)` — re-ejecutar no duplica |

### UC-E1 — Ejecutar ETL Core por proveedor

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Precondición** | Tablas de canal (`vp_*`, `tk_*`, `p_*`, `tch_*`) con datos frescos |
| **Trigger** | `POST /etl/core/{provider}` — corre en background task |
| **Flujo** | 1. ETL lee tablas de canal en batches de 500. 2. Resuelve identidad vía `core_clients` + `external_identities`. 3. Crea/actualiza `core_subscriptions`, `core_charges`, `core_payments`. 4. Registra `EtlRun` con conteos. |
| **Postcondición** | Core Layer actualizado para el proveedor; `EtlRun` registrado |
| **Restricción** | Requiere que el sync haya corrido primero. No escribe a proveedores. |

### UC-E2 — Ejecutar ETL global

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM / Sistema |
| **Trigger** | `POST /etl/core/all` |
| **Flujo** | Ejecuta UC-E1 en orden para los 4 proveedores: TCH → VirtualPOS → Toku → Payku |
| **Postcondición** | Todo el Core Layer sincronizado con el estado más reciente de staging |

### UC-C1 — Buscar cliente por RUT

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Flujo** | Operador ingresa RUT → sistema consulta `core_clients` via `external_identities.attribute_value` → devuelve ficha con nombre, fuentes, subscripciones activas |
| **Dato clave** | Un mismo RUT puede tener `core_clients` en varios canales si ADR-001 no ha cerrado el match |

### UC-C2 — Ver suscripciones de cliente

| Campo | Valor |
|-------|-------|
| **Flujo** | `GET /clients/{id}/subscriptions` → lista `core_subscriptions` con canal de origen, estado, monto, fecha inicio |
| **Nota** | `started_at` de Toku refleja la fecha del próximo cobro (TK-1) — interpretar con cautela |

### UC-C3 — Ver historial de pagos

| Campo | Valor |
|-------|-------|
| **Flujo** | `GET /clients/{id}/payments` → lista `core_payments` con monto, fecha, proveedor, estado fuente |
| **Nota** | VirtualPOS solo muestra pagos 'pagado' (VP-2). No hay pagos rechazados en Core para VP. |

### UC-C4 — Ver candidatos de match

| Campo | Valor |
|-------|-------|
| **Flujo** | `GET /match/candidates` → lista `client_match_candidates` con score, razón, pares de `core_client_id` |
| **Restricción** | ADR-001: nunca merge automático. Solo revisión manual (UC-O1). |

### UC-O1 — Revisar candidatos de merge

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Precondición** | `client_match_candidates` con `status = 'pending'` |
| **Flujo** | Operador revisa el par → si confirma: `PATCH /match/candidates/{id}` con `decision=accept` → sistema marca ambos `core_clients` como vinculados |
| **Alternativo** | Rechaza: `decision=reject` → se registra pero no se fusiona |
| **Restricción** | No existe aún endpoint de fusión real — pendiente de implementación |

### UC-O2 — Ejecutar carga TCH Excel

| Campo | Valor |
|-------|-------|
| **Actor principal** | Operador CRM |
| **Precondición** | Archivo Excel TCH disponible con el formato estándar `AAAAMMDD TCH IG*.XLSX` |
| **Flujo** | Operador ejecuta `python -m app.etl.tch.load --file <path>` → script parsea hojas `CARGOS ACEPTADOS` y `CARGOS RECHAZADOS` → upsert en `tch_transacciones` via `dedupe_key` → upsert en `tch_suscripciones` y `tch_clientes` |
| **Postcondición** | `tch_recaudacion_mensual` actualizado; 0 duplicados gracias a `dedupe_key` |

### UC-O3 — Ver rechazos por proveedor

| Campo | Valor |
|-------|-------|
| **Flujo** | Dashboard → tabla de `core_charges` + staging joins → agrupa por proveedor/motivo |
| **Restricción** | VirtualPOS: rechazos no en Core (VP-2). Toku: invoice status UNPAID no en Core (TK-2). TCH: `razon_rechazo` en staging pero no en Core (TCH-3). |

### UC-A1 — Habilitar escrituras a proveedor

| Campo | Valor |
|-------|-------|
| **Actor principal** | Administrador |
| **Precondición** | `VPOS_WRITES_ENABLED=false` (o equivalente Toku) |
| **Flujo** | Administrador cambia flag en `.env` + reinicia servicio → habilitado solo para operaciones autorizadas |
| **Restricción** | Nunca habilitar sin caso de negocio explícito. Las escrituras son irreversibles en el proveedor. |

### UC-A3 — Gestionar webhooks

| Campo | Valor |
|-------|-------|
| **Estado actual** | Toku (D2) implementado pero no activado en producción. VirtualPOS (D3) y Payku (D4) implementados, pendientes de activación. |
| **Flujo** | Administrador registra URL del webhook en la plataforma del proveedor → SynkmetriX recibe `POST /webhooks/{provider}` → procesa evento en tiempo real |

---

## 4. Matriz de cobertura funcional

| Dominio | Implementado | Parcial | Pendiente |
|---------|-------------|---------|-----------|
| Sync VirtualPOS | ✅ | | |
| Sync Toku | ✅ | | |
| Sync Payku | ✅ | | |
| Sync TCH (batch Excel) | ✅ | | |
| ETL Core (4 proveedores) | ✅ | | |
| Deduplicación cross-canal | | ✅ (EPIC-C implementado) | Fusión manual pendiente |
| Webhooks | | ✅ (código listo) | Activación producción |
| Rechazos en Core | | | ✅ (VP-2, TK-2, TCH-3 pendientes) |
| Escrituras a proveedor | | ✅ (flags) | Por caso de negocio |

---

*Documento generado el 2026-10-20. Refleja la arquitectura actual en rama `master`.*
