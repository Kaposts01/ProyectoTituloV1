# Modelo Centralizado

**Status: Proposed**

El Core debe ser independiente de proveedor y preservar la trazabilidad hacia staging y los identificadores externos.

| Concepto | Responsabilidad conceptual |
| --- | --- |
| CLIENTE | Entidad interna de socio o donante. |
| SUSCRIPCION | Relacion recurrente de un cliente con un plan o compromiso. |
| COBRO_PROGRAMADO / CUOTA | Obligacion o intento planificado de cobro. |
| PAGO / TRANSACCION | Resultado o movimiento informado por una fuente. |
| LIQUIDACION | Agrupacion financiera pendiente de contrato comun. |
| PLAN | Oferta o programa recurrente. |
| PLATAFORMA | Fuente, proveedor o canal de procedencia. |
| LOG_API | Evidencia operativa de interacciones y procesos, sin secretos. |

## Identidad centralizada

**Status: Accepted**

CLIENTE usa un identificador interno estable. Las identidades externas de persona se relacionan de forma extensible con CLIENTE, su fuente y el registro de staging que las respalda; `provider + external_id` es unico dentro de su espacio de nombres de identidad. RUT, email y telefono son atributos personales y senales de comparacion, no claves transversales unicas.

Normalizacion, matching, deduplicacion y merge son procesos distintos. Solo una identidad externa ya conocida se asocia automaticamente en el flujo inicial; las coincidencias transversales basadas en atributos personales requieren revision manual. Los merges son manuales, auditados y reversibles; no eliminan source records ni valores de origen. Vease [ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md).

## Estado actual observado

**Status: Accepted**

El modelo desplegado conserva entidades por origen con claves que incluyen fuente e identificador externo. `source_records` respalda la trazabilidad mediante payloads saneados.
