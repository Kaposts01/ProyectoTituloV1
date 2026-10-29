---
name: synkmetrix-etl-pandas
description: Desarrollar o corregir ETL de SynkmetriX, importaciones Excel TCH con Pandas/openpyxl y materializacion desde staging o tablas de canal al Core. Usar para transformacion, saneamiento, idempotencia y cobertura; no para autenticacion HTTP ni matching de personas.
---

# SynkmetriX · ETL y Excel

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Preparacion de la carga

Lee `scripts/etl_tch.py`, `app/services/core_*_etl.py` o la materializacion afectada y sus pruebas. Distingue carga a proyeccion de canal, consolidacion operativa anterior y Core: completar una no certifica las otras. Revisa `.opencode/skills/provider-integration/SKILL.md` si cambia adquisicion o Raw y `.opencode/skills/data-modeling/SKILL.md` si cambia semantica de entidades.

## Transformacion y calidad

- Inspecciona nombres de hojas, dimensiones, cabeceras y tipos sin imprimir filas personales ni datos de cuenta. Detecta extensiones mayusculas y variantes soportadas antes de inferir que una carpeta esta vacia.
- Define columnas obligatorias, opcionales y manejo de filas invalidas. No continúes silenciosamente con un dataset vacio por un fallo de lectura o envelope no reconocido.
- Conserva valores de origen y su procedencia cuando corresponda; sanea antes de persistir. Una extension .xlsx o MIME declarado no valida el contenido: considera estructura ZIP y limites del importador existente.
- Especifica formatos chilenos de miles/decimales, nulos y fechas. Distingue cero de ausente; no trunques hora o precision monetaria sin que el contrato lo justifique.
- La normalizacion no decide identidad. No uses primer RUT coincidente ni email compartido para vincular hechos ambiguos. Registra o conserva la falta de evidencia.
- Define clave natural de cada hecho y precedencia entre ventanas que repiten historia. Incluye intentos distintos cuando el modelo los distinga; el nombre temporal del archivo no debe crear hechos nuevos.
- Controla lotes segun numero de parametros, memoria y volumen real. Un iterrows o carga completa no es un error automatico: cambia el enfoque cuando medicion y tamanos lo justifiquen.
- Define atomicidad de full, incremental y etapas de Core. Un modo full no autoriza vaciar una proyeccion operativa; revisa alcance, respaldo y recuperacion antes de ejecutarlo.
- Registra corrida, archivo o fuente, resultados, exclusiones y errores saneados. Diferencia filas leidas, rechazadas, insertadas, actualizadas y total existente; un upsert sin cambios no significa base vacia.

## Validacion y entrega

Prueba transformaciones con ejemplos sinteticos y persistencia en PostgreSQL aislado cuando corresponda. Verifica una segunda ejecucion sin duplicados, relaciones, formatos invalidos y rollback ante un fallo intermedio. Antes de repetir una carga real, consulta corridas activas, procedencia y cobertura existente. Entrega conteos reconciliados y limites; no certifiques historia completa solo porque una corrida termino.

Consulta [casos de revision](references/review.md) para importaciones o cambios en claves de hechos.
