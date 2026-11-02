# Runbook de webhooks (RT-17)

Operación diaria y de incidentes de la cola `webhook_events`. Diseño y contrato: `docs/data/webhooks.md`. Tiempo real hacia el navegador: `docs/architecture/data-flow.md`.

Reglas que valen para todo este documento:

- Los secretos (`TOKU_WEBHOOK_SECRET`, `PAYKU_WEBHOOK_SECRET`, `VIRTUALPOS_PAYOUT_WEBHOOK_SECRET`) viven **solo** en el `.env` real o en el gestor de secretos. Nunca en el chat, en Git, en tickets ni en capturas.
- Exponer algo a Internet (túnel, dominio, puerto) exige confirmación explícita en el momento (decisión D8). Solo `/api/v1/webhooks/*`, nunca el frontend ni el resto de la API.
- Probar primero en `crm_sandbox`. Con `APP_ENV=development` el procesador escribe en `crm`.
- Tras cambiar el `.env` hay que reiniciar el backend: no se recarga solo.

## 1. Revisar la salud

1. Entrar a **Administración → Sincronización → Salud de webhooks** (permiso `webhooks.manage`).
2. Mirar por canal: pendientes, fallidos, demora del pendiente más antiguo y último recibido.
3. Señales de alarma:
   - procesador apagado con pendientes que crecen: falta `WEBHOOK_PROCESSOR_ENABLED=true`;
   - demora de minutos u horas con el procesador encendido: el job no corre (backend caído o scheduler detenido) o el proveedor no responde;
   - un canal con «último recibido» viejo: el proveedor dejó de enviar (túnel caído, endpoint deshabilitado o secreto rotado sin actualizar);
   - muchos `PROVIDER_READ_FAILED`: el proveedor está caído o limita peticiones.
4. Si las alertas están configuradas (`ALERTS_ENABLED`, `ALERT_EMAIL_TO`, `ALERT_SMTP_HOST`), llegan correos `webhook_failed`, `webhook_lag` y, si `ALERT_WEBHOOK_SILENCE_HOURS` > 0, `webhook_silence:<canal>`.

## 2. Reprocesar eventos fallidos

Seguro siempre: el procesador relee al proveedor y no aplica el contenido del webhook.

1. Corregir primero la causa (proveedor caído, credencial vencida, procesador apagado).
2. En el panel, «Reprocesar» por evento o «Reprocesar todos los fallidos». Por API: `POST /api/v1/admin/webhooks/requeue` con `{"ids": [...]}` o `{"all_failed": true, "source": "toku"}` (sesión y CSRF).
3. El evento vuelve a `pending` con `attempts=0` y el procesador lo toma en el siguiente minuto. Los `ignored` solo se reencolan por id (se descartaron a propósito, p. ej. `NO_RESOURCE`).
4. Si vuelve a fallar con el mismo código, no repetir en bucle: revisar el log del backend (solo trae la clase de la excepción y códigos fijos).

## 3. Rotar un secreto

### Toku (`TOKU_WEBHOOK_SECRET`, `whesec_…`)

1. En Toku, recrear o actualizar el endpoint (ver 4). Toku devuelve un secreto nuevo.
2. Guardar el secreto nuevo en el `.env` real y reiniciar el backend.
3. Entre el cambio en Toku y el reinicio, los avisos llegan con una firma que el backend rechaza (401). Toku los reintenta durante ~1 h 41 min: si el reinicio ocurre dentro de esa ventana, no se pierde nada. Si no, seguir el paso 5.
4. Verificar con un evento de prueba que el receptor responde 200 y que aparece la fila en el panel.

### Payku (`PAYKU_WEBHOOK_SECRET`, token `?k=`)

1. Elegir un token nuevo largo y aleatorio. Cambiarlo en el `.env` real y en las URLs `url_notify_*` del plan o de la transacción.
2. Cambiar las URL de un plan afecta a todas sus suscripciones, y los planes son fijos: **requiere autorización** antes de tocarlos (RT-10).
3. Rotarlo si se sospecha que el token se filtró: viaja en la URL y queda en los logs de cualquier proxy o túnel intermedio.

### VirtualPOS payout (`VIRTUALPOS_PAYOUT_WEBHOOK_SECRET`)

Se acuerda con VirtualPOS (no hay portal). Coordinar la fecha del cambio, actualizar el `.env` y reiniciar a la hora acordada.

## 4. Recrear el endpoint de Toku

1. Usar la petición de Postman «Crear Webhook Endpoint» (`POST /webhook_endpoints`) con la URL pública **fija** `https://<dominio fijo>/api/v1/webhooks/toku`.
2. Toku hace upsert por URL: con una URL distinta se crea un endpoint duplicado. No usar URL temporales (`trycloudflare`).
3. `enabled_events` acotados: `subscription.created`, `subscription.updated`, `subscription.deleted`, `transaction.success`, `transaction.failed`, `invoice.paid`, `invoice.voided`, `payment_method.status_update`, `payment_method.deleted`.
4. Copiar el `whesec_…` devuelto directo al `.env` (ver 3) y reiniciar.
5. Si el endpoint quedó `disabled`, Toku descarta los pendientes: tratarlo como ventana perdida (paso 5).
6. La llave de sandbox de Toku comparte host con producción (DEC-26): confirmar qué llave se usa antes de crear nada.

## 5. Se perdió la ventana de reintentos (más de 1 h 41 min sin recibir)

Pasa con el PC apagado, el túnel caído, el secreto mal configurado o el endpoint deshabilitado.

1. Arreglar la causa y comprobar con un evento de prueba que vuelve a entrar.
2. Lo perdido no se recupera desde el proveedor por webhook. Recuperarlo así, de menor a mayor costo:
   - **Reconciliación dirigida** (`TARGETED_RECONCILE_ENABLED=true`): corre 6 veces al día (07 a 22 h) y refresca las suscripciones con cobros recientes, rechazos o pendientes vencidos. No cubre suscripciones sin cobros en esa ventana.
   - **Sincronización completa** del canal afectado desde Administración → Sincronización (1,9 a 2,8 h; respeta el lock de corridas).
   - **Reportes descargados** de Toku o VirtualPOS (importación de reportes) para el estado de suscripción.
3. Los cambios recuperados quedan en `status_change_events` como cualquier otro; el navegador los recibe por el SSE.
4. Anotar el intervalo perdido (desde y hasta) para revisar luego en el panel o en el historial de cambios.

## 6. El navegador no recibe cambios en vivo

1. El SSE es `GET /api/v1/events/stream` y exige sesión y `dashboard.view`. Una sesión vencida corta el stream y el frontend pasa a polling cada 60 s.
2. Detrás de un proxy, desactivar el buffering (el backend ya manda `X-Accel-Buffering: no` y `Cache-Control: no-transform`).
3. Recuerda que el SSE solo avisa de lo que ya cambió en la base: si el procesador está apagado o el proveedor no avisa, no hay nada que empujar.

## 7. Purga

Manual y administrada por el usuario (sentencias en `docs/data/webhooks.md`, «Retención y purga sugerida»). Nunca purgar `pending` ni `processing`. `status_change_events` es append-only y no se purga.
