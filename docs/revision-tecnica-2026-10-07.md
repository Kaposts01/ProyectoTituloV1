# Revisión Técnica — SynkmetriX

**Fecha:** 2026-10-07  
**Rama activa:** `feature/core-centralizado`

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| **Backend** | Python · FastAPI · SQLAlchemy ORM · Alembic (migraciones) |
| **Base de datos** | PostgreSQL 17-alpine (Docker) |
| **Frontend** | React + Vite (TypeScript) · SPA servida por FastAPI |
| **Scheduler** | APScheduler (sincronizaciones programadas) |
| **Config** | Pydantic Settings → `.env` |
| **Linting/CI** | Ruff · pytest · GitHub Actions |
| **Runtime Python** | 3.14.5 (bloqueado en `.python-version` + `requirements.lock`) |

---

## Infraestructura

**Docker Compose** (`compose.yaml`) levanta únicamente la base de datos:

- PostgreSQL 17 en `localhost:5433` (puerto no estándar)
- Base de datos: `crm`
- Volumen persistente: `crm_projectotitulo_postgres_data`
- Usuario configurable vía `.env` (`POSTGRES_PASSWORD` obligatorio)

El backend y frontend se levantan por separado (no están dockerizados). FastAPI sirve también el build de Vite (`frontend/dist/`) como archivos estáticos, por lo que en producción local **solo hay un servidor activo**.

---

## URLs de acceso local

| Recurso | URL |
|---|---|
| **Frontend (SPA)** | `http://localhost:8000/` |
| **FastAPI Swagger** | `http://localhost:8000/docs` |
| **FastAPI ReDoc** | `http://localhost:8000/redoc` |
| **Health check** | `http://localhost:8000/health` |
| **PostgreSQL** | `localhost:5433/crm` |

> Durante desarrollo con Vite activo: frontend en `http://localhost:5173` (proxy hacia 8000). Después de `npm run build`, el frontend se sirve directamente desde FastAPI en el 8000.

---

## Arquitectura de datos

```
Fuentes externas
  ↓
Connectors (app/integrations/)
  ↓
source_records  ← staging idempotente por (source, resource_type, external_id)
  ↓
Tablas por canal (vp.py, toku_channel.py, payku_channel.py, tch.py)
  ↓
Core ETL Layer 3  ← POST /etl/core/{provider}
  ↓
Modelo centralizado (core_clients, external_identities, core_subscriptions,
                     core_charges, core_payments, core_client_attributes)
  ↓
FastAPI  →  React SPA
```

---

## Modelo de datos Core

Tablas centralizadas (migraciones `0024–0028`):

| Tabla | Propósito |
|---|---|
| `core_clients` | Entidad cliente con UUID interno |
| `external_identities` | Vincula `client_id` con IDs externos por fuente |
| `core_subscriptions` | Suscripciones normalizadas multi-fuente |
| `core_charges` | Cargos programados / cuotas |
| `core_payments` | Pagos / transacciones |
| `core_client_attributes` | RUT, email, teléfono como atributos trazables (no claves) |

Tablas operativas adicionales: `source_records`, `sync_runs`, `write_runs`, `etl_runs`, tablas `vp_*`, `toku_*`, `payku_*`, `tch_*`.

---

## Canales integrados

| Canal | Tipo | Writes habilitados |
|---|---|---|
| VirtualPOS (2 cuentas) | API REST | Flag `virtualpos_writes_enabled` (off por defecto) |
| Toku | API REST | Flag `toku_writes_enabled` |
| Payku | API REST | Flag `payku_writes_enabled` |
| TCH | Excel → ETL | Solo lectura |

---

## API Backend — grupos de rutas

| Prefijo | Módulo | Descripción |
|---|---|---|
| `/api/v1/auth` | `routes/auth.py` | Autenticación (JWT) |
| `/api/v1/` | `routes/crm.py` | Entidades CRM (clientes, suscripciones, etc.) |
| `/api/v1/sync-runs` | `routes/sync_runs.py` | Ejecuciones de sincronización |
| `/api/v1/staging` | `routes/staging.py` | Registros saneados por canal |
| `/api/v1/etl` | `routes/etl.py` | Disparadores ETL Core |
| `/api/v1/writes` | `routes/writes.py` | Escrituras autorizadas a proveedores |
| `/api/v1/recovery` | `routes/recovery.py` | Recuperación VirtualPOS |
| `/api/v1/admin` | `routes/admin.py` | Usuarios, roles y permisos |
| `/api/v1/catalog` | `routes/catalog.py` | Catálogo de mapeos y QA |
| `/api/v1/tch` | `routes/tch.py` | Canal TCH |
| `/api/v1/reports` | `routes/reports.py` | Reportes automáticos |
| `/api/v1/scheduler` | `routes/scheduler.py` | Orquestador de sincronizaciones |
| `/health` | `main.py` | Estado de la API |

---

## Rutas del frontend (SPA)

| Ruta | Vista |
|---|---|
| `/central/resumen` | Dashboard consolidado |
| `/central/clientes` | Listado clientes centralizados |
| `/central/suscripciones` | Listado suscripciones centralizadas |
| `/central/reporte-automatico` | Reporte automático |
| `/virtualpos/resumen` | Dashboard VirtualPOS |
| `/virtualpos/clientes` | Clientes VirtualPOS |
| `/virtualpos/suscripciones` | Suscripciones VirtualPOS |
| `/virtualpos/cargos` | Cargos VirtualPOS |
| `/virtualpos/transacciones` | Transacciones VirtualPOS |
| `/virtualpos/recuperador-socios` | Recovery VirtualPOS |
| `/toku/resumen` | Dashboard Toku |
| `/toku/clientes`, `/suscripciones`, `/metodos-pago`, `/deudas`, `/transacciones` | Recursos Toku |
| `/payku/resumen` | Dashboard Payku |
| `/payku/clientes`, `/suscripciones`, `/transacciones` | Recursos Payku |
| `/tch/resumen` | Dashboard TCH |
| `/tch/clientes`, `/suscripciones`, `/transacciones` | Recursos TCH |
| `/tch/suscripciones/:numeroFicha` | Ficha de suscripción TCH |
| `/admin/usuarios` | Administración de usuarios |
| `/admin/sincronizaciones` | Historial de sincronizaciones |
| `/mi-perfil` | Perfil de usuario |

---

## Estado actual

- Rama `feature/core-centralizado` en revisión final antes de merge a `master`
- Core ETL completo para los 4 proveedores (migraciones 0027 y 0028 aplicadas)
- CI con `ruff check` limpio; `pytest` tiene 3 fallos pre-existentes no relacionados con el Core ETL
- Identidad centralizada parcialmente implementada (esquema físico y gobierno de atributos personales pendientes)

---

## Decisiones arquitectónicas aceptadas

- PostgreSQL es la fuente central de verdad
- Cada proveedor tiene staging independiente y trazable
- Ningún proveedor escribe directamente en tablas Core
- Credenciales y API keys no se almacenan en Git
- Las integraciones deben poder reprocesarse (idempotencia)
- Identidad centralizada usa CLIENTE con identificador interno, matching conservador y merge reversible (ADR-001)
