# Memoria de título: índice y estado (DOC-14)

> **Estado:** esqueleto creado en S6 (2026-11-10). Borradores revisables de los capítulos 4 y 5.
> **Fuente del plan:** `docs/tasks.md`, fila DOC-14 y §3.9 a §3.12 (línea continua de memoria: S6 arquitectura y datos;
> S7 calidad y resultados; S8 limitaciones, trabajo futuro y cierre).
> **Formato:** pendiente de confirmar con la universidad (DEC-42). Mientras tanto se redacta en Markdown, en español, con
> tono académico; la conversión al formato oficial (plantilla, citas, numeración de figuras) se hace en S8.
> **Regla:** ningún capítulo incluye datos personales (nombres, RUT, correos, teléfonos, tarjetas ni identificadores
> reales de socios), llaves ni valores del `.env`. Las cifras agregadas se citan con su fuente. Lo dudoso se marca
> **[verificar]**.

## Capítulos

| N.º | Capítulo | Sprint | Estado | Archivo | Fuentes principales |
| --- | --- | --- | --- | --- | --- |
| 1 | Introducción y problema | S6 (esbozo) / S8 | Pendiente | — | `README.md`, `docs/product/`, `docs/memory/PROJECT_STATE.md` |
| 2 | Objetivos (general y específicos) | S8 | Pendiente | — | `docs/tasks.md` §1 y §3 |
| 3 | Estado del arte (CRM para organizaciones sin fines de lucro, integración de pasarelas de pago, ETL e idempotencia) | S8 | Pendiente | — | Bibliografía por reunir |
| 4 | Arquitectura del sistema | S6 | **Borrador** | [04-arquitectura.md](04-arquitectura.md) | `docs/architecture/`, `app/`, `frontend/` |
| 5 | Modelo de datos e integración por canal | S6 | **Borrador** | [05-modelo-datos-integracion.md](05-modelo-datos-integracion.md) | `docs/data/`, `docs/integrations/`, `app/models/`, ADR-001 |
| 6 | Sincronización y calidad de datos | S7 | Pendiente | — | `docs/data/sync-idempotency.md`, `docs/data/status-history.md`, SYNC-01, auditoría del 2026-10-29 |
| 7 | Seguridad y datos personales | S7 | Pendiente | — | `docs/architecture/security.md`, SEC-01, SEC-02, SEC-03 |
| 8 | Operación (despliegue local, respaldo, alertas) | S7 | Pendiente | — | `docs/operations/`, BCK-01a, OPS-11, d155, d156 |
| 9 | Validación con usuarios y métricas | S7 | Pendiente | — | MET-01, MET-02, MET-03 (SUS), d159, d160 |
| 10 | Resultados | S7 / S8 | Pendiente | — | MET-01 a MET-03, informes de QA, paridad por canal |
| 11 | Limitaciones y trabajo futuro (terceros sin respuesta, hosting d155) | S8 | Pendiente | — | `docs/operations/ter-01-pedidos.md`, corte d154, ENV-01, BCK-01 con PITR |
| 12 | Conclusiones | S8 | Pendiente | — | Todo lo anterior |

Anexos previstos: glosario de estados por canal, catálogo de códigos de error de la API, diagrama entidad-relación,
guion de las sesiones con usuarios y cuestionario SUS, y registro de decisiones (ADR y familia DEC).

## Convenciones de redacción

- Se cita el código con su ruta relativa al repositorio (por ejemplo, `app/services/channel_consolidation.py`) y, cuando
  aplica, la migración de Alembic o la decisión (ADR, DEC-xx, ficha dxxx) que lo respalda.
- Los nombres de tablas, columnas y endpoints van en formato de código; los conceptos del dominio, en español.
- Las afirmaciones sobre el comportamiento de un proveedor distinguen entre lo **documentado** por el proveedor, lo
  **observado** en sandbox y lo **inferido**; esto último se marca [verificar].
- Las cifras del sistema en operación (conteos, tiempos) se toman de informes ya versionados y se redondean.

## Pendientes de forma

- Confirmar con la universidad la plantilla, la extensión máxima y el estilo de citas [verificar].
- Decidir si los diagramas se generan como figuras (SVG o PNG) a partir de los bloques de texto de cada capítulo.
- Revisar en S8 la coherencia de términos entre capítulos (socio, donante, cliente; cobro, cargo, cuota).
