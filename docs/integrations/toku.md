# Toku

Toku aporta clientes, suscripciones, metodos de pago, deudas y transacciones. Usa una clave de API solo en el backend; los sincronizadores aplican limites y reintentos para respuestas temporales.

Las operaciones mutables implementadas requieren `TOKU_WRITES_ENABLED=true`, permisos y proteccion CSRF. El navegador no llama a Toku directamente.

El dashboard usa las deudas para su actividad y las transacciones para resultados de pago. La comparación con suscripciones activas usa exclusivamente transacciones fechadas del canal, no facturas.
