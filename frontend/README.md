# Dashboard CRM

Dashboard read-only para los datos normalizados desde VirtualPOS Sandbox.

## Desarrollo local

1. Inicia FastAPI en `http://127.0.0.1:8000`.
2. Ejecuta `npm install` la primera vez.
3. Ejecuta `npm run dev`.
4. Abre `http://127.0.0.1:5173`.

Vite redirige `/api` a FastAPI local. No se configuran credenciales ni se llama directamente a VirtualPOS desde el navegador.

## Alcance inicial

- Metricas de clientes, planes, suscripciones, cargos y pagos.
- Estado de la ultima sincronizacion.
- Explorador de registros para clientes, planes, suscripciones, cargos y pagos.
- Detalle de cliente con UUID VirtualPOS, identidad, contacto, estado, fechas y tarjetas resumidas.
- Detalle de plan, cargo y pago con todos los campos disponibles en su `GET` CRM.
- Detalle de suscripcion con plan y cargos relacionados.

No se muestran pagos ni relaciones de cliente no confirmadas por el proveedor.
