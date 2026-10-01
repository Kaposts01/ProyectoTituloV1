# Requisitos Documentados

## Principios

**Status: Accepted**

- PostgreSQL es la fuente central de verdad.
- Cada proveedor mantiene staging independiente.
- Ningun proveedor escribe directamente en tablas Core.
- Se preservan datos raw saneados cuando sea posible y toda transformacion debe ser trazable.
- Las integraciones deben poder reprocesarse de forma idempotente.
- Credenciales y API keys nunca se almacenan en Git.
- El Core debe ser independiente de la estructura particular de cada proveedor y permitir nuevos canales.

## Requisitos funcionales

**Status: Proposed**

- Centralizar informacion de clientes, suscripciones, cobros programados o cuotas, pagos, liquidaciones, planes y plataformas.
- Presentar consulta centralizada y reportes operativos, financieros y estrategicos.
- Mantener la gestion de suscripciones dentro de los flujos internos autorizados.
- Reservar una fase posterior para analitica predictiva.

## Restricciones de identidad

**Status: Accepted**

- No asumir que email, telefono o RUT siempre estan presentes.
- No asumir que un cliente tiene una sola suscripcion.
- No asumir que el RUT identifica automaticamente a una persona de forma transversal.

## Definiciones pendientes

**Status: TBD**

- Reglas de matching, deduplicacion y merge de clientes.
- Fuente de verdad para atributos personales, consentimiento y estado de donante.
- Taxonomia comun de estados, montos, monedas y periodicidad.
- Politicas de retencion, rectificacion y eliminacion de datos personales.
- Contrato transversal de liquidaciones.
