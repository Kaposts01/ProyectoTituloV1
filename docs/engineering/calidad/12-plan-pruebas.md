# Plan de Pruebas — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Estrategia y catálogo de pruebas para garantizar la correctitud de los flujos críticos del sistema.

---

## 1. Estrategia general

SynkmetriX es un sistema ETL/CRM donde los errores en datos son costosos y difíciles de revertir. La estrategia de pruebas prioriza:

1. **Integridad de datos** sobre cobertura de código
2. **Idempotencia** en todos los flujos de ingesta
3. **Aislamiento** de pruebas que tocan proveedores externos
4. **Sin mocks de base de datos** para tests de integración — se usa PostgreSQL real en Docker

### Pirámide de pruebas aplicada

```
          ┌───────────────────────┐
          │   E2E / Manual QA     │  ← UI, flujos completos, webhooks
          ├───────────────────────┤
          │  Integración (BD real)│  ← ETL, sync, identidad, idempotencia
          ├───────────────────────┤
          │   Unitarias (helpers) │  ← Pure functions, mapeos, transformaciones
          └───────────────────────┘
```

---

## 2. Entorno de pruebas

| Componente | Configuración |
|-----------|---------------|
| PostgreSQL | Docker en puerto 5433, BD `crm_test` |
| Python | 3.14.5, `.venv/Scripts/pytest.exe` |
| Variables | `DATABASE_URL=postgresql://crm:crm@localhost:5433/crm_test` |
| Fixtures | Alembic aplica todas las migraciones antes del suite |
| Datos externos | Fixtures hardcodeadas — nunca llamar APIs reales en CI |

**Comando base:**
```bash
PYTHONPATH=. .venv/Scripts/pytest.exe tests/ -v
```

---

## 3. Categorías y rutas de prueba

### 3.1 Tests unitarios — helpers y transformaciones

**Ubicación:** `tests/test_core_etl_helpers.py` (66 tests existentes)

| Test | Descripción |
|------|-------------|
| `test_vp_social_id_normalization` | RUT normalizado, sin espacios, dígito verificador preservado |
| `test_toku_anchor_semantics` | `anchor` → `started_at`: confirmar que es fecha ISO, no día de mes |
| `test_payku_amount_zero_rejection` | Transacciones rechazadas con amount=0 vs amount real |
| `test_tch_dedupe_key_format` | `dedupe_key` es único por `(numero_ficha, numero_mandato, periodo, numero_cuota)` |
| `test_period_reference_derivation` | `due_at` → `YYYY-MM` para `period_reference` |
| `test_source_status_passthrough` | VirtualPOS: status en español; Toku: NULL; Payku: inglés |

### 3.2 Tests de integración — ETL Core

**Ubicación:** `tests/integration/test_core_etl_*.py`

#### VirtualPOS

| Test | Dato crítico | Qué verifica |
|------|-------------|--------------|
| `test_vp_etl_linkage_by_rut` | VP-1: `client_external_id` NULL | Subscripciones se vinculan a `core_clients` vía `social_id` (RUT) |
| `test_vp_etl_only_pagado` | VP-2: rechazados descartados | `core_payments` solo tiene registros 'pagado'; rechazados ausentes |
| `test_vp_etl_idempotency` | Ejecutar 2 veces mismo dataset | Conteo idéntico en ambas ejecuciones; 0 duplicados |
| `test_vp_charge_no_crossref` | VP-3: `charge_external_id` NULL | `CorePayment.charge_id = NULL` — no lanzar error |

#### Toku

| Test | Dato crítico | Qué verifica |
|------|-------------|--------------|
| `test_toku_anchor_not_started_at` | TK-1: anchor = fecha próximo cobro | `core_subscriptions.started_at` NO es la fecha futura de anchor |
| `test_toku_invoice_status_ignored` | TK-2: invoice status no en Core | `core_charges` no tiene campo `status` con UNPAID/PAID (pendiente de implementar) |
| `test_toku_payment_source_status_null` | TK-3: TokuPayment sin status | `core_payments.source_status = NULL`; no falla ETL |
| `test_toku_stub_subscriptions` | Suscripciones eliminadas | 112 stubs con `status='deleted_at_source'`; facturas huérfanas vinculadas |
| `test_toku_etl_idempotency` | Ejecución repetida | Sin duplicados en Core |

#### Payku

| Test | Dato crítico | Qué verifica |
|------|-------------|--------------|
| `test_payku_rejected_amount_zero` | PK-1: 75% con amount=0 | `CorePayment.amount = 0` es aceptable, no error |
| `test_payku_rejected_amount_real` | PK-1: 25% con monto real | `CorePayment.amount` preserva el monto |
| `test_payku_no_charges` | Sin CoreCharge | Payku no genera `core_charges`; solo `core_payments` |
| `test_payku_etl_idempotency` | Ejecución repetida | Sin duplicados |

#### TCH

| Test | Dato crítico | Qué verifica |
|------|-------------|--------------|
| `test_tch_excel_load_dedupe` | `dedupe_key` | Cargar el mismo Excel 2 veces: 0 nuevas filas |
| `test_tch_etl_rut_linkage` | RUT es la clave | `core_clients` vinculados por RUT vía TCH |
| `test_tch_etl_rejection_reasons` | `razon_rechazo` | `core_charges` (pending TCH-3) o staging |
| `test_tch_etl_idempotency` | Ejecución repetida | Sin duplicados |

### 3.3 Tests de idempotencia (cross-proveedor)

| Test | Qué verifica |
|------|-------------|
| `test_source_records_upsert` | `(source, resource_type, external_id)` único; segunda escritura actualiza, no inserta |
| `test_etl_all_providers_twice` | `POST /etl/core/all` dos veces → mismo conteo en Core |
| `test_sync_and_etl_pipeline` | Sync → ETL en secuencia → Core consistente |

### 3.4 Tests de identidad y match (ADR-001)

| Test | Qué verifica |
|------|-------------|
| `test_no_auto_merge` | Nunca `core_clients` fusionados automáticamente |
| `test_match_candidate_creation` | Mismo RUT en VP y TCH → genera `client_match_candidates` |
| `test_match_candidate_score` | Score calculado correctamente para mismo RUT cross-canal |
| `test_external_identity_uniqueness` | `(source, attribute_type, attribute_value)` unique constraint |

### 3.5 Tests de API REST

| Endpoint | Tests |
|----------|-------|
| `POST /sync/{provider}` | 200 on success, 409 if already running, 400 bad provider |
| `GET /sync/runs` | Paginación, filtro por proveedor, orden por fecha |
| `POST /etl/core/{provider}` | 202 Accepted + task id; idempotente |
| `GET /clients/{id}` | 404 si no existe; datos correctos |
| `GET /clients/{id}/subscriptions` | Lista por proveedor; múltiples fuentes |
| `POST /tch/upload` | 200 con conteo; 400 formato inválido |

### 3.6 Tests de seguridad y control de acceso

| Test | Qué verifica |
|------|-------------|
| `test_jwt_required_on_protected_routes` | 401 sin token |
| `test_rbac_operator_cannot_write` | Operador no puede habilitar WRITES_ENABLED |
| `test_no_credentials_in_logs` | Logs no contienen tokens, RUT completos ni PAN |
| `test_webhook_signature_validation` | Webhook rechazado si HMAC inválido |

---

## 4. Cobertura actual vs objetivo

| Categoría | Tests existentes | Objetivo |
|-----------|-----------------|----------|
| Helpers ETL | 66 | ✅ |
| Integración ETL VP | 0 | 8 |
| Integración ETL Toku | 0 | 8 |
| Integración ETL Payku | 0 | 6 |
| Integración ETL TCH | 0 | 6 |
| Idempotencia | 0 | 5 |
| Identidad / Match | 0 | 4 |
| API REST | 0 | 12 |
| Seguridad | 0 | 4 |

---

## 5. Reglas operativas

1. **No ejecutar tests que hagan escrituras reales a proveedores** sin `VPOS_WRITES_ENABLED=true` explícito y en entorno de staging.
2. **Tests de integración requieren Docker activo** (`docker compose up -d`).
3. **No mockear la base de datos** en tests de integración — los mocks ocultaron migraciones rotas en el pasado.
4. **Cada gap crítico (VP-2, TK-1, TK-2, PK-2, TCH-3) debe tener su test antes de implementar la corrección**.
5. Antes de merge a `master`: `ruff check .` limpio y `pytest tests/` sin nuevos fallos.

---

## 6. Tests pendientes prioritarios

En orden de riesgo:

| Prioridad | Test | Justificación |
|-----------|------|---------------|
| 1 | `test_vp_etl_idempotency` | 71k pagos VP — un duplicado corrompe métricas |
| 2 | `test_tch_excel_load_dedupe` | 1.47M registros TCH — sin dedupe = caos |
| 3 | `test_toku_stub_subscriptions` | 112 stubs con lógica especial |
| 4 | `test_no_auto_merge` | ADR-001 es irrenunciable |
| 5 | `test_vp_etl_only_pagado` | 22,783 rechazados actualmente invisibles |

---

*Documento generado el 2026-10-20.*
