# Flujo: gestionar una suscripción de monto fijo

**Objetivo:** operar pausas de cobro, reanudaciones y cambios de monto cuando todas las suscripciones usan planes `MONTO_FIJO`.

> VirtualPOS no ofrece un endpoint para editar una suscripción, su `plan_id`, monto, frecuencia, día de cobro ni `charge_program`. Los cargos creados por un plan fijo tampoco pueden ser creados nuevamente con `POST /v3/charge`: ese endpoint exige un plan `MONTO_VARIABLE` (`E-113`).

## 1. Decisiones operativas

| Solicitud del socio | Operación | Resultado |
| --- | --- | --- |
| Baja definitiva | `DELETE /v3/suscription/{suscription_id}` | Suscripción `CANCELADA` y cargos pendientes cancelados. |
| Omitir un mes | `DELETE /v3/charge/{charge_id}` | Se cancela solo un cargo `pendiente`. |
| Pausar X meses | Listar cargos pendientes y cancelar uno por uno los que caigan en el rango. | La suscripción sigue `ACTIVA`; los cargos cancelados no se pueden restaurar. |
| Reanudar una pausa | No hay endpoint de reanudación. | Los cargos pendientes que no se cancelaron continuarán normalmente. |
| Cambiar el monto | Crear otra suscripción contra el plan fijo del nuevo monto y, cuando esté activa, dar de baja la anterior. Ver [cambiar-monto.md](cambiar-monto.md). | El socio debe inscribir la tarjeta otra vez. |
| Cambiar frecuencia o día de cobro | Igual que cambio de monto, usando el plan fijo de destino. | No se puede editar la suscripción existente. |

## 2. Pausar cobros por X meses

Esta es una **suspensión de cobro**, no un cambio de estado de la suscripción. Solo se puede aplicar sobre cargos `pendiente`; un cargo `procesando`, `pagado` o `rechazado` no puede cancelarse.

```text
Paso 1: GET /v3/suscription/{suscription_id}
↓  Validar que status = ACTIVA.
↓
Paso 2: GET /v3/suscription/{suscription_id}/charges?status=pendiente&limit=100&page=N
↓  Recorrer todas las páginas y seleccionar charge_date dentro del intervalo solicitado.
↓
Paso 3: Antes de cada cancelación, GET /v3/charge/{charge_id}
↓  Confirmar status = pendiente y charge_date esperado.
↓
Paso 4: DELETE /v3/charge/{charge_id}
↓  Registrar cargo, período, solicitante, motivo y respuesta.
↓
Paso 5: GET /v3/suscription/{suscription_id}/charges?status=pendiente
↓  Verificar que los meses suspendidos no sigan pendientes.
↓
Resultado: la suscripción permanece ACTIVA, sin cobro en los meses cancelados.
```

**No usar** `DELETE /v3/charges/{suscription_id}` para una pausa temporal: cancela todos los cargos pendientes, incluido el calendario posterior a la pausa, y no hay forma de recrearlos en un plan fijo.

### Límites de la pausa

- La cancelación de un cargo es irreversible por API.
- La API no documenta si los cargos cancelados afectan `num_charges` ni la renovación automática. Si la pausa debe extender el término de la membresía, validar ese comportamiento en sandbox antes de ofrecerlo.
- Si el primer cargo afectado ya está `procesando`, informar que podría cobrarse y cancelar solo los períodos posteriores que aún estén `pendiente`.

## 3. Cambiar el monto, frecuencia o día de cobro

> Ver [cambiar-monto.md](cambiar-monto.md). El flujo correcto es **crear primero la suscripción nueva** (el socio inscribe la tarjeta) y **cancelar la anterior solo cuando la nueva está `ACTIVA`**. Así el socio no queda sin cobertura si abandona el formulario. La migración no conserva la tarjeta tokenizada. Para frecuencia o día de cobro aplica la misma lógica.

## 4. Datos y auditoría

Registrar cada solicitud en `vpos_subscription_changes`:

`id, suscription_id, type [PAUSA|CAMBIO_MONTO|CAMBIO_FRECUENCIA|CAMBIO_DIA|BAJA], requested_by, requested_at, effective_from, effective_to, old_plan_id, new_plan_id, cancelled_charge_ids, reason, status, raw_response`.

Para una pausa, conservar explícitamente cada `charge_id` cancelado. Para una migración, enlazar la suscripción anterior con la nueva mediante `replaced_by_suscription_id` en la base propia.
