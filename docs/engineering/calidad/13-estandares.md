# Estándares de Desarrollo — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Convenciones obligatorias de código, API, datos y seguridad para mantener coherencia entre módulos.

---

## 1. Estándares de código (Python)

### 1.1 Linting y formato

- **Linter:** `ruff check .` — debe pasar limpio antes de todo merge.
- **No se omiten reglas** (`# noqa`) sin comentario que justifique el motivo y el issue abierto.
- Longitud máxima de línea: 100 caracteres.

### 1.2 Nomenclatura

| Elemento | Convención | Ejemplo |
|----------|-----------|---------|
| Tablas SQLAlchemy | `snake_case`, plural | `core_payments`, `tch_transacciones` |
| Modelos Python | `PascalCase` | `CorePayment`, `TokuSubscription` |
| Servicios ETL | `core_{provider}_etl.py` | `core_vp_etl.py` |
| Servicios sync | `{provider}_sync.py` | `toku_sync.py` |
| Endpoints FastAPI | `snake_case`, plural | `/core_payments`, `/sync/runs` |
| Variables de entorno | `UPPER_SNAKE_CASE` | `VPOS_WRITES_ENABLED`, `DATABASE_URL` |

### 1.3 Imports y dependencias

- Imports ordenados: stdlib → third-party → local (enforced por ruff).
- No importar `*`.
- Dependencias de proveedor solo en `app/services/` y `app/connectors/` — no en modelos ni schemas.

### 1.4 Manejo de errores

- ETL: capturar excepciones por registro, loguear y continuar — no abortar el batch completo por un registro fallido.
- Sync: `SyncRun.status = 'partial'` si algunos registros fallaron pero el bulk completó.
- Nunca silenciar `Exception` sin log.

---

## 2. Estándares de base de datos

### 2.1 Migraciones Alembic

- Cada cambio estructural: una migración nueva — nunca editar migraciones históricas.
- Nombrar migraciones descriptivamente: `add_status_to_core_subscriptions`, no `migration_001`.
- Toda migración debe tener `downgrade()` funcional.
- Si hay backfill de datos: separar en migración de estructura y script de backfill.

### 2.2 Idempotencia

Toda escritura de ingesta debe ser idempotente via:
```python
# source_records
INSERT ... ON CONFLICT (source, resource_type, external_id) DO UPDATE SET payload=...

# tablas de canal
INSERT ... ON CONFLICT (external_id) DO UPDATE SET ...
```

No usar `INSERT OR IGNORE` — siempre actualizar si el registro existe.

### 2.3 PII y datos sensibles

- Números de cuenta: solo últimos 4 dígitos en staging (`XXXX-8084`).
- RUT: almacenar normalizado pero **no loguear** completo.
- Email/teléfono: almacenar en staging, no exponer en logs de ETL.
- **Nunca almacenar:** PAN completo, CVV, datos de tarjeta más allá de últimos 4 dígitos.

### 2.4 Tipos de columnas

| Dato | Tipo recomendado |
|------|----------------|
| IDs externos | `VARCHAR` — no asumir formato numérico |
| Montos | `VARCHAR` o `NUMERIC(12,2)` — depende del proveedor |
| Fechas de proveedor | `VARCHAR` en staging, `TIMESTAMPTZ` en Core |
| Payloads raw | `JSONB` con índice GIN en campos de búsqueda frecuente |
| IDs internos | `UUID` generado por el CRM |

---

## 3. Estándares de API (FastAPI)

### 3.1 Estructura de respuestas

**Éxito paginado:**
```json
{
  "data": [...],
  "total": 1234,
  "page": 1,
  "page_size": 50
}
```

**Error:**
```json
{
  "detail": "Proveedor 'foo' no reconocido",
  "code": "UNKNOWN_PROVIDER"
}
```

### 3.2 Códigos HTTP

| Situación | Código |
|-----------|--------|
| Operación completada | 200 |
| Task creada en background | 202 Accepted |
| Recurso no encontrado | 404 |
| Ya en ejecución (sync running) | 409 Conflict |
| Error de validación | 422 |
| Sin autorización | 401 |
| Acceso denegado | 403 |

### 3.3 Autenticación

- JWT en header `Authorization: Bearer <token>`.
- HttpOnly cookies para sesiones de frontend.
- CSRF token requerido para mutations desde browser.
- No exponer tokens en URLs ni logs.

### 3.4 Operaciones de escritura a proveedor

- Requieren `*_WRITES_ENABLED=true` en env.
- Siempre registrar en `write_runs` con: proveedor, operación, payload (sanitizado), resultado.
- No ejecutar en el hilo principal — siempre background task.
- Endpoint debe requerir rol `admin`.

---

## 4. Estándares de connectors y sync

### 4.1 Paginación

Todo endpoint de proveedor debe paginarse hasta agotar resultados:
```python
while has_more:
    page = fetch_page(cursor=cursor, size=100)
    process(page)
    cursor = page.next_cursor
    has_more = page.has_more
```

Nunca asumir que la primera página contiene todos los datos.

### 4.2 Rate limiting

- VirtualPOS: respetar límites documentados; usar backoff exponencial.
- Toku: cursor-based pagination; no hay rate limit documentado — ser conservador.
- Payku: timeout conocido en `/api/transaction` — usar subscripciones con transacciones embebidas.

### 4.3 Sanitización de payloads

Antes de persistir en `source_records`:
- Remover campos que nunca deben almacenarse: PAN, CVV, datos de tarjeta completos.
- No loguear el payload completo si contiene datos personales — loguear solo IDs.

### 4.4 Separación de capas

```
connector (HTTP)
  → source_records (raw JSONB)
  → tablas de canal (estructuradas)
  → Core Layer (cross-proveedor)
```

- Nunca saltear capas: un connector no escribe directo a Core.
- No mezclar lógica de un proveedor en otro.

---

## 5. Estándares de seguridad

| Regla | Detalle |
|-------|---------|
| Secrets en `.env` | Nunca versionar `.env`; usar `.env.example` sin valores reales |
| Logs | Sin credenciales, tokens, RUT completos ni datos de pago |
| WRITES_ENABLED | Por defecto `false` en todos los entornos salvo staging explícito |
| Webhooks | Validar firma HMAC antes de procesar payload |
| Dependencias | Revisar `pip-audit` antes de agregar nueva dependencia |

---

## 6. Estándares de documentación de código

- **No comentar qué hace el código** — los nombres deben ser suficientes.
- **Sí comentar el por qué** cuando hay una invariante no obvia, una limitación del proveedor o un workaround:

```python
# VP no incluye client_id en el objeto suscripción (limitación de la API).
# La linkage se hace por social_id (RUT) vía _build_social_id_index().
```

- Docstrings solo en módulos: una línea de propósito + referencias a gaps conocidos.
- No docstrings en métodos internos simples.

---

*Documento generado el 2026-10-20.*
