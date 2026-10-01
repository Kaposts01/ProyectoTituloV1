# Lecciones Aprendidas

**Status: Accepted**

- Preservar payloads saneados permite trazabilidad sin retener datos de tarjeta.
- La idempotencia debe depender de claves de origen estables y no de campos mutables.
- Una confirmacion remota no debe marcarse como completada si falla la persistencia local; requiere reconciliacion.
- No se deben inferir relaciones entre pagos, cargos y suscripciones sin una clave o contexto verificable.
- Los documentos historicos de datos y ETL deben separarse de la arquitectura desplegada.
- El RUT, email y telefono son evidencia potencial de identidad, no una regla automatica de merge.
- La configuracion de Context7 para OpenCode y Claude es independiente; deben mantenerse de forma consciente para evitar divergencias.
