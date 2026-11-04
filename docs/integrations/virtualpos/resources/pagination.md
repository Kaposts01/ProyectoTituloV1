# Paginación

> Fuente: https://virtualpos.readme.io/reference/paginacion-para-el-listado-de-objetos · Verificado: 2026-10-12

## 1. Cómo funciona

Paginación **numérica** (no por cursor) con dos parámetros de query:

| Parámetro | Descripción |
| --- | --- |
| `limit` | Registros por página. Mín. **1**, máx. **100**. |
| `page` | Página solicitada. |

```http
GET /v3/payments?limit=100&page=1
```

La respuesta trae:

```json
"pagination": { "limit": 3, "page": 1, "pages": 2, "total": 6 }
```

| Campo | Significado |
| --- | --- |
| `limit` | Registros por página aplicados |
| `page` | Página devuelta |
| `pages` | Total de páginas |
| `total` | Total de registros |

> **Ambigüedad oficial:** el texto dice que `limit=2&page=1` "omite el primer resultado", lo que sugeriría que `page` parte en 0. Pero `page: 1` aparece en todas las respuestas de ejemplo como primera página. **Inferencia:** `page` parte en **1**. Verifícalo en sandbox: pide `page=0` y `page=1` y compara el primer registro.

> **Observado en sandbox 2026-10-27** [CLAIM:VP-C14] (DRIFT): `page=0` no dio error (HTTP 200) y devolvió un primer registro distinto al de `page=1`. `limit=101` tampoco dio error (HTTP 200; devolvió 25 registros). Comportamiento no documentado: no depender de él. El CRM sigue usando `page` desde 1 y `limit` ≤ 100.

## 2. Dónde aplica

| Endpoint | Request `page`/`limit` | Respuesta | Nota |
| --- | --- | --- | --- |
| `GET /v3/payments` | Sí (página *Paginación*) | `pagination{}` | |
| `GET /v3/plans` | Sí (página *Paginación*) | `pagination{}` | |
| `GET /v3/suscriptions` | Sí (página *Paginación*) | `pagination{}` | |
| `GET /v3/suscription/{id}/charges` | Sí (página *Paginación*) | `pagination{}` | |
| `GET /v3/clients` | Sí (en la ficha, default `page=1`, `limit=100`) | **`page`, `limit`, `total` en la raíz**, sin `pages` | Formato distinto |
| `GET /v3/deposit/{date}/sales` | No documentado | `pagination{}` | No confirmado en la documentación oficial de VirtualPOS |
| `GET /v3/deposit/{date}/withholdings` | No documentado | `pagination{}` | No confirmado en la documentación oficial de VirtualPOS |

> **Observado en sandbox 2026-10-27** [CLAIM:VP-C15] (DRIFT): `GET /v3/clients` devuelve las claves raíz `clients`, `code`, `pagination`, `status`. La paginación viene en `pagination{}` y no en `page/limit/total` de la raíz.

Errores: `E-090` (page), `E-091` (limit).

## 3. Implementación robusta (**Recomendación**)

```js
// Node.js — recorre todas las páginas de cualquier listado de VirtualPOS
async function* paginate(client, path, params = {}, itemsKey) {
  const limit = 100;
  let page = 1;
  while (true) {
    const res = await client.get(path, { ...params, limit, page });
    // Formato estándar: { pagination: {pages} }  |  Clients: { page, limit, total }
    const pg = res.pagination ?? { page: res.page, limit: res.limit, total: res.total,
                                   pages: Math.ceil((res.total ?? 0) / (res.limit || limit)) };
    let items = res[itemsKey] ?? [];
    if (!Array.isArray(items)) items = [items];           // el ejemplo de /payments trae un objeto
    for (const it of items) yield it;
    if (items.length === 0 || page >= (pg.pages ?? 0)) break;
    page += 1;
    await sleep(200);                                      // rate limit no documentado: sé amable
  }
}
```

Puntos clave:

- **Condición de término doble**: `page >= pages` **o** página vacía (protege de bucles infinitos si `pages` viene mal).
- **Estabilidad:** si se crean registros mientras paginas, un orden por fecha descendente desplaza los elementos y puedes **saltarte o duplicar** registros. Mitigación: filtra por una ventana de fechas cerrada (`created_from`/`created_to` en el pasado) y haz *upsert* por ID.
- El orden por defecto solo está documentado para Clients (`created` descendente). Para el resto: No confirmado en la documentación oficial de VirtualPOS.
- Rate limit: no documentado. Usa una pausa entre páginas y backoff exponencial ante 429/5xx.
- **Observado en sandbox 2026-10-27** [CLAIM:VP-C16]: 20 GET seguidos con pausa de ~300 ms no dispararon 429 ni cabeceras de rate limit. Solo observación en sandbox; producción puede diferir.
