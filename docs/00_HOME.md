# CRM de Socios y Donantes

El repositorio es un vault portable de Obsidian. `docs/` contiene la documentacion tecnica fuente de verdad y `knowledge/` aporta navegacion y relaciones de alto nivel. Las preferencias locales de Obsidian no se versionan.

## Navegacion

- [Producto](product/vision.md)
- [Arquitectura](architecture/overview.md)
- [Modelo de datos centralizado](data/centralized-model.md)
- [Integraciones](integrations/virtualpos.md)
- [Decisiones](decisions/README.md)
- [Estado del proyecto](memory/PROJECT_STATE.md)
- [Sprint actual](memory/CURRENT_SPRINT.md)
- [Bloqueos](memory/BLOCKERS.md)
- [Lecciones aprendidas](memory/LESSONS_LEARNED.md)
- [Sesiones](sessions/README.md)

## Estado observado

El repositorio ya implementa un CRM interno con FastAPI, PostgreSQL y React/Vite. Centraliza datos de VirtualPOS, Toku, Payku y TCH mediante staging y entidades por canal. Esta documentacion organiza el conocimiento existente; no introduce cambios de backend, frontend, base de datos ni integraciones.

## Referencias existentes

- [Tareas historicas](tasks.md)
- [Arquitectura anterior](history/architecture/observed-architecture-pre-reorg.md)
- [Plan de consolidacion cerrado](history/migrations/bdlocales-consolidation-closed.md)
- [Investigacion historica de VirtualPOS](history/integrations/virtualpos-appscript-research.md)
- [Plan ETL TCH historico](history/tch/2026-09-etl-plan.md)
- [Colecciones Postman](reference/postman/)

## Uso en Obsidian

1. En Obsidian, seleccione **Open folder as vault** y elija la raiz del repositorio.
2. Abra `docs/00_HOME.md` como punto de entrada tecnico o `knowledge/00 - Home/SynkmetriX.md` para la navegacion de alto nivel.
3. Los enlaces Markdown son compatibles con Obsidian y GitHub; `.obsidian/` permanece local.

Comprobacion local: Obsidian esta instalado y el protocolo `obsidian://` esta registrado en Windows.
