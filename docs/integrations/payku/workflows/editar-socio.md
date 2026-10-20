# Flujo: editar los datos de un socio (adaptador Payku)

**Objetivo:** aplicar en Payku los cambios de **nombre, email y teléfono** que ya se guardaron en nuestra base, y dejar registrado lo que Payku no permite cambiar (el **RUT**).
**Recursos:** Cliente de suscripción (`cl…`) · **Postman:** carpeta `02 · Editar socio`
**Relacionados:** [capa común editar-socio](../../../../Transversal/docs/transversal/workflows/editar-socio.md) · [customers.md](../customers.md) · [create-customer.md](create-customer.md)

## 1. Qué se puede editar

`PUT /api/suclient/{identificadorCliente}` ✅ (el path también acepta el email ✅). Todos los campos del body son opcionales.

| Dato | Campo | ¿Editable? | Respaldo |
| --- | --- | --- | --- |
| Nombre | `name` (máx. 80) | ✅ | Body oficial de *Actualizar cliente* |
| Email | `email` (máx. 50) | ✅ | Body oficial (la doc lo describe por error como "Nombre del cliente") |
| Teléfono | `phone` (máx. 20) | ✅ | Body oficial |
| **RUT** | `rut` | ❌ | **No aparece** en el body de *Actualizar cliente*; solo existe al crear ✅ |
| Dirección | `address`, `country`, `region`, `city`, `postal_code` | ✅ | Fuera del alcance de este flujo |
| Nuestro ID | `additional_parameters` | ✅ | ⚠️ No documentado si se reemplaza o se mezcla: no tocarlo en este flujo |

**La suscripción no tiene endpoint de edición** ✅. Su detalle incluye un objeto `client` ⚠️ (no documentado si es una referencia viva al cliente o una copia: Q-30).

## 2. Flujo

```text
PASO 1 · Estado actual                           GET /api/suclient/{cl…}          ← siempre por ID, nunca por email
↓  Diff entre nuestra base y Payku (solo name, email, phone)
↓  └─ Sin diferencias → APLICADO (nada que enviar)
↓
PASO 2 · Si cambia el email: normalizar y verificar disponibilidad
↓  Normalizar a minúsculas ANTES de enviar (Payku distingue mayúsculas; un email en mayúsculas
↓  puede crear un duplicado visual de uno existente en minúsculas)
↓  GET /api/suclient/{email_nuevo_lowercase}
↓  ├─ Devuelve OTRO cl… → frenar: ERROR de unicidad → revisión de duplicados  (⚠️ unicidad no documentada: Q-18)
↓  └─ No existe (404 o status: failed) → seguir
↓
PASO 3 · Actualizar                              PUT /api/suclient/{cl…}  (solo los campos que cambian)
↓  Ojo: cada campo enviado entra en la firma Sign
↓  └─ HTTP 200 con status: failed → ERROR (no es éxito)
↓
PASO 4 · Confirmar                               GET /api/suclient/{cl…}
↓  Comparar name, email, phone con lo enviado → APLICADO por campo
↓  Si cambió el email → actualizar payku_cliente_map.email_al_vincular
↓
PASO 5 · ¿Se ve en la suscripción?               GET /api/sususcription/{su…}   (solo hasta resolver Q-30)
↓  client.email / client.name / client.phone ¿cambiaron?
↓  ├─ Sí → la suscripción referencia al cliente: listo
↓  └─ No → registrar: la suscripción guarda una copia (anotar en open-questions.md)
↓
PASO 6 · RUT
↓  Si el cambio incluye RUT → resultado MANUAL: tarea "pedir a soporte de Payku corregir el RUT de cl…"
↓
RESULTADO: {name, email, phone: APLICADO | ERROR, rut: MANUAL}
```

## 3. Request

```json
PUT /api/suclient/cl0be4c8e623c167bc8b777
{ "name": "Ana Pérez Soto", "email": "ana.nuevo@mail.com", "phone": "987654321" }
```

**Respuesta (resumida):** el cliente completo, con `update_at` lleno (ej. `"2023-10-2 08:32:52"`, sin cero a la izquierda en el día) ✅.

## 4. Implementación (Python, referencia)

```python
CAMPOS = {"nombre": "name", "email": "email", "telefono": "phone"}

class EditarSocioPayku:
    def actualizar(self, socio, cambios: dict) -> dict:
        cl = repo.payku_cliente_map.get(socio.id)
        if not cl:
            return {}                                                    # el socio no está en Payku
        resultado = {}
        if "rut" in cambios:
            resultado["rut"] = "MANUAL"                                  # no está en el body de Actualizar cliente
            tareas.crear("payku", socio.id, f"Pedir a soporte de Payku corregir el RUT de {cl.payku_client_id}")

        actual = payku.get(f"/api/suclient/{cl.payku_client_id}")
        # Normalizar email a minúsculas antes de comparar y enviar
        if "email" in cambios:
            cambios["email"] = cambios["email"].strip().lower()
        body = {CAMPOS[k]: v for k, v in cambios.items() if k in CAMPOS and actual.get(CAMPOS[k]) != v}
        if not body:
            return resultado | {k: "APLICADO" for k in cambios if k in CAMPOS}

        if "email" in body:
            otro = payku.get(f"/api/suclient/{body['email']}", allow_404=True)
            if otro and otro.get("status") != "failed" and otro.get("id") != cl.payku_client_id:
                return resultado | {k: "ERROR" for k in cambios if k in CAMPOS} | {"_conflicto": otro["id"]}

        r = payku.put(f"/api/suclient/{cl.payku_client_id}", body)      # firma Sign sobre el body enviado
        if r.get("status") == "failed":
            raise ErrorPayku(r)

        nuevo = payku.get(f"/api/suclient/{cl.payku_client_id}")
        for k, campo in CAMPOS.items():
            if k in cambios:
                resultado[k] = "APLICADO" if nuevo.get(campo) == cambios[k] else "ERROR"
        if resultado.get("email") == "APLICADO":
            repo.payku_cliente_map.update(socio.id, email_al_vincular=cambios["email"])
        return resultado

    def verificar(self, socio) -> dict:
        cl = repo.payku_cliente_map.get(socio.id)
        c = payku.get(f"/api/suclient/{cl.payku_client_id}")
        return {k: c.get(campo) == getattr(socio, k) for k, campo in CAMPOS.items()}
```

## 5. Errores

| Paso | Error / estado | Qué hacer |
| --- | --- | --- |
| Todos | HTTP 200 con `status: failed` | Es un error ✅: revisar siempre `status` |
| Todos | `401` | Firma `Sign` mal calculada: en un `PUT` firman todos los campos del body (Q-01, Q-03) |
| 2 | El email nuevo ya es de otro cliente | Frenar y revisar duplicados (dos fichas de la misma persona) |
| 3 | `400` de validación | Largo máximo: `name` 80, `email` 50, `phone` 20 |
| 6 | Cambio de RUT | `MANUAL`: soporte de Payku. Mientras tanto, los reportes de Payku muestran el RUT anterior |

## 6. Consideraciones

- **Siempre usar el ID (`cl…`) en el path**, no el email: si se está cambiando el email, buscar por el anterior o por el nuevo es ambiguo, y un email en el path tiene la duda de firma Q-03.
- **Normalizar el email a minúsculas** antes de comparar con Payku y antes de enviar en el `PUT`. Payku podría distinguir mayúsculas y crear duplicados visuales si se guardan emails con distinta capitalización.
- **No enviar `rut`** en el `PUT`: no está documentado y podría ignorarse en silencio o fallar.
- Los avisos de Payku (comprobantes, links de inscripción) usan el email del cliente: por eso conviene que quede al día.
- `additional_parameters` no se toca en este flujo (comportamiento de reemplazo o mezcla no documentado).

## 7. Probarlo en Postman

Carpeta **`02 · Editar socio`** de `Payku API v2.postman_collection.json` (sandbox), para **Run folder**:

| Request | Qué hace | Siguiente |
| --- | --- | --- |
| EP-1 Obtener cliente | Lee `client_id` y arma el body solo con lo que cambia (`edit_name`, `edit_email`, `edit_phone`) | Sin cambios → FIN · Cambia email → EP-2 · Otro → EP-3 |
| EP-2 Verificar email libre | ¿El email nuevo es de otro cliente? | Libre → EP-3 · Ocupado → **FIN** |
| EP-3 Actualizar cliente | `PUT` con el body armado (`edit_body`) | EP-4 |
| EP-4 Confirmar en el cliente | Compara lo guardado con lo enviado | EP-5 si hay `subscription_id` · FIN |
| EP-5 ¿Se ve en la suscripción? (Q-30) | Compara `client` de la suscripción | FIN |

**Variables de entorno:** `client_id`, `subscription_id` (opcional) y los valores nuevos `edit_name`, `edit_email`, `edit_phone` (vacío = no cambia). Los scripts llenan `edit_body` y `edit_before`.
