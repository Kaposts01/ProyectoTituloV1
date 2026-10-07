# Toku

Toku aporta clientes, suscripciones, metodos de pago, deudas y transacciones. Usa una clave de API solo en el backend; los sincronizadores aplican limites y reintentos para respuestas temporales.

Las operaciones mutables implementadas requieren `TOKU_WRITES_ENABLED=true`, permisos y proteccion CSRF. El navegador no llama a Toku directamente.

El dashboard usa las deudas para su actividad y las transacciones para resultados de pago. La comparación con suscripciones activas usa exclusivamente transacciones fechadas del canal, no facturas.

## Suscripciones eliminadas en el origen

El sync de Toku solo recupera suscripciones activas desde la API. Las suscripciones que fueron canceladas o eliminadas antes o entre ciclos de sincronización no aparecen en `tk_subscriptions`, pero sus invoices y pagos sí existen en el sistema del proveedor y se sincronizan a `tk_invoices` y `tk_payments`.

**Magnitud observada (2026-10-07):** 112 suscripciones distintas ausentes del staging generan 564 invoices `PAID` (todos con pago exitoso), cubriendo el rango 2024-10-09 a 2026-07-09.

**Opciones evaluadas para la materialización Core:**

- **Opción B (descartada):** Aceptar el gap. Materializar los 564 pagos con `charge_id=NULL` y `subscription_id=NULL`. Simple, pero deja pagos PAID sin trazabilidad financiera hacia ninguna suscripción ni cargo, lo que distorsiona cualquier reporte de recaudación por suscripción.

- **Opción A (elegida):** Crear un `CoreSubscription` stub por cada suscripción ausente con `status='deleted_at_source'` y `client_id=NULL`. Los campos de monto, fecha y cliente quedan en NULL porque no están disponibles. Esto permite mantener la cadena `payment→charge→subscription` y garantiza que los 564 pagos PAID aparezcan correctamente en reportes de recaudación. Los stubs pueden enriquecerse si en el futuro el sync se extiende para capturar suscripciones históricas canceladas mediante la API de Toku.

El ETL Core implementa esta estrategia en `app/services/core_toku_etl.py` (`_materialize_stub_subscriptions`).
