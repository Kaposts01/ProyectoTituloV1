# Diagrama de Infraestructura — SynkmetriX

**Última actualización:** 2026-10-20
**Ítem cubierto:** 8 (diagrama de infraestructura)

---

## Infraestructura actual — desarrollo local (estado operativo)

```mermaid
graph TD
    subgraph INTERNET["Internet"]
        VP_EXT[VirtualPOS API\nhttps://api.virtualpos.cl]
        TK_EXT[Toku API\nhttps://api.toku.cl]
        PK_EXT[Payku API\nhttps://app.payku.cl/api]
        GH[GitHub\nKaposts01/ProyectoTituloV1]
    end

    subgraph WINDOWS["Windows 11 Pro (máquina local)"]
        subgraph DOCKER["Docker Desktop"]
            PG_CTR["Contenedor: crm_projectotitulo-postgres-1\nImagen: postgres:17-alpine\nPuerto: 0.0.0.0:5433→5432\nRed: crm_projectotitulo_default"]
            PG_VOL[("Volumen Docker\ncrm_projectotitulo_postgres_data\nPersistencia durable")]
        end

        subgraph VENV["Python 3.14.5 venv (.venv)"]
            UVICORN["uvicorn\n127.0.0.1:8000\nFastAPI + APScheduler\nPID activo"]
        end

        subgraph NODE_ENV["Node.js"]
            VITE_DEV["Vite :5173\ndev server (desarrollo)\nProxy → :8000"]
            VITE_BUILD["vite build\n→ frontend/dist/\n(producción: servido por uvicorn)"]
        end

        ENV_FILE[".env\nAPI Keys\nDB credentials\nJWT secret\nWrites flags\n(no versionado)"]

        CI_LOCAL["CI local\nGitHub Actions\nruff + tsc + pytest"]
    end

    subgraph USER["Operador"]
        BROWSER["Navegador\nChrome / Firefox"]
    end

    BROWSER -->|"http://localhost:5173\n(dev)"| VITE_DEV
    VITE_DEV -->|"proxy /api/v1\nHTTP"| UVICORN
    BROWSER -->|"http://localhost:8000\n(directo, dev)"| UVICORN
    UVICORN -->|"psycopg3\nTCP localhost:5433"| PG_CTR
    PG_CTR --- PG_VOL
    UVICORN -->|"HTTPS + API Key"| VP_EXT
    UVICORN -->|"HTTPS + API Key"| TK_EXT
    UVICORN -->|"HTTPS + API Key"| PK_EXT
    ENV_FILE -.->|"pydantic-settings\nlectura al inicio"| UVICORN
    GH -->|"git pull/push"| WINDOWS
    CI_LOCAL -.->|"push trigger"| GH

    PG_CTR -.->|"crm DB\nmigraciones Alembic"| UVICORN

    style PG_VOL fill:#EAFAF1,stroke:#1E8449
    style ENV_FILE fill:#FEF9E7,stroke:#B7950B
```

---

## Infraestructura objetivo — producción (propuesta)

```mermaid
graph TD
    subgraph INTERNET["Internet"]
        USERS[Operadores\nnaveganadores]
        VP_P[VirtualPOS API]
        TK_P[Toku API]
        PK_P[Payku API]
        WH_P[Webhooks\nVP / Toku / Payku]
    end

    subgraph CLOUD["Servidor / Cloud (propuesto)"]
        subgraph LB["Reverse Proxy / CDN"]
            NGINX["nginx / Caddy\nHTTPS :443\nTerminación TLS\nSNI + certificado"]
        end

        subgraph APP["Servidor de aplicación"]
            UVICORN_P["uvicorn\n--workers N\nFastAPI + APScheduler\nBehind proxy"]
            STATIC["Archivos estáticos\nfrontend/dist/\nservidos por nginx"]
        end

        subgraph DB_PROD["Base de datos"]
            PG_PROD[("PostgreSQL 17\nInstancia dedicada\nBackup automático\nread replica (opcional)")]
        end

        ENV_PROD["Variables de entorno\nsistema operativo / secrets manager\nNo en disco como .env"]
    end

    USERS -->|"HTTPS :443"| NGINX
    NGINX -->|"reverse proxy\nHTTP interno"| UVICORN_P
    NGINX -->|"archivos estáticos"| STATIC
    UVICORN_P -->|"TCP psycopg3"| PG_PROD
    UVICORN_P -->|"HTTPS"| VP_P & TK_P & PK_P
    WH_P -->|"HTTPS POST /api/v1/webhooks/*"| NGINX
    ENV_PROD -.->|"lectura al inicio"| UVICORN_P

    style PG_PROD fill:#EAFAF1,stroke:#1E8449
    style ENV_PROD fill:#FEF9E7,stroke:#B7950B
```

---

## Inventario de servicios y recursos

### Servicios activos (desarrollo local)

| Servicio | Tecnología | Host:Puerto | Estado |
|---------|-----------|-------------|--------|
| API Backend | FastAPI + uvicorn | `127.0.0.1:8000` | Activo |
| Frontend dev | Vite | `localhost:5173` | Activo (dev) |
| Base de datos | PostgreSQL 17 (Docker) | `localhost:5433` | Activo |

### Recursos de datos

| Recurso | Tipo | Ubicación | Contenido |
|---------|------|-----------|-----------|
| Base de datos principal | PostgreSQL | Docker volumen `crm_projectotitulo_postgres_data` | Todas las tablas del CRM |
| Migraciones | Alembic | `alembic/versions/` | 31 revisiones — head: `20261020_0031` |
| Código fuente | Git | `C:\Users\Usuario\Downloads\CRM_projectoTitulo` | Repositorio local + GitHub |
| Variables de entorno | Archivo `.env` | Raíz del proyecto | API Keys, secretos, flags |
| Dependencias Python | `requirements.lock` | Raíz | Bloqueadas en Python 3.14.5 |
| Dependencias Node | `frontend/package.json` | `frontend/` | React, Vite, TypeScript |

---

## Diagrama de red local — detalle Docker

```mermaid
graph LR
    subgraph HOST["Host Windows (localhost)"]
        PROC_UV["PID uvicorn\n127.0.0.1:8000"]
        PROC_VITE["PID node/vite\n0.0.0.0:5173"]
        BIND["Puerto 5433\n0.0.0.0:5433"]
    end

    subgraph DOCKER_NET["Red Docker crm_projectotitulo_default"]
        PG_INT["postgres:17-alpine\n:5432 (interno)\nhostname: postgres"]
    end

    PROC_UV -->|"TCP 127.0.0.1:5433"| BIND
    BIND -->|"port mapping"| PG_INT
    PROC_VITE -->|"proxy HTTP\n/api/v1"| PROC_UV
```

---

## CI/CD actual

```mermaid
graph LR
    DEV[Desarrollador\ngit push] --> GH[GitHub\nmaster branch]
    GH --> CI[GitHub Actions]
    CI --> LINT[ruff check\napp tests alembic scripts]
    CI --> TSC[cd frontend &&\nnpx tsc --noEmit]
    CI --> TEST[PYTHONPATH=. pytest\n.venv/Scripts/pytest.exe]
    LINT & TSC & TEST --> RESULT{¿Pasó?}
    RESULT -->|Sí| MERGE[PR mergeable]
    RESULT -->|No| BLOCK[PR bloqueado]
```

**Estado del CI:** ruff pasa limpio; `pytest` tiene 3 fallos pre-existentes no relacionados con el Core ETL (2 en Toku sync mock, 1 en Payku consolidación histórica). Pendiente de resolución.

---

## Gaps infraestructurales conocidos

| Gap | Impacto | Prioridad |
|-----|---------|-----------|
| Sin URL HTTPS pública | Webhooks de proveedores no se pueden activar en producción | Alta |
| Sin backup automatizado | Pérdida de datos ante fallo de disco en local | Alta |
| Sin servidor de producción definido | No hay entorno de producción separado del de desarrollo | Media |
| APScheduler in-process | Pérdida de trabajos si uvicorn se reinicia durante una sync | Media |
| Sin monitoreo de uptime | No hay alertas si el servicio cae | Media |
| Sin rate-limit en API pública | Riesgo de abuso si se expone | Baja (hoy solo en local) |

---

*Documento generado como parte de la Fase 2 — Datos y comunicaciones.*
