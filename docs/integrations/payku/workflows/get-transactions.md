# Flujo: obtener transacciones y cobros (y saber si están pagados)

## 1. Qué necesitamos hacer
Obtener todos los pagos recibidos por Payku y relacionarlos con suscripciones, socios y depósitos.

## 2. Endpoints necesarios

Payku tiene **dos mundos** de "transacciones":

| Mundo | Endpoint | Contiene |
|---|---|---|
| Cobros de **suscripción** | `GET /api/sususcriptionv3` (`paid[]`), `GET /api/sususcription/{id}` (`transactions[]`) | Cuotas de socios ✅ |
| Transacciones de **pago único** | `GET /api/transaction`, `GET /api/transaction/{id}` | Donaciones puntuales, pagos con Webpay/transferencia ✅ |
| Depósitos | `POST /api/conciliation` | Qué se liquidó, comisión y neto ✅ |

⚠️ No sabemos si los cobros de suscripción también aparecen en `GET /api/transaction` (Q-06). Hasta validarlo, se leen por separado y **no se suman** para evitar contar dos veces.

## 3. Recursos involucrados
Cobro de suscripción, transacción, conciliación → [data-model.md](../data-model.md).

## 4. Parámetros necesarios
- Transacciones: `date_init`, `date_end` (**obligatorios en la práctica**, por defecto hoy ✅), `page`, `per_page` ≤ 4000, filtros de estado.
- Conciliación: `date_init`, `date_end` (≤ 30 días ✅).

## 5. Ejemplo de request

```http
GET /api/transaction?date_init=2026-10-01&date_end=2026-10-12&success=true&page=1&per_page=1000
Authorization: Bearer <TOKEN_PUBLICO>
```

## 6. Ejemplo de response
Ver [transactions.md](../transactions.md#obtener-múltiples-transacciones).

## 7. Cómo implementarlo en backend 💡

```text
Paso 1  Suscripciones V3 (ventanas)        → cobros por ciclo (paid[])
Paso 2  Transacciones (ventanas)           → pagos únicos
Paso 3  Conciliación (ventanas ≤ 30 días)  → depósitos, fee, neto
Paso 4  Cruces:
          conciliación.payment_key ↔ transacción.payment.payment_key
          conciliación.order       ↔ cobro.order / transacción.order
Paso 5  Marcar cada cobro/transacción como: PAGADO / LIQUIDADO / DEPOSITADO
```

### ¿Cómo sé si una transacción está pagada? ✅
- Pago único: `status == "success"` (y `gateway_response.status == "success"`).
- Cobro de suscripción: `status == "success"` (V1/detalle/callback) o `paid[].status == "success"` (V3).
- Dinero en el banco: aparece en conciliación con `status == "paid_out"` 💡.

### ¿Cómo relaciono una transacción con una suscripción?
- Callback de cobro: `subscriptions.id` ✅.
- Lectura: el cobro está **dentro** de la suscripción ✅.
- Una transacción de `/api/transaction` → ⚠️ no hay campo de suscripción documentado.

## 8. Qué datos guardar
Ver [subscription-charges.md § 6](../subscription-charges.md#6-qué-guardar-por-cobro-) y [transactions.md](../transactions.md#campos-importantes). Para conciliación: `id`, `status`, `deposit_date`, y por transacción `payment_key`, `order`, `amount`, `fee`, `amount_deposit`.

## 9. Consideraciones importantes
- Montos con tipos mezclados (string/int): convertir a entero en el ETL.
- Fechas sin zona horaria: asumir `America/Santiago` ⚠️.
- La conciliación cambia de estado con el tiempo: reconsultar los últimos 30 días cada día.
