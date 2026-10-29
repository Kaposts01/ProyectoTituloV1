# Catálogo de códigos de error de la API

Desde la tanda D35 los errores de `writes.py`, `staging.py`, `security.py` y `scheduler.py` devuelven
`detail` como objeto `{"code": "<código_en_inglés>", "message": "<texto en español>"}`. El **código** es estable
(el frontend debe traducir por código); el **mensaje** en español es el respaldo mientras tanto. Los códigos HTTP
no cambian. Los errores de validación de FastAPI (422 con `detail` como lista) y los de `billing_changes`,
`changes`, `dashboard` e `imports` (que ya usaban `{code, message}`) no forman parte de este catálogo.

Notas:

- `operation_conflict` (409) y `invalid_operation` (422) llevan como `message` el texto de la excepción de dominio
  (en español); el detalle fino vive en el mensaje, no en el código.
- `toku_write_blocked` (403) lleva en el mensaje el código de la guarda de ambiente (p. ej. `NOT_ARMED`).
- `toku_deletion_aborted` (502) lleva en el mensaje el código interno de la causa (p. ej. `INVOICE_LIST_FAILED`).
- Los códigos de rechazo del proveedor (`virtualpos_rejected_*`, `toku_rejected_*`, `payku_rejected_*`) conservan el
  estado HTTP que devolvió el proveedor (`exc.response.status_code`).
- Referencia generada del código: se mantiene al día con `tests/test_error_codes.py` (todo código del código fuente
  debe figurar aquí).

| Código | HTTP | Ruta(s) | Causa (mensaje por defecto) |
|---|---|---|---|
| `alert_detail_virtualpos_only` | 404 | `GET /api/v1/staging/dashboard/{source}/alerts/{alert_id}` | Detalle de alertas solo disponible para VirtualPOS |
| `amount_max_not_numeric` | 422 | (función `_list_vp`, usada por varias rutas) | El monto máximo debe ser numérico. |
| `amount_min_not_numeric` | 422 | (función `_list_vp`, usada por varias rutas) | El monto mínimo debe ser numérico. |
| `amount_range_unsupported` | 422 | (función `_list_vp`, usada por varias rutas) | Este recurso no admite filtrar por rango de monto. |
| `at_least_one_field_required` | 422 | `PUT /api/v1/writes/virtualpos/clients/{client_id}`<br>`PUT /api/v1/writes/toku/customers/{customer_id}`<br>`PUT /api/v1/writes/payku/clients/{client_id}`<br>`PUT /api/v1/writes/toku/invoices/{invoice_id}` | Se requiere al menos un campo. |
| `authentication_not_configured` | 503 | toda ruta protegida (dependencia de seguridad) | La autenticación no está configurada en este servidor. |
| `authentication_required` | 401 | toda ruta protegida (dependencia de seguridad) | Debes iniciar sesión para continuar. |
| `cancellation_requires_reconciliation` | 503 | `DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}`<br>`DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>`DELETE /api/v1/writes/virtualpos/charges/{charge_id}`<br>`DELETE /api/v1/writes/payku/subscriptions/{subscription_id}`<br>`DELETE /api/v1/writes/virtualpos/payments/{payment_id}` | La cancelación requiere reconciliación local |
| `channel_disabled` | 409 | `POST /api/v1/staging/sync/{source}` | El canal {source} está deshabilitado en {settings.env_mode}. |
| `channels_disabled` | 409 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Canal(es) deshabilitado(s) en {settings.env_mode}: {', '.join(skipped)}. |
| `charge_not_found` | 404 | `DELETE /api/v1/writes/virtualpos/charges/{charge_id}`<br>`POST /api/v1/writes/virtualpos/charges/{charge_id}/retry` | Cargo no encontrado |
| `client_not_found` | 404 | `GET /api/v1/staging/dashboard/general/clients/{rut}` | Cliente no encontrado. |
| `date_range_unsupported` | 422 | (función `_list_vp`, usada por varias rutas) | Este recurso no admite filtrar por rango de fechas. |
| `deletion_requires_reconciliation` | 503 | `DELETE /api/v1/writes/toku/customers/{customer_id}`<br>`DELETE /api/v1/writes/payku/clients/{client_id}`<br>`DELETE /api/v1/writes/toku/subscriptions/{subscription_id}`<br>`DELETE /api/v1/writes/toku/invoices/{invoice_id}` | La eliminación requiere reconciliación local |
| `empty_channel_list` | 422 | `POST /api/v1/scheduler/jobs/{job_id}/run` | La lista de canales no puede estar vacía. |
| `expected_boolean_value` | 422 | (función `_vp_filter`, usada por varias rutas) | El campo {ff} debe ser verdadero o falso. |
| `invalid_channels` | 422 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Canales inválidos: {sorted(invalid)} |
| `invalid_csrf_token` | 403 | toda ruta protegida (dependencia de seguridad) | Sesión desactualizada. Recarga la página e inténtalo de nuevo. |
| `invalid_date_format` | 422 | (función `_list_vp`, usada por varias rutas) | El parámetro {parameter_name} debe tener el formato AAAA-MM-DD. |
| `invalid_filter_field` | 422 | (función `_staging_filter`, usada por varias rutas)<br>(función `_vp_filter`, usada por varias rutas)<br>(función `_toku_filter`, usada por varias rutas)<br>(función `_payku_filter`, usada por varias rutas) | Campo de filtro no válido. |
| `invalid_filter_format` | 422 | (función `_list_vp`, usada por varias rutas) | Los filtros deben tener el formato campo:valor. |
| `invalid_operation` | 422 | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>`POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/reassign-amount` | Texto de la excepción de dominio (datos no válidos para la operación). |
| `invalid_or_expired_session` | 401 | toda ruta protegida (dependencia de seguridad) | Sesión inválida o expirada. Vuelve a iniciar sesión. |
| `invalid_run_id` | 400 | `GET /api/v1/scheduler/runs/{run_id}/stream` | run_id inválido. |
| `invalid_rut` | 422 | `PUT /api/v1/writes/virtualpos/clients/{client_id}`<br>`POST /api/v1/writes/virtualpos/clients` | El RUT no es válido. |
| `invalid_session` | 401 | toda ruta protegida (dependencia de seguridad) | Sesión inválida. Vuelve a iniciar sesión. |
| `invalid_sort_field` | 422 | (función `_toku_sort_field`, usada por varias rutas)<br>(función `_vp_sort_field`, usada por varias rutas)<br>(función `_payku_sort_field`, usada por varias rutas) | Campo de orden no válido. |
| `invalid_staging_resource` | 422 | `GET /api/v1/staging/records/filter-values` | Tipo de registro no válido. |
| `job_already_running` | 409 | `POST /api/v1/scheduler/jobs/{job_id}/run` | El job ya está en ejecución (run_id={running.id}). |
| `job_channel_selection_unsupported` | 422 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Este job no admite selección de canales. |
| `job_manual_run_unsupported` | 400 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Job no soporta ejecución manual. |
| `job_not_found` | 404 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Job '{job_id}' no encontrado. |
| `operation_conflict` | 409 | `POST /api/v1/writes/virtualpos/subscriptions`<br>`DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}`<br>`DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>`POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/reassign-amount`<br>`POST /api/v1/writes/virtualpos/charges/{charge_id}/retry` | Texto de la excepción de dominio (conflicto con el estado actual). |
| `payku_client_not_found` | 404 | `PUT /api/v1/writes/payku/clients/{client_id}`<br>`DELETE /api/v1/writes/payku/clients/{client_id}` | Cliente Payku no encontrado |
| `payku_rejected_cancellation` | el del proveedor | `DELETE /api/v1/writes/payku/subscriptions/{subscription_id}` | Payku rechazó la cancelación |
| `payku_rejected_deletion` | el del proveedor | `DELETE /api/v1/writes/payku/clients/{client_id}` | Payku rechazó la eliminación |
| `payku_rejected_update` | el del proveedor | `PUT /api/v1/writes/payku/clients/{client_id}` | Payku rechazó la actualización |
| `payku_subscription_not_found` | 404 | `DELETE /api/v1/writes/payku/subscriptions/{subscription_id}` | Suscripción Payku no encontrada |
| `payku_writes_disabled` | 403 | `PUT /api/v1/writes/payku/clients/{client_id}`<br>`DELETE /api/v1/writes/payku/clients/{client_id}`<br>`DELETE /api/v1/writes/payku/subscriptions/{subscription_id}` | Las escrituras a Payku están deshabilitadas en este ambiente. |
| `payment_not_found` | 404 | `DELETE /api/v1/writes/virtualpos/payments/{payment_id}` | Pago no encontrado |
| `permission_denied` | 403 | (función `_require_source_access`, usada por varias rutas)<br>`POST /api/v1/writes/toku/subscriptions/{subscription_id}/status`<br>toda ruta protegida (dependencia de seguridad) | No tienes permiso para realizar esta acción. |
| `provider_resource_not_found` | 404 | (función `_require_source_access`, usada por varias rutas) | Recurso del proveedor no encontrado. |
| `reassignment_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/reassign-amount` | La reasignación requiere reconciliación local |
| `retry_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/charges/{charge_id}/retry` | El reintento requiere reconciliación local |
| `secondary_status_filter_invalid` | 422 | (función `_list_vp`, usada por varias rutas) | El filtro de estado secundario solo vale para suscripciones. |
| `staging_record_not_found` | 404 | `GET /api/v1/staging/{source}/{resource_type}/{external_id}` | Registro no encontrado. |
| `status_change_requires_reconciliation` | 503 | `POST /api/v1/writes/toku/subscriptions/{subscription_id}/status` | El cambio de estado requiere reconciliación local |
| `subscription_not_found` | 404 | `DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}` | Suscripción no encontrada |
| `subscription_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/subscriptions` | La suscripción requiere reconciliación local |
| `sync_already_active` | 409 | `POST /api/v1/scheduler/jobs/{job_id}/run` | Ya hay una sincronización activa (run_id={busy.run_id}). Espera a que termine. |
| `toku_client_not_found` | 404 | `PUT /api/v1/writes/toku/customers/{customer_id}`<br>`DELETE /api/v1/writes/toku/customers/{customer_id}` | Cliente Toku no encontrado |
| `toku_deletion_aborted` | 502 | `DELETE /api/v1/writes/toku/subscriptions/{subscription_id}` | Eliminación abortada: la suscripción no se eliminó ({exc.code}). |
| `toku_invoice_not_found` | 404 | `PUT /api/v1/writes/toku/invoices/{invoice_id}`<br>`DELETE /api/v1/writes/toku/invoices/{invoice_id}` | Invoice Toku no encontrado |
| `toku_rejected_deletion` | el del proveedor | `DELETE /api/v1/writes/toku/customers/{customer_id}`<br>`DELETE /api/v1/writes/toku/subscriptions/{subscription_id}` | Toku rechazó la eliminación |
| `toku_rejected_invoice_deletion` | el del proveedor | `DELETE /api/v1/writes/toku/invoices/{invoice_id}` | Toku rechazó la eliminación del invoice |
| `toku_rejected_invoice_update` | el del proveedor | `PUT /api/v1/writes/toku/invoices/{invoice_id}` | Toku rechazó la actualización del invoice |
| `toku_rejected_status_change` | el del proveedor | `POST /api/v1/writes/toku/subscriptions/{subscription_id}/status` | Toku rechazó el cambio de estado |
| `toku_rejected_update` | el del proveedor | `PUT /api/v1/writes/toku/customers/{customer_id}` | Toku rechazó la actualización |
| `toku_subscription_not_found` | 404 | `POST /api/v1/writes/toku/subscriptions/{subscription_id}/status`<br>`DELETE /api/v1/writes/toku/subscriptions/{subscription_id}` | Suscripción Toku no encontrada |
| `toku_write_blocked` | 403 | `PUT /api/v1/writes/toku/customers/{customer_id}`<br>`DELETE /api/v1/writes/toku/customers/{customer_id}`<br>`POST /api/v1/writes/toku/subscriptions/{subscription_id}/status`<br>`DELETE /api/v1/writes/toku/subscriptions/{subscription_id}`<br>`PUT /api/v1/writes/toku/invoices/{invoice_id}`<br>`DELETE /api/v1/writes/toku/invoices/{invoice_id}` | Escritura Toku bloqueada por las guardas de ambiente (<código de guarda>). |
| `toku_writes_disabled` | 403 | `PUT /api/v1/writes/toku/customers/{customer_id}`<br>`DELETE /api/v1/writes/toku/customers/{customer_id}`<br>`POST /api/v1/writes/toku/subscriptions/{subscription_id}/status`<br>`DELETE /api/v1/writes/toku/subscriptions/{subscription_id}`<br>`PUT /api/v1/writes/toku/invoices/{invoice_id}`<br>`DELETE /api/v1/writes/toku/invoices/{invoice_id}` | Las escrituras a Toku están deshabilitadas en este ambiente. |
| `unknown_alert_type` | 404 | `GET /api/v1/staging/dashboard/{source}/alerts/{alert_id}` | Tipo de alerta '{alert_id}' no reconocido |
| `unknown_channel` | 404 | `GET /api/v1/staging/dashboard/channel/{source}` | Canal desconocido: {source}. Válidos: <lista de canales>. |
| `unknown_staging_resource` | 404 | `GET /api/v1/staging/{source}/{resource_type}/{external_id}` | Tipo de registro desconocido. |
| `unknown_staging_source` | 404 | `GET /api/v1/staging/records/filter-values`<br>`GET /api/v1/staging/dashboard/{source}`<br>`POST /api/v1/staging/sync/{source}` | Origen de registros desconocido. |
| `unsupported_filter_value_field` | 422 | `GET /api/v1/staging/records/filter-values` | Ese campo no admite valores de filtro. |
| `update_requires_reconciliation` | 503 | `PUT /api/v1/writes/toku/customers/{customer_id}`<br>`PUT /api/v1/writes/payku/clients/{client_id}`<br>`PUT /api/v1/writes/toku/invoices/{invoice_id}` | La actualización requiere reconciliación local |
| `virtualpos_charge_listing_incomplete` | 502 | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>`DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>`POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/reassign-amount` | Listado de cobros de VirtualPOS incompleto o inesperado |
| `virtualpos_charge_not_found` | 404 | `GET /api/v1/staging/virtualpos/charges/{external_id}` | No se encontró el cargo en VirtualPOS. |
| `virtualpos_charge_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges` | La operación sobre el cargo requiere conciliación local. |
| `virtualpos_client_duplicate_document` | 409 | `POST /api/v1/writes/virtualpos/clients` | Ya existe un cliente con ese documento de identidad en VirtualPOS |
| `virtualpos_client_not_found` | 404 | `GET /api/v1/staging/virtualpos/clients/{external_id}`<br>`PUT /api/v1/writes/virtualpos/clients/{client_id}` | No se encontró el cliente en VirtualPOS. |
| `virtualpos_client_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/clients` | La operación sobre el cliente requiere conciliación local. |
| `virtualpos_payment_not_found` | 404 | `GET /api/v1/staging/virtualpos/payments/{external_id}` | No se encontró el pago en VirtualPOS. |
| `virtualpos_plan_not_found` | 404 | `GET /api/v1/staging/virtualpos/plans/{external_id}` | No se encontró el plan en VirtualPOS. |
| `virtualpos_plan_requires_reconciliation` | 503 | `POST /api/v1/writes/virtualpos/plans` | La operación sobre el plan requiere conciliación local. |
| `virtualpos_rejected_amount_reassignment` | el del proveedor | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/reassign-amount` | VirtualPOS rechazó la reasignación de monto |
| `virtualpos_rejected_cancellation` | el del proveedor | `DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}` | VirtualPOS rechazó la cancelación |
| `virtualpos_rejected_charge` | el del proveedor | `POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges` | VirtualPOS rechazó el cargo. |
| `virtualpos_rejected_charge_cancellation` | el del proveedor | `DELETE /api/v1/writes/virtualpos/charges/{charge_id}` | VirtualPOS rechazó la cancelación del cargo |
| `virtualpos_rejected_charge_retry` | el del proveedor | `POST /api/v1/writes/virtualpos/charges/{charge_id}/retry` | VirtualPOS rechazó el reintento del cargo |
| `virtualpos_rejected_charges_cancellation` | el del proveedor | `DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges` | VirtualPOS rechazó la cancelación de cargos |
| `virtualpos_rejected_client` | el del proveedor | `POST /api/v1/writes/virtualpos/clients` | VirtualPOS rechazó el cliente. |
| `virtualpos_rejected_payment_cancellation` | el del proveedor | `DELETE /api/v1/writes/virtualpos/payments/{payment_id}` | VirtualPOS rechazó la cancelación del pago |
| `virtualpos_rejected_plan` | el del proveedor | `POST /api/v1/writes/virtualpos/plans` | VirtualPOS rechazó el plan. |
| `virtualpos_rejected_subscription` | el del proveedor | `POST /api/v1/writes/virtualpos/subscriptions` | VirtualPOS rechazó la suscripción |
| `virtualpos_rejected_update` | el del proveedor | `PUT /api/v1/writes/virtualpos/clients/{client_id}` | VirtualPOS rechazó la actualización. |
| `virtualpos_subscription_not_found` | 404 | `GET /api/v1/staging/virtualpos/subscriptions/{external_id}` | No se encontró la suscripción en VirtualPOS. |
| `virtualpos_update_requires_reconciliation` | 503 | `PUT /api/v1/writes/virtualpos/clients/{client_id}` | La actualización requiere conciliación local. |
| `virtualpos_writes_disabled` | 403 | `PUT /api/v1/writes/virtualpos/clients/{client_id}`<br>`POST /api/v1/writes/virtualpos/clients`<br>`POST /api/v1/writes/virtualpos/plans`<br>`POST /api/v1/writes/virtualpos/subscriptions`<br>`DELETE /api/v1/writes/virtualpos/subscriptions/{subscription_id}`<br>`POST /api/v1/writes/virtualpos/subscriptions/{subscription_id}/charges`<br>… (+5 rutas) | Las escrituras a VirtualPOS están deshabilitadas en este ambiente. |

Total: 90 códigos en 154 puntos de error.
