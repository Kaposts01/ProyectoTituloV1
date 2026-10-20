# Flujo: obtener suscripciones (y saber si están activas)

## 1. Qué necesitamos hacer
Saber qué suscripciones existen, en qué estado están y si pagaron.

## 2. Endpoint necesario (según el caso)

| Caso | Endpoint |
|---|---|
| Masivo, con pagos por ciclo | `GET /api/sususcriptionv3?date_init=…&date_end=…&page=…&per_page=…` ✅ (recomendado) |
| Masivo, con `last_status_current_payment` | `GET /api/sususcription?page=…&per_page=…` (V1) |
| Una sola suscripción | `GET /api/sususcription/{id}` |
| Las suscripciones de un cliente | `GET /api/suclient/{id}` → `subcriptions` (⚠️ objeto, no arreglo) |
| Solo las activas | V3 con `active=true` ✅ |

## 3. Recurso involucrado
Suscripción → [subscriptions.md](../subscriptions.md).

## 4. Parámetros necesarios
- **Siempre** `date_init` y `date_end` (sin ellos solo trae **hoy** ✅).
- `per_page` hasta 4000 en V3 ✅.
- Filtros de estado opcionales (`active=true`, `suspended=true`, …).

## 5. Ejemplo de request

```http
GET /api/sususcriptionv3?date_init=2026-09-13&date_end=2026-10-12&page=1&per_page=1000
Authorization: Bearer <TOKEN_PUBLICO>
Sign: <firma de /api/sususcriptionv3 + date_end, date_init, page, per_page>
```

## 6. Ejemplo de response
Ver [subscriptions.md § V3](../subscriptions.md#obtener-suscripciones-v3-recomendado-para-sincronizar).

## 7. Cómo implementarlo en backend 💡

```python
def fetch_subscriptions_v3(date_init: date, date_end: date, per_page: int = 1000):
    def fetch_page(page, per_page):
        params = {"date_init": date_init.isoformat(), "date_end": date_end.isoformat(),
                  "page": str(page), "per_page": str(per_page)}
        data = payku.get("/api/sususcriptionv3", params=params)
        return extract_list(data, key="subscriptions")   # tolera [ {subscriptions: [...]} ]
    yield from iter_pages(fetch_page, per_page)           # ver pagination.md
```

### ¿Cómo sé si una suscripción está activa? ✅
`estatus == "active"` (V3) o `status == "active"` (V1/detalle).

### ¿Cómo sé si está "al día"? 💡
Mira el último ciclo en `paid[]` (V3): `status == "success"` y `payment_cycle_day` del periodo esperado. Si el último ciclo tiene `try_number > 1` y no es `success`, está en reintentos. `active` **no** garantiza que el último cobro haya salido bien.

## 8. Qué datos guardar
Cada elemento crudo en `stg_payku_subscription_v3`; luego el ETL actualiza `suscripcion`, `cobro` y `suscripcion_estado_hist`. Ver [data-model.md § 5](../data-model.md#5-qué-va-a-stg_payku-y-qué-al-modelo-normalizado).

## 9. Consideraciones importantes
- ⚠️ No sabemos sobre qué fecha filtra el rango (Q-11). Hasta validarlo, para "todas las suscripciones vigentes" usa un rango **desde el inicio de la cuenta** hasta hoy, en ventanas.
- V1 y V3 usan nombres distintos (`status` / `estatus`, `cards` / `active_cards`).
- Sin metadatos de paginación: cortar cuando la página venga incompleta.
