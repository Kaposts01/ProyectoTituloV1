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
├── calidad/               ← Fase 3: Casos de uso, plan de pruebas, estándares
└── operaciones/           ← Fase 4: KPIs, SLAs, disponibilidad, continuidad, mantención
```

## Estado por fase

| Fase | Ítems | Estado |
|------|-------|--------|
| 1 — Arquitectura base | 1, 2, 3, 5, 9 | ✅ Completa |
| 2 — Datos y comunicaciones | 6, 7, 8 | ✅ Completa |
| 3 — Calidad | 4, 12, 13 | Pendiente |
| 4 — Operaciones | 10, 11, 14, 15, 16 | Pendiente |

## Convenciones

- Diagramas: Mermaid embebido en Markdown (renderizan en GitHub y VS Code).
- Cada documento incluye fecha de última actualización.
- Los cambios de arquitectura que invalidan un documento aquí deben actualizarlo en el mismo commit.
