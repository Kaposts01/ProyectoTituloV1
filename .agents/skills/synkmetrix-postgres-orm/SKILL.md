---
name: synkmetrix-postgres-orm
description: Disenar o corregir persistencia PostgreSQL, consultas SQLAlchemy, transacciones, indices y migraciones Alembic de SynkmetriX. Usar cuando cambian esquema o acceso a datos; no decidir matching de personas ni ejecutar mantenimiento destructivo por defecto.
---

# SynkmetriX · Persistencia

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Mapa de trabajo

Lee el modelo afectado, sus consultas, `app/db/session.py`, `alembic/env.py` y las migraciones relacionadas. Para semantica de entidades, consulta `docs/data/centralized-model.md`, arquitectura vigente y ADR-001. El diseno conceptual de identidad se rige por `.opencode/skills/data-modeling/SKILL.md`; cargalo cuando corresponda.

## Decisiones de persistencia

- Modela identidad del hecho y pertenencia antes de elegir UNIQUE. RUT, email y telefono pueden repetirse: una restriccion por valor personal puede perder asociaciones aunque el insert sea idempotente.
- Preserva claves de origen, cuenta y tipo de recurso. No conviertas coincidencias ambiguas en FK tomando arbitrariamente el primer registro. Un caso sin evidencia puede requerir null o revision, no una relacion inventada.
- Comprueba tipos de monto, precision, redondeo y zona horaria de extremo a extremo. Usa restricciones para invariantes aprobadas, no para decisiones pendientes.
- Define la unidad atomica: que confirma, que revierte y que queda durable ante fallo. Identifica commits internos, savepoints, efectos de autoflush y estado de sesion tras una excepcion.
- Detecta N+1 y cargas completas antes de optimizar. Mide conteo de consultas o plan representativo y propone indices por predicados, joins, orden y selectividad; evita indices duplicados.
- Define orden estable al paginar. Los filtros y el orden deben aplicarse antes de offset/limit, con desempate apropiado.
- En upserts revisa columnas actualizables, null, filas repetidas dentro del lote y limite de parametros. No informes filas insertadas como total existente ni como cobertura de origen.

## Migraciones

Agrega una revision nueva; verifica la cadena y metadata, incluyendo imports de modelos en `alembic/env.py`. Revisa manualmente el autogenerado: una diferencia no autoriza drop/recreate. Para datos existentes, plantea expansion, backfill y restricciones en etapas si el volumen o compatibilidad lo requieren. No ejecutes upgrade, downgrade, backfill ni EXPLAIN ANALYZE mutante sobre una base operativa como prueba.

## Validacion y entrega

Usa una base PostgreSQL de pruebas aislada para constraints, JSONB, upserts y concurrencia; SQLite no demuestra equivalencia. Comprueba upgrade desde el estado anterior y que metadata no proponga operaciones inesperadas. Evalua downgrade solo cuando sea seguro y este dentro del alcance. Entrega esquema, compatibilidad, impacto de bloqueo y evidencia medida.

Consulta [casos de revision](references/review.md) para cambios de integridad o rendimiento.
