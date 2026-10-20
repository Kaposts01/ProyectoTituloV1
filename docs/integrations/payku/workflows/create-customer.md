# Flujo: crear (o encontrar) un cliente

## 1. Qué necesitamos hacer
Tener un cliente de suscripción en Payku para un socio nuestro, **sin duplicarlo**.

## 2. Endpoints necesarios

```http
GET  /api/suclient/{email}
POST /api/suclient
```

## 3. Recurso involucrado
Cliente de suscripción (`cl…`) → [customers.md](../customers.md).

## 4. Parámetros necesarios
- Para buscar: email del socio (path).
- Para crear: `email`, `name`, `phone` (obligatorios ✅); `rut`, dirección y `additional_parameters` opcionales.

## 5. Ejemplo de request

```bash
# 1) Buscar
curl -X GET "https://des.payku.cl/api/suclient/socio%40ejemplo.cl" \
  -H "Authorization: Bearer $PAYKU_PUBLIC_TOKEN" \
  -H "Sign: <firma de /api/suclient/socio@ejemplo.cl>" \
  -H "Accept: application/json"

# 2) Si no existe, crear
curl -X POST "https://des.payku.cl/api/suclient" \
  -H "Authorization: Bearer $PAYKU_PUBLIC_TOKEN" \
  -H "Sign: <firma>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "socio@ejemplo.cl",
    "name": "Ana Pérez",
    "rut": "111111111",
    "phone": "912345678",
    "additional_parameters": { "techo_person_id": "P-000123" }
  }'
```

⚠️ Cómo se firma un path con email (¿con `@` o con `%40`?) no está documentado. 💡 Firma el path exactamente como lo envías. Validar (Q-03).

## 6. Ejemplo de response

```json
{ "status": "active", "id": "cl0be4c8e623c167bc8b777", "email": "socio@ejemplo.cl", "name": "Ana Pérez", "created_at": "2026-10-12", "subcriptions": null }
```

## 7. Cómo implementarlo en backend 💡

```python
def ensure_payku_customer(person: Person) -> str:
    mapping = repo.get_payku_client_map(person.id)
    if mapping:
        return mapping.payku_client_id

    existing = payku.customers.get(person.email)          # None si no existe (404 o status=failed)
    if existing:
        repo.save_payku_client_map(person.id, existing["id"], person.email, source="found")
        return existing["id"]

    created = payku.customers.create(
        email=person.email, name=person.full_name, phone=person.phone_e164_local,
        rut=person.rut_sin_puntos, additional_parameters={"techo_person_id": person.id},
    )
    repo.save_payku_client_map(person.id, created["id"], person.email, source="created")
    return created["id"]
```

- Envolver en un **lock por persona** (o por email) para que dos requests simultáneos no creen dos clientes.
- Ante timeout del POST: **volver a buscar por email** antes de reintentar.

## 8. Qué datos guardar
`payku_cliente_map`: `persona_id`, `payku_client_id`, `email_al_vincular`, `created_at`, `source` (`found`/`created`), `environment`. Respuesta cruda en `stg_payku_api_call_log`.

## 9. Consideraciones importantes
- ⚠️ Unicidad del email en Payku no confirmada.
- ⚠️ No sabemos cómo responde "Obtener cliente" cuando no existe (no hay ejemplo de 404): manejar HTTP 404 **y** HTTP 200 con `status: failed`.
- El límite "máx. 20 caracteres" del path parece no aplicar al email; validar (Q-10).
