# System Overview

## Arquitectura actual

Los canales API ingresan mediante conectores de backend; TCH ingresa desde reportes Excel. Los datos saneados se preservan en staging, pasan por tablas por canal y se consolidan para su consulta desde FastAPI y React/Vite.

```mermaid
flowchart LR
    VP[VirtualPOS API]
    TK[Toku API]
    PK[Payku API]
    TCH[TCH Excel]

    VP --> ING[Connectors y sincronizadores]
    TK --> ING
    PK --> ING
    TCH --> ETL[TCH ETL]
    ING --> RAW[source_records Raw/Staging]
    ETL --> CT[TCH tablas por canal]
    RAW --> CT[Tablas por canal]
    CT --> CON[Consolidacion]
    CON --> CRM[Entidades CRM iniciales]
    CRM --> API[FastAPI]
    API --> UI[React/Vite y reportes]
```

PostgreSQL es la fuente central de verdad. Los proveedores no escriben directamente en Core; la API intermedia las operaciones autorizadas. La identidad transversal unica entre plataformas sigue pendiente de implementacion tecnica.

## Referencias tecnicas

- [Vision de arquitectura](../../docs/architecture/overview.md)
- [Flujo de datos](../../docs/architecture/data-flow.md)
- [Base de datos](../../docs/architecture/database.md)
- [Integraciones](../../docs/architecture/integrations.md)
- [Seguridad](../../docs/architecture/security.md)
