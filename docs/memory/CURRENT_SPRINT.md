# Sprint Actual

> **La fuente de verdad del plan y del estado es [docs/tasks.md](../tasks.md).** Este archivo ya no mantiene un backlog propio.

## Sprint activo: S6 (2026-11-06 a 2026-11-13)

**Plan fiel, producción segura y pedidos finales a terceros.** Detalle, tareas y definición de hecho en [tasks.md, sección 3.10](../tasks.md#310-s6-plan-fiel-producción-segura-y-pedidos-finales-a-terceros-2026-11-06-a-2026-11-13).

- Equipo: DOC-12 y DOC-13 (reconciliación del plan y del handoff, PR #9), BCK-01a (respaldo local, PR #8), L8-QA (hallazgos del QA del sandbox del 2026-11-05 y SEC-03, PR #10; los bajos QA-17 a QA-30 quedan para otro lote), SEC-01 (inventario de datos personales), TER-01 (pedidos finales a terceros), SYNC-01, TK-PAR-04 (dry-run), DOC-14 (esqueleto de la memoria).
- Usuario: ventana de despliegue OPS-11 (respaldo, migración `0071` en `crm`, `seed_roles.py`, rotar el JWT, reinicio, recarga de TCH, backfill de Toku, SMTP), usuarios por rol, mover el reporte con nombres (D40), enviar los pedidos a terceros, decidir QA-04 (datos personales reales en `crm_sandbox`, ficha d163) y definir `SANDBOX_AUTH_JWT_SECRET` antes de reiniciar el sandbox con el PR #10.
- Siguen: S7 (2026-11-14 a 2026-11-21, congelamiento de código al cierre) y S8 (hasta la entrega a fines de noviembre). Ver [tasks.md, secciones 3.9 a 3.12](../tasks.md#39-plan-post-mvp-calendario-y-reglas).

## Dónde está cada cosa

- Tablero de sprints y líneas de trabajo: [tasks.md, sección 2](../tasks.md#2-tablero-resumen).
- Backlog con estado por tarea: [tasks.md, sección 4](../tasks.md#4-backlog-por-área); tareas de la auditoría del 2026-10-29 en la sección 4.14.
- Bloqueos y decisiones: [tasks.md, sección 5](../tasks.md#5-bloqueos-y-decisiones-abiertas).
- Olas 1 a 7 e integración en `master`: [tasks.md, sección 3.8](../tasks.md#38-olas-1-a-7-2-al-4-de-noviembre-e-integración-en-master).
- Retrospectivas y notas de sesión: [tasks.md, sección 7](../tasks.md#7-historial-y-retrospectivas).
- Cómo cerrar un sprint, flujo por sesión y chequeo de desfase: [tasks.md, reglas de uso](../tasks.md#14-reglas-de-uso).
- Cómo levantar los ambientes, banderas, riesgos e incidentes: [handoff.md](../../handoff.md).

## Regla para quien edite

No agregar tareas ni estados aquí: se actualiza la fila en `docs/tasks.md`. Al cambiar de sprint, actualizar solo el bloque «Sprint activo». El contexto técnico general sigue en [PROJECT_STATE.md](PROJECT_STATE.md).
