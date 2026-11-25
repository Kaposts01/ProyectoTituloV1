# ADR-002 — Motor de rechazos asistido y separado de operaciones

Date: 2026-11-24

Status: Proposed

## Contexto

El documento aportado por el usuario propone sustituir un agente LLM/vLLM por reglas y ML clasico en CPU. El CRM ya tiene catalogos por canal, Core y recuperadores con permisos. Se autoriza esta primera entrega de definiciones y auditoria, no implementacion ni entrenamiento.

La auditoria de la copia QA 0082 encuentra Core y eventos vacios; solo TCH aporta 2.094 motivos, reducidos a diez combinaciones normalizadas, sin etiquetas revisadas. El seguimiento de reintentos del codigo usa cuatro dias, no el horizonte propuesto de 30. No existe evidencia local para elegir un algoritmo o estimar recuperacion.

## Decision propuesta

1. Separar P1 (motivo), P2 (probabilidad observacional de pago de la misma obligacion a 30 dias) y politica de acciones autorizadas. P1 puede entregarse sin P2.
2. Mantener arquitectura de datos centralizados, catalogos y contratos. El motor no consulta ni escribe proveedores; solo informa. Estados, permisos y banderas WR prevalecen sobre la recomendacion.
3. Priorizar reglas y abstencion explicita. No forzar una categoria de emisor cuando falta evidencia ni inventar porcentajes o fechas de reintento.
4. Considerar ML clasico CPU como candidato; decidir solo tras datos aptos, benchmark temporal y revision de costos/riesgos. Conservar funcionamiento sin artefacto activo. No agregar GPU ni otro servicio sin necesidad medida.
5. Mantener trazabilidad de evidencia/episodio, fuente/cuenta, dataset, corte, variables, ambos modelos, reglas, politica y revisiones humanas; asegurar idempotencia aun sin modelos.
6. Separar entrenamiento y promocion. Banderas apagadas, modo sombra, activacion humana inicial y rollback antes de un piloto con ejecutivos.

## Alternativas y consecuencias

- **Catalogos solos:** menor mantenimiento y referencia obligatoria. Pueden bastar en glosas repetitivas; no extrapolan probabilidad de recuperacion.
- **Reglas + modelos CPU:** opcion propuesta para probar si agregan valor. Exige anotacion, cobertura y vigilancia; no garantiza mejoras frente a reglas.
- **LLM/vLLM o embeddings:** no justificados ahora por el alcance, datos y operacion disponibles. No se concluye inferioridad universal ni se usa una matriz teorica como benchmark.

La interpretabilidad ayuda a revisar resultados pero no acredita cumplimiento legal. Datos enlazables y texto libre siguen requiriendo gobierno, acceso y retencion. El texto normativo debe revisarse segun su vigencia y contexto; no decide una libreria ni algoritmo.

## Condiciones de aceptacion futuras

Revision explicita del objetivo y de pagos parciales/reversos/mandatos; fuente QA representativa y episodio trazable; privacidad, criterios de seleccion, presupuesto operativo y permisos acordados. Evaluacion de datos y de modelos son hitos diferentes. Esta ADR no se marca Accepted por haber escrito el plan ni porque el usuario autorizo auditar.

## Evidencia

- [Plan revisado](../planning/ml-rechazos/PLAN.md) y [definiciones](../planning/ml-rechazos/DEFINICIONES.md).
- [Auditoria y limites](../planning/ml-rechazos/QA-2026-11-24.md).
- [Estado de tareas ML](../tasks.md#417-motor-de-rechazos-definiciones-y-viabilidad-2026-11-24).
