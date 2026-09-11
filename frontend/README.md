# Dashboard CRM

Interfaz React read-only para los registros de staging locales de VirtualPOS, Toku y Payku.

## Desarrollo local

1. Inicia FastAPI en `http://127.0.0.1:8000`.
2. En `frontend/`, ejecuta `npm install` la primera vez.
3. Ejecuta `npm run dev`.
4. Abre `http://127.0.0.1:5173`.

Vite redirige `/api` hacia FastAPI local. El navegador no configura credenciales ni realiza solicitudes a proveedores.

## Alcance

- Dashboard global con el resumen de staging por fuente.
- Mini dashboards para VirtualPOS, Toku y Payku con metricas, estados y actividad mensual disponibles.
- Exploradores por recurso con columnas propias de cada proveedor.
- Fichas relacionadas para clientes, planes y suscripciones VirtualPOS; fichas completas y relaciones verificables para Toku y Payku.
- TCH sigue reservado y no tiene integracion activa.

Los datos se muestran tal como estan en staging saneado. No se infieren relaciones que el proveedor no haya declarado y no se muestran datos de tarjeta completos.
