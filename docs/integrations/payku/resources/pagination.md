# Paginación y filtros

Documentación oficial: secciones de cada endpoint en https://docs.payku.com/cl/api/subscriptions/, https://docs.payku.com/cl/api/transaction/, https://docs.payku.com/cl/api/wallet/ y https://docs.payku.com/cl/api/reconciliation/

---

## Términos clave

- **Paginación por página (offset):** pides la página 1, 2, 3… con un tamaño fijo (`per_page`). Es el único mecanismo que usa Payku. ✅
- **Cursor:** un "marcador" que te da la API para seguir. **Payku no usa cursores.** ✅ (no aparece en la documentación)
- **Ventana de fechas:** rango `date_init` – `date_end` que limita los resultados.

🎨 **Analogía:** Payku te entrega un archivador por cajones (páginas). No te dice cuántos cajones hay; abres uno tras otro hasta encontrar uno vacío. Además, si no le dices qué **meses** quieres (fechas), solo te muestra el cajón de **hoy**.

---

## 1. Mecanismo ✅

Se agregan query params al final del endpoint:

```text
?page=1&per_page=100
```

- `page`: número de página (empieza en 1). ✅
- `per_page`: registros por página. ✅

---

## 2. Endpoints paginados y sus límites

| Endpoint | Máx. `per_page` | Filtro de fechas | Filtro de estado | Fuente |
|---|---|---|---|---|
| `GET /api/transaction` | **4000** ✅ | `date_init`, `date_end` ✅ | `?success=true`, `?pending=true&rejected=true` ✅ | Transacción |
| `GET /api/suclient/customers` | **100** ✅ | "posee un filtro de fecha" ✅ — **nombre del parámetro no documentado** ⚠️ | No documentado | Suscripción |
| `GET /api/sususcription` (V1) | **No indicado** ⚠️ (la doc dice "un máximo de  registros", sin número) | "posee un filtro de fecha" ✅ — **nombre no documentado** ⚠️ | `?<estado>=true` ✅ | Suscripción |
| `GET /api/sususcriptionv3` (V3) | **4000** ✅ | `date_init`, `date_end` ✅ | `?active=true` (y otros estados) ✅ | Suscripción |
| `GET /api/wallet/list` | **4000** ✅ | No documentado (la doc dice "posee los siguientes filtros:" y no lista ninguno) ⚠️ | No documentado | Wallet |

No paginados (según la documentación): `GET /api/suplan/plans`, `GET /api/banks`, `GET /api/paymentmethods`, `POST /api/conciliation`. ⚠️ Si devuelven muchos registros, no sabemos si cortan.

---

## 3. Filtros de fecha

### Comportamiento por defecto ✅ (crítico)

> Si `date_init` no se envía, la búsqueda inicia en la **fecha actual**. Si `date_end` no se envía, la búsqueda termina en la **fecha actual**.

👉 Un `GET /api/sususcriptionv3` **sin fechas devuelve solo lo del día de hoy**, no todo el historial. Lo mismo en transacciones, clientes y suscripciones V1.

### Formato

`YYYY-MM-DD` (ejemplo oficial: `date_init=2021-09-01&date_end=2021-09-15`). ✅

### Lo que NO está documentado ⚠️

| Pregunta | Estado |
|---|---|
| ¿Sobre qué fecha filtra? (creación, `start`, último cambio, fecha de pago…) | ⚠️ No confirmado. 💡 Probablemente creación/registro. |
| ¿Los extremos son inclusivos? | ⚠️ No confirmado. 💡 Solapar un día en cada ventana. |
| ¿Zona horaria? | ⚠️ No confirmado. 💡 Hora de Chile (la doc de `expired` habla de "hora Santiago"). |
| ¿Rango máximo entre `date_init` y `date_end`? | ⚠️ No documentado para listados. (En **conciliación** sí: máximo **30 días** ✅.) |
| ¿Existe un filtro por **fecha de actualización**? | ⚠️ No existe en la documentación. Impacta la sincronización incremental (ver [sync-payku.md](workflows/sync-payku.md)). |

### Conciliación ✅

`POST /api/conciliation` con body `{"date_init": "...", "date_end": "..."}`:
- `date_init` no puede ser mayor que hoy ni que `date_end`;
- `date_end` no puede ser mayor que hoy ni menor que `date_init`;
- rango máximo **30 días**.

---

## 4. Filtros de estado ✅

Se agrega el estado como parámetro con valor `true`. Puedes combinar varios:

```text
/api/transaction?pending=true&rejected=true
/api/sususcriptionv3?date_init=2021-09-01&date_end=2021-09-15&active=true
```

Si no envías ningún estado, se devuelven todos. ✅

⚠️ Los estados con espacios (p. ej. `canceled by customer`) no tienen un formato de filtro documentado.

---

## 5. Cómo detectar que hay más páginas

⚠️ **Payku no devuelve metadatos de paginación** (total de registros, total de páginas, `has_more`, `next`). La única excepción es `wallet/list`, que devuelve un objeto `filter` con `page` y `per_page` (pero sin total).

💡 Regla de corte recomendada:

```text
seguir mientras  len(items_de_la_página) == per_page
parar cuando     len(items_de_la_página) <  per_page   (incluye 0)
```

Más una **protección contra bucles**: si una página devuelve exactamente los mismos IDs que la anterior, parar y alertar (algunas APIs ignoran `page` fuera de rango y repiten la última página). ⚠️ No sabemos qué hace Payku con una página fuera de rango.

---

## 6. Forma de las respuestas de listados (ojo al parsear) ✅

| Endpoint | Forma |
|---|---|
| `GET /api/sususcription` | `[ { "subscriptions": [ … ] } ]` (arreglo con un objeto) |
| `GET /api/sususcriptionv3` | `[ { "subscriptions": [ … ] } ]` |
| `GET /api/suclient/customers` | `[ { "Customers": [ … ] } ]` (con **C mayúscula**) ⚠️ el ejemplo oficial está mal formado (mezcla esquema con datos) |
| `GET /api/transaction` | `{ "transaction": [ … ] }` |
| `GET /api/wallet/list` | `{ "status", "current_id", "amount_available", "filter", "wallet_movements": [ … ] }` |
| `GET /api/suplan/plans` | `{ "status": "success", "plans": [ … ] }` |

💡 El extractor debe ser tolerante: aceptar tanto `[ {...} ]` como `{...}`, y buscar la clave de la lista sin importar mayúsculas.

---

## 7. Estrategia recomendada para recorrer todo el dataset 💡

```python
def iter_pages(fetch_page, per_page: int, max_pages: int = 10_000):
    """fetch_page(page, per_page) -> list[dict]."""
    previous_ids = None
    for page in range(1, max_pages + 1):
        items = fetch_page(page, per_page)
        ids = tuple(item.get("id") for item in items)
        if previous_ids is not None and ids and ids == previous_ids:
            raise RuntimeError(f"Página {page} repite la anterior; corte de seguridad")
        yield from items
        if len(items) < per_page:
            return
        previous_ids = ids
    raise RuntimeError("Se alcanzó max_pages; revisar")
```

Para cargas históricas, combina **ventanas de fechas** con paginación:

```text
para cada ventana de 30 días desde FECHA_INICIO_CUENTA hasta hoy (con 1 día de solape):
    recorrer todas las páginas de esa ventana
```

- Ventanas cortas reducen el riesgo de timeouts y facilitan reprocesar un tramo.
- `per_page`: usa el máximo documentado (4000 en V3 y transacciones; 100 en clientes). ⚠️ Para V1 usa 100 hasta validar.
- Deduplica por `id` al guardar (upsert), porque el solape de ventanas genera repetidos.
