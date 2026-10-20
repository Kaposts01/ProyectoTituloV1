# Flujo: exportar todos los objetos de VirtualPOS

**Objetivo:** obtener una fotografía completa de clientes, planes, suscripciones, cargos y transacciones (`Payment`) en una base propia.

**Alcance:** exportación inicial o reconstrucción. Para la operación diaria, usar [sync-virtualpos.md](sync-virtualpos.md), que trabaja de forma incremental.

## 1. Principios

- Usar `limit=100` y recorrer todas las páginas de cada listado.
- Guardar primero la respuesta cruda y luego normalizarla. Cada objeto debe hacerse *upsert* por su ID de VirtualPOS.
- Pedir el detalle de cada objeto aunque el listado traiga campos similares. Los listados no garantizan incluir todos los atributos ni las relaciones completas.
- No existe una consulta global de cargos: deben obtenerse por cada suscripción.
- No existe relación directa por ID entre `Client` y `Suscription`/`Payment`. Unirlos localmente por RUT normalizado, email y, para socios propios, `service_id`.
- Una exportación no es atómica: los objetos pueden cambiar mientras se pagina. Repetir una pasada de conciliación al final y conservar `fetched_at` en cada registro.

## 2. Orden de extracción

```text
1. Plans          GET /v3/plans                         -> GET /v3/plan/{plan_id}
2. Clients        GET /v3/clients                       -> GET /v3/client/{client_uuid}
3. Suscriptions   GET /v3/suscriptions por cada estado  -> GET /v3/suscription/{suscription_id}
4. Charges        GET /v3/suscription/{id}/charges      -> GET /v3/charge/{charge_id}
5. Payments       GET /v3/payments                      -> GET /v3/payment/{payment_uuid}
6. Conciliación   enlazar Charge.payment.order.uuid y volver a consultar cambios recientes
```

Los planes se obtienen primero porque una suscripción contiene `plan_id`. Los pagos se extraen al final, ya que pueden enlazarse tanto desde `charge.payment.order.uuid` como desde el listado global de Payments.

## 3. Requests por objeto

| Objeto | Listado completo | Detalle por registro | Llave local | Observaciones |
| --- | --- | --- | --- | --- |
| Plan | `GET /v3/plans?limit=100&page=N` | `GET /v3/plan/{plan_id}` | `plan.id` | El listado incluye la definición principal; el detalle deja una fuente única por plan. |
| Cliente | `GET /v3/clients?limit=100&page=N` | `GET /v3/client/{client_uuid}` | `client.uuid` | La paginación viene en raíz: `page`, `limit`, `total`; calcular páginas con `ceil(total / limit)`. |
| Suscripción | Un listado por estado, ver abajo | `GET /v3/suscription/{suscription_id}` | `suscription.id` | No hay filtro incremental por actualización. |
| Cargo | `GET /v3/suscription/{suscription_id}/charges?limit=100&page=N` | `GET /v3/charge/{charge_id}` solo para `status=pagado` o `rechazado` | `charge.id` | No hay endpoint global de cargos. El detalle de la cuota aporta `payment.order.uuid`; para los estados `pendiente` y `cancelado` el listado es suficiente. |
| Payment | `GET /v3/payments?limit=100&page=N` | `GET /v3/payment/{payment_uuid}` solo si el listado no trae los campos necesarios (ej. `authorization_attempts_cards[]`) | `payment.order.uuid` | El ejemplo oficial modela `payments` como objeto; el parser debe aceptar objeto o arreglo. El detalle de pago es opcional si el listado ya incluye monto, estado y `order.uuid`. |

### Suscripciones: recorrer todos los estados

No depender de que omitir `status` devuelva todos los estados. Ejecutar el listado paginado para cada valor documentado:

```text
GET /v3/suscriptions?status=SUSCRIBIENDO&limit=100&page=N
GET /v3/suscriptions?status=SUSCRIPCION_FALLIDA&limit=100&page=N
GET /v3/suscriptions?status=ACTIVA&limit=100&page=N
GET /v3/suscriptions?status=CANCELADA&limit=100&page=N
GET /v3/suscriptions?status=FINALIZADA&limit=100&page=N
```

El mismo `suscription.id` puede aparecer en más de una respuesta si cambia de estado durante la exportación. El *upsert* por ID resuelve el duplicado; conservar el resultado más reciente por `fetched_at`.

## 4. Algoritmo de exportación

```text
Inicio: crear export_run con started_at y ambiente (sandbox/producción)
↓
Planes: listar páginas -> guardar RAW -> detalle por plan -> upsert vpos_plans
↓
Clientes: listar páginas -> guardar RAW -> detalle por cliente -> upsert vpos_clients
↓
Suscripciones: para cada estado, listar páginas -> detalle por suscripción
↓  -> upsert vpos_suscriptions y guardar charge_program[] como fuente preliminar de cargos
↓
Cargos: por cada suscripción encontrada, listar todas las páginas sin filtro de estado
↓  -> detalle solo para cargos con status `pagado` o `rechazado` (para obtener payment.order.uuid) -> upsert vpos_charges
↓
Payments: listar todas las páginas sin filtros de fecha ni estado
↓  -> detalle por Payment -> upsert vpos_payments
↓
Conciliación: enlazar payment_uuid en cargos; detectar objetos obtenidos al inicio que cambiaron
↓
Pasada final: repetir suscripciones ACTIVAS, sus cargos y Payments creados/autorizados desde el inicio del run
↓
Fin: marcar export_run como COMPLETADO y registrar conteos, errores y última página por recurso
```

La pasada final no garantiza una fotografía transaccional, porque la API no ofrece un corte o cursor de consistencia. Reduce, sin embargo, los vacíos de objetos que cambiaron durante la primera pasada.

## 5. Relaciones resultantes

```text
vpos_plans.plan_id
  <- vpos_suscriptions.plan_id
       <- vpos_charges.suscription_id
            <- vpos_charges.payment_uuid
                 = vpos_payments.payment_uuid

vpos_clients.social_id / email
  ~ vpos_suscriptions.client_social_id / client_email
  ~ vpos_payments.client_social_id / client_email
```

El símbolo `~` indica una relación débil: no hay `client_uuid` en la suscripción ni en el Payment. Para el modelo de socios, `service_id` debe ser el vínculo principal con la identidad local.

## 6. Paginación y tolerancia a errores

| Situación | Tratamiento |
| --- | --- |
| Listados estándar: Plan, Suscription, Charge, Payment | Terminar cuando `page >= pagination.pages` o la página llegue vacía. |
| Listado de Client | Terminar cuando `page * limit >= total` o la página llegue vacía. |
| `E-041`, `E-066`, `E-079`, `E-082` | No hay datos para ese recurso; registrar y continuar. |
| Timeout, 429 o 5xx en GET | Reintentar con backoff exponencial y preservar la página pendiente. |
| Error de detalle de un ID | Registrar el ID y continuar; reintentarlo en una cola al terminar la exportación. |
| Respuesta con tipos inconsistentes | Persistir RAW y normalizar con tolerancia, por ejemplo `amount: "6990"` a número. |

No aplicar reintentos HTTP automáticos a endpoints que cambian estado. Este flujo usa exclusivamente `GET`.

## 7. Límites documentados

- La API no documenta un endpoint para listar todos los cargos del comercio.
- La API no documenta filtros de actualización para planes, suscripciones ni clientes. Una extracción completa debe releerlos; la sincronización diaria mitiga el costo con barridos por frecuencia.
- `GET /v3/payments` permite filtros de fecha, pero para una exportación histórica completa deben omitirse y paginarse todos los resultados. Para la pasada final usar ventanas `created_from`/`created_to` y `authorization_from`/`authorization_to`.
- La documentación no publica límites de tasa. Aplicar una pausa corta entre páginas y limitar la concurrencia de detalles, por ejemplo a tres requests simultáneos.

## 8. Persistencia mínima

Guardar `raw_vpos(resource, external_id, endpoint, payload, payload_hash, fetched_at, export_run_id)` y las tablas normalizadas `vpos_plans`, `vpos_clients`, `vpos_suscriptions`, `vpos_charges` y `vpos_payments` descritas en [sync-virtualpos.md](sync-virtualpos.md#5-tablas-sugeridas-central).

Al finalizar, registrar: `export_run(id, environment, started_at, finished_at, status, plans, clients, suscriptions, charges, payments, errors)`.
