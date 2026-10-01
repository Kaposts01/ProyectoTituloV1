# Integraciones

## Fuentes consideradas

**Status: Proposed**

| Fuente | Tipo | Situacion |
| --- | --- | --- |
| VirtualPOS | API | Canal existente. |
| Toku | API | Canal existente. |
| Payku | API | Canal existente. |
| TCH | Reportes Excel | Canal existente. |
| Google Sheets | Hoja o reporte | Fuente considerada; sin integracion confirmada. |

## Principios

**Status: Accepted**

Cada proveedor tiene staging independiente. Las credenciales solo viven en variables de entorno. La API interna intermedia operaciones y el navegador no llama directamente a proveedores.

## Limitaciones

**Status: Accepted**

Payku presenta limitaciones para recuperar parte de su historial de transacciones. VirtualPOS puede tener historial de cargos incompleto para algunas suscripciones.

Consulte las fichas de [VirtualPOS](../integrations/virtualpos.md), [Toku](../integrations/toku.md), [Payku](../integrations/payku.md) y [TCH](../integrations/tch.md).
