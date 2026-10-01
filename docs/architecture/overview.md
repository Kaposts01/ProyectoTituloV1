# Vision General de Arquitectura

## Arquitectura conceptual

**Status: Proposed**

```text
Fuentes externas
  -> Connectors
  -> Staging / Raw
  -> ETL / Normalizacion
  -> PostgreSQL Core
  -> API Backend
  -> CRM / Reportes / Analytics
```

El modelo separa adquisicion, datos de origen, transformacion y consumo. Los Connectors no deben acoplar a Core con estructuras especificas de proveedor.

## Estado actual observado

**Status: Accepted**

El repositorio usa FastAPI, PostgreSQL y React/Vite. VirtualPOS, Toku y Payku se sincronizan a staging; TCH carga reportes Excel. La API intermedia toda comunicacion con proveedores y el navegador no recibe credenciales.

## Limite actual

**Status: TBD**

No hay identidad unica de socio o donante entre plataformas. El Core conceptual debe admitirla, pero sus reglas no estan aprobadas.

## Documentos relacionados

- [Flujo de datos](data-flow.md)
- [Base de datos](database.md)
- [Integraciones](integrations.md)
- [Seguridad](security.md)
