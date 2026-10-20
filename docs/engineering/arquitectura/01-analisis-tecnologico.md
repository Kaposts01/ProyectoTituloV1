# Análisis Tecnológico — SynkmetriX

**Última actualización:** 2026-10-20
**Ítems cubiertos:** 1 (análisis cualitativo/cuantitativo) y 2 (herramientas, lenguajes, componentes)

---

## 1. Stack tecnológico completo

### Backend

| Tecnología | Versión | Rol | Justificación |
|------------|---------|-----|---------------|
| **Python** | 3.14.5 | Lenguaje principal del servidor | Ecosistema maduro para ETL (pandas, openpyxl), tipado estático progresivo, amplio soporte de librerías para APIs y bases de datos. |
| **FastAPI** | ≥0.115 | Framework HTTP / API REST | Tipado nativo con Pydantic, generación automática de OpenAPI, soporte async, rendimiento superior a Flask/Django para cargas I/O bound. |
| **SQLAlchemy** | ≥2.0 | ORM / acceso a base de datos | ORM maduro con soporte para Mapped/mapped_column (estilo 2.0), generación de queries seguras, integración directa con Alembic. |
| **Alembic** | ≥1.16 | Migraciones de esquema | Versionado explícito del esquema, integrado con SQLAlchemy, revisión y rollback controlado. |
| **uvicorn** | ≥0.34 | Servidor ASGI | Servidor de producción para FastAPI; soporte para `--workers` en producción, bajo overhead. |
| **psycopg** (v3) | ≥3.2 | Driver PostgreSQL | Driver moderno con soporte async nativo, binary protocol, reemplaza psycopg2. |
| **PyJWT** | ≥2.10 | Autenticación JWT | Generación y validación de tokens JWT; usado para sesiones stateless del CRM. |
| **pwdlib [argon2]** | ≥0.2 | Hash de contraseñas | Argon2 es el algoritmo ganador de PHC 2015; recomendado sobre bcrypt/scrypt para nuevas implementaciones. |
| **httpx** | ≥0.28 | Cliente HTTP async | Usado en connectors para llamadas a APIs de proveedores; soporte async/sync, retry configurable, reemplaza requests. |
| **pydantic-settings** | ≥2.10 | Configuración desde env | Tipado estático para variables de entorno, validación automática, compatible con `.env`. |
| **APScheduler** | ≥3.10 | Scheduler de tareas | Orquesta sincronizaciones programadas sin infraestructura externa (no requiere Celery/Redis para este volumen). |
| **pandas** | ≥2.2 | Procesamiento de datos tabulares | Usado exclusivamente para ETL de archivos Excel TCH; manejo de DataFrames, tipos de datos heterogéneos. |
| **openpyxl** | ≥3.1 | Lectura de archivos Excel | Backend de pandas para `.xlsx`; lectura de reportes TCH con múltiples hojas y formatos variables. |
| **email-validator** | ≥2.2 | Validación de emails | Validación RFC-compliant de emails en Pydantic models. |
| **ruff** | ≥0.11 | Linter + formatter | Linter y formatter en un solo binario (Rust), reemplaza flake8+isort+black, 10-100× más rápido. |
| **pytest** | ≥8.3 | Testing | Framework de testing estándar; usado con fixtures, markers y conftest para tests de integración con PostgreSQL. |

### Base de datos

| Tecnología | Versión | Rol | Justificación |
|------------|---------|-----|---------------|
| **PostgreSQL** | 17 | Base de datos principal | Fuente central de verdad. JSONB nativo para payloads saneados, índices parciales, UNIQUE constraints compuestos, soporte para UUID. |
| **Docker** | — | Contenedor del CRM PostgreSQL (desarrollo) | Aislamiento del entorno de base de datos; imagen `postgres:17-alpine`. Datos persistidos en volumen Docker. |

### Frontend

| Tecnología | Versión | Rol | Justificación |
|------------|---------|-----|---------------|
| **React** | 18+ | Framework UI | Ecosistema estándar para SPAs; componentes reutilizables, hooks, compatibilidad con Recharts. |
| **TypeScript** | — | Tipado del frontend | Detección de errores en tiempo de compilación, contratos explícitos entre componentes y llamadas API. |
| **Vite** | — | Build tool + dev server | Build moderno con HMR, bundling eficiente, proxy hacia FastAPI en desarrollo. |
| **Recharts** | — | Gráficos y dashboards | Librería de charts basada en React/D3; usada para KPIs, series temporales y distribuciones en dashboards. |
| **oxlint** | — | Linter frontend | Linter rápido compatible con ESLint, basado en Rust. |

---

## 2. Análisis cualitativo del stack

### Fortalezas

- **Tipado end-to-end:** Pydantic en FastAPI + TypeScript en React permiten detectar inconsistencias entre contratos API y UI en tiempo de desarrollo.
- **Separación de capas estricta:** connectors → staging → ETL → core → API; ningún proveedor escribe directamente en tablas Core.
- **Idempotencia por diseño:** clave `(source, resource_type, external_id)` en `source_records`; todas las sincronizaciones son re-ejecutables sin duplicados.
- **Sin dependencias de infraestructura externa:** APScheduler evita Celery/Redis para el volumen actual (~332k registros, 4 proveedores); todo corre en un único proceso uvicorn.

### Deuda técnica conocida

| Área | Deuda | Impacto |
|------|-------|---------|
| Frontend | Estado, dashboards y exploradores concentrados en `App.tsx` | Mantenibilidad media; refactor pendiente |
| Identidad | `core_client_attributes` + `client_match_candidates` sin UI de revisión | Match cross-canal incompleto sin herramienta de merge |
| TCH | Solo carga Excel; no tiene API ni webhook | Dependencia manual de reportes periódicos |
| Consolidación | `channel_consolidation.py` y `crm_materialization.py` coexisten | Transición incompleta; riesgo de lógica divergente |

### Análisis cuantitativo

| Métrica | Valor | Fuente |
|---------|-------|--------|
| Registros TCH | ~1.47M pagos materializados | PROJECT_STATE.md |
| Suscripciones Toku | 112 con estado `deleted_at_source` | PROJECT_STATE.md |
| Archivos de tests | 20 | `find tests/` |
| Modelos SQLAlchemy | 16 | `find app/models/` |
| Servicios | 20 | `find app/services/` |
| Rutas API | ~30+ endpoints | `find app/api/` |
| Migraciones Alembic | 31 | `find alembic/versions/` |
| Proveedores activos | 4 (VirtualPOS, Toku, Payku, TCH) | CLAUDE.md |

---

## 3. Decisiones tecnológicas clave

| Decisión | Alternativa descartada | Razón |
|----------|------------------------|-------|
| FastAPI sobre Django REST | Django REST Framework | Django agrega overhead de ORM propio y admin que no se usa; FastAPI es más directo para una API pura. |
| SQLAlchemy 2.0 sobre SQLModel | SQLModel | SQLModel es una capa delgada sobre SQLAlchemy; usar directamente SQLAlchemy 2.0 evita la indirección y es más estable. |
| APScheduler sobre Celery | Celery + Redis | El volumen actual no justifica un broker externo; APScheduler in-process es suficiente y elimina una dependencia de infraestructura. |
| psycopg3 sobre psycopg2 | psycopg2 | psycopg3 soporta async nativo y binary protocol; psycopg2 está en mantenimiento. |
| Mermaid en Markdown | draw.io / Confluence | Los diagramas viven con el código, renderizan en GitHub sin herramientas adicionales, y se versiona con git. |

---

*Documento generado como parte de la Fase 1 — Arquitectura base.*
*Actualizar cuando cambie una dependencia mayor o se tome una decisión de stack.*
