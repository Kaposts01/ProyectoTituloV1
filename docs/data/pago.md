# Pago y Cobro Programado

## Modelo conceptual

**Status: Proposed**

COBRO_PROGRAMADO / CUOTA representa una obligacion o intento esperado. PAGO / TRANSACCION representa un movimiento o resultado reportado por una fuente. Su relacion debe conservar evidencia de origen y no asumirse por semejanza de atributos.

## Estado observado

**Status: Accepted**

El modelo desplegado distingue cargos de pagos cuando el proveedor entrega ambas entidades. Los enlaces se conservan solo cuando hay identificador o contexto verificable.

## Riesgo

**Status: Accepted**

No todo pago puede vincularse a una suscripcion o cargo. VirtualPOS mantiene pagos historicos sin cargo local confirmado; vease [tasks.md](../tasks.md).
