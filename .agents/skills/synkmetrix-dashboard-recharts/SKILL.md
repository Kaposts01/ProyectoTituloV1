---
name: synkmetrix-dashboard-recharts
description: Implementar, revisar o corregir dashboards Recharts y reportes de SynkmetriX cuando importan definicion de KPI, periodos, cobertura y agregacion entre canales. No usar para estilos generales o navegacion sin cambios de datos o metricas.
---

# SynkmetriX · Dashboards

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Mapa y contrato de una metrica

Lee el calculo backend en `app/api/v1/routes/staging.py`, `tch.py` o `reports.py`, y su consumo en `frontend/src/AutomaticReport.tsx`, `App.tsx` o componentes de graficos. Consulta el contrato del proveedor afectado; no asumas que invoice, transaction y payment significan lo mismo entre canales.

Antes de cambiar un KPI, identifica evento o entidad contado, poblacion, filtros de estado, numerador, denominador, unidad, moneda, rango temporal, zona horaria, fecha de corte y cobertura conocida. Mantén esta definicion junto a la logica o documentacion que la gobierna.

## Integridad analitica

- Distingue stock al inicio/cierre de flujos de altas, bajas y cobros. Comprueba fronteras de dia/mes y exclusiones para no contar un evento dos veces.
- Distingue intento rechazado, compromiso de cobro, pago exitoso y liquidacion. No derives recaudacion real de suscripciones activas ni de una factura sin evidencia de pago.
- No agregues monedas distintas sin politica de conversion aprobada. Preserva exactitud en calculo y aplica formato/redondeo solo donde corresponda.
- Un mes sin datos disponibles no equivale a actividad cero. Expresa cobertura parcial y errores de carga; trata denominador cero como estado definido, sin infinito ni porcentajes enganosos.
- La agrupacion transversal de personas no se prueba por compartir RUT. Distingue entidades por origen y socios confirmados segun identidad centralizada aprobada.
- Para TCH revisa controles mensuales y detalle: su diferencia de granularidad debe explicarse y no sumarse duplicadamente. No publiques proyecciones o fechas futuras como recaudacion observada sin evidencia.
- Indicadores como churn, MRR y LTV requieren definicion de poblacion y formula explicita; una estimacion debe rotularse como tal y respetar limites de cobertura de la fuente.

## Presentacion y rendimiento

Conserva consistencia entre tarjetas, tablas, tooltips y filtros; etiquetas de unidad, estado y periodo deben ser visibles. Usa colores semanticos consistentes, alternativa tabular cuando sea necesaria y contenedores responsivos. Separa obtencion, agregacion y render; no recomputes grandes series en cada celda. Optimiza renders o carga diferida solo con una necesidad concreta.

## Validacion y entrega

Usa ejemplos sinteticos con limites de mes, estado terminal, valor cero, datos ausentes y cobertura parcial. Concilia al menos un total agregado con su fuente verificable sin exponer PII. Ejecuta checks del backend y/o frontend que cambien. Entrega formula, periodo, fuente y limites del indicador junto al resultado.

Consulta [casos de revision](references/review.md) para paridad entre canales o reportes de periodo.
