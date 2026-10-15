# Paginación

Doc oficial: <https://docs.trytoku.com/reference/headers-y-convenciones> (sección paginación) y la página de cada listado.

Toku usa **dos mecanismos distintos** según el endpoint. [Confirmado]

## 1. Paginación por cursor

**Analogía:** es como leer un libro con un marcador. Toku te devuelve una página y el marcador (`next_cursor`). Para seguir leyendo le devuelves el marcador. No puedes saltar a la página 7.

| Elemento | Valor |
|---|---|
| Parámetros | `page_size` (por defecto 50, mín. 1, máx. 100) y `next_cursor` (omitir en la primera llamada) |
| Respuesta | `{ "items": [...], "next_cursor": "..." }` |
| Fin | `next_cursor` es `null` |
| Total | No se informa |

Endpoints que la usan [Confirmado]:

| Endpoint | Notas |
|---|---|
| `GET /customers` | |
| `GET /subscriptions` | |
| `GET /invoices` | |
| `GET /invoices/chargeable` | La doc dice que el orden es estable entre páginas. |

```text
cursor = null
repetir:
    resp = GET /invoices?page_size=100[&next_cursor=cursor]
    procesar(resp.items)
    cursor = resp.next_cursor
hasta que cursor == null
```

## 2. Paginación por número de página

**Analogía:** es un catálogo numerado. Pides la página 1, 2, 3… y te dicen cuántos productos hay en total.

| Elemento | Valor |
|---|---|
| Parámetros | `page` (empieza en 1) y `page_size` (por defecto 50, mín. 1, máx. 100) |
| Respuesta | `{ "items": [...], "total_results": N }` |
| Fin | **[Inferencia]** cuando `page * page_size >= total_results`, o cuando `items` viene vacío. Toku no expone `has_more`. |

Endpoints que la usan [Confirmado]:

| Endpoint | Notas |
|---|---|
| `GET /transactions` | Límite de **1 req/s**. Mantener los mismos filtros en todas las páginas. |
| `GET /payment-methods` | `total_results` puede ser **mayor** que la suma de `items`: Toku descarta los ítems cuya forma agregada no puede construir, pero igual los cuenta. |

```text
page = 1
repetir:
    resp = GET /transactions?page={page}&page_size=100&start_date=...&end_date=...
    procesar(resp.items)
    si len(resp.items) == 0 o page * 100 >= resp.total_results: terminar
    page += 1
    esperar ≥ 1 s   # rate limit de transactions
```

> ⚠️ **Por la diferencia de `total_results` en Payment Methods**, no uses `len(items) < page_size` como condición de término en ese endpoint: puede cortar antes de tiempo. Usa `page * page_size >= total_results`. [Inferencia]

## 3. Endpoints sin paginación (devuelven un array) [Confirmado]

| Endpoint | Riesgo |
|---|---|
| `GET /customers/{id}/invoices` | Un Customer con historial muy largo podría devolver un array grande. |
| `GET /invoices/customer/{id}` | Igual; además responde `404` si el Customer no tiene Invoices. |
| `GET /subscriptions/customer/{customer_id}` | |
| `GET /webhook_endpoints` | |
| `GET /customer-collection-accounts?customer=` | Devuelve `{ "customer_collection_accounts": [...] }` y `404` si no hay cuentas activas. |

## 4. Recomendaciones para recorrer todo [Recomendación]

1. Usar siempre `page_size=100`: menos llamadas y menos riesgo de rate limit.
2. **Secuencial, no paralelo.** El rate limit es por credencial, así que paralelizar con la misma key no ayuda.
3. Ante un `429`: backoff exponencial (1 s, 2 s, 4 s, 8 s…), con un máximo de reintentos y registro del cursor o página donde se cortó, para poder retomar.
4. **Hacer checkpoint del cursor/página** en un almacenamiento persistente. Si el proceso muere (por ejemplo, por el límite de 6 minutos de Apps Script), debe retomar donde quedó.
5. **[Inferencia]** Un cursor puede quedar inválido si pasa mucho tiempo. Si un cursor falla con `422`, reiniciar la carga de ese recurso desde cero (los upserts en STG son idempotentes).
6. Paginación por página con datos que cambian: si entran registros nuevos durante la lectura, las páginas se pueden "correr". Para Transactions, acotar con `start_date`/`end_date` fijos durante toda la corrida.
