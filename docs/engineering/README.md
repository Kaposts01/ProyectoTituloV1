# Documentación de Ingeniería — SynkmetriX

Documentación técnica formal del proyecto. Organizada por fase según el plan aprobado 2026-10-20.

## Estructura

```
docs/engineering/
├── arquitectura/          ← Fase 1: Arquitectura base
│   ├── 01-analisis-tecnologico.md   (ítems 1 y 2)
│   ├── 02-bpmn-tecnico.md           (ítem 3 — flujos del sistema)
│   ├── 03-bpmn-operacional.md       (ítem 3 — flujos del operador)
│   ├── 04-diagrama-componentes.md   (ítem 5)
│   └── 05-diagrama-arquitectura.md  (ítem 9)
├── datos/                 ← Fase 2: Modelo de datos y comunicaciones
│   ├── 06-modelo-datos.md           (ítem 6)
│   ├── 07-topologia-comunicaciones.md (ítem 7)
│   ├── 08-diagrama-infraestructura.md (ítem 8)
│   ├── 09-analisis-contratos-api.md (análisis comparativo VP/Toku/Payku — verificado contra BD)
│   ├── 10-analisis-contratos-tch.md (análisis Excel TCH — modelo, gaps y mapeo a staging)
│   └── 11-conciliacion-canales.md   (conciliación reportes vs BD: VP, Toku, Payku, TCH — 2026-10-20)
├── calidad/               ← Fase 3: Casos de uso, plan de pruebas, estándares
│   ├── 11-casos-de-uso.md           (ítem 4)
│   ├── 12-plan-pruebas.md           (ítem 12)
│   └── 13-estandares.md             (ítem 13)
└── operaciones/           ← Fase 4: KPIs, SLAs, disponibilidad, continuidad, mantención
    ├── 14-kpis.md                   (ítem 10)
    ├── 15-slas.md                   (ítem 11)
    ├── 16-disponibilidad.md         (ítem 14)
    ├── 17-continuidad.md            (ítem 15)
    └── 18-mantencion.md             (ítem 16)
```

## Estado por fase

| Fase | Ítems | Estado |
|------|-------|--------|
| 1 — Arquitectura base | 1, 2, 3, 5, 9 | ✅ Completa |
| 2 — Datos y comunicaciones | 6, 7, 8 + análisis de canales | ✅ Completa |
| 3 — Calidad | 4, 12, 13 | ✅ Completa |
| 4 — Operaciones | 10, 11, 14, 15, 16 | ✅ Completa |

## Convenciones

- Diagramas: Mermaid embebido en Markdown (renderizan en GitHub y VS Code).
- Cada documento incluye fecha de última actualización.
- Los cambios de arquitectura que invalidan un documento aquí deben actualizarlo en el mismo commit.
