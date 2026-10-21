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

## Identidad centralizada

**Status: Parcialmente implementado** (ver [ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md))

El modelo Core incluye `core_clients`, `ExternalIdentity`, `CoreClientAttribute` y `ClientMatchCandidate`. La deteccion de candidatos de match cross-canal esta operativa. Pendiente: flujo de revision/confirmacion manual y merge reversible de identidades (CORE-04).

## Limite actual

**Status: En progreso**

La identidad centralizada esta parcialmente implementada (modelo fisico completo, matching conservador activo). Faltan: gobierno de atributos personales, taxonomia transversal de estados/montos, separacion de entornos Sandbox/QA/Produccion (ENV-01), y flujo de resolucion de candidatos (CORE-04).

## Documentos relacionados

- [Flujo de datos](data-flow.md)
- [Base de datos](database.md)
- [Integraciones](integrations.md)
- [Seguridad](security.md)
