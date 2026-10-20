# Flujo: suspender / reactivar una suscripción

## 1. Qué necesitamos hacer
Entender cuándo una suscripción queda `suspended` y cómo sale de ese estado.

## 2. Endpoint necesario

**No existe un endpoint para suspender ni para reactivar.** ✅ (no aparece en la documentación oficial)

| Acción | ¿Por API? | Cómo ocurre |
|---|---|---|
| Suspender | ❌ | Payku la suspende, por ejemplo "por máximos intentos de cobros realizados". ✅ ⚠️ Otros motivos no documentados. |
| Reactivar | ❌ directo / ✅ indirecto | El cliente inscribe una **nueva tarjeta** (`POST /api/suinscriptionscards`) → Payku "podrá revisar los pagos pendientes, hacer el cargo correspondiente y **activar automáticamente** la suscripción". ✅ |
| Pausar a petición del socio | ❌ | No hay mecanismo. 💡 Alternativas abajo. |

## 3. Recurso involucrado
Suscripción (`status`/`estatus` = `suspended`) y sus cobros (`retry`, `maximum attempt limit`).

## 4. Cómo detectar una suspensión
- Webhook `url_notify_suscription` con `status: suspended` (⚠️ no confirmado que se envíe).
- Barrido V3: `estatus == "suspended"`.
- `logs.status[]` con `final_status: "suspended"` y su `change_date`.
- Señal temprana: cobros con `try_number > 1` en V3 o `retry` en la lista A.

## 5. Ejemplo — reactivar vía nueva tarjeta

```json
POST /api/suinscriptionscards
{ "suscription": "sucaab7865dceaff49d8b3" }
```

```json
{ "status": "success", "id": "sucaab7865dceaff49d8b3", "url": "https://des.payku.cl/gateway/registrosuscripcion?plan=true&token=246&validacion=d6b32" }
```

## 6. Qué pasa después
Cuando el socio completa la `url`: Payku puede cobrar los ciclos atrasados y dejar la suscripción `active`. ✅ Confirmar con `GET /api/sususcription/{id}`.

## 7. Cómo implementarlo en backend 💡
1. Al detectar `suspended`: estado `SUSPENDIDA`, motivo = último estado de cobro (p. ej. `maximum attempt limit`).
2. Disparar comunicación al socio con un link de `suinscriptionscards` (ver [update-card.md](update-card.md)).
3. Avisar en el mensaje que **se pueden cobrar meses atrasados**.
4. Barrido diario de suscripciones `SUSPENDIDA` para detectar reactivación aunque se pierda el webhook.

## 8. Qué datos guardar
Fecha de suspensión (de `logs.status[].change_date`), motivo, intentos (`try_number`), fecha y canal de contacto al socio, fecha de reactivación.

## 9. Consideraciones importantes
- ⚠️ Número máximo de intentos y calendario de reintentos: **no documentados**.
- ⚠️ No sabemos cuánto tiempo puede estar `suspended` antes de pasar a otro estado (`cancel`/`finish`?).
- 💡 **"Pausa" pedida por el socio:** las únicas opciones son (a) dar de baja y crear una suscripción nueva después, o (b) acordar con Payku si su panel ofrece pausa. No simular una pausa eliminando la tarjeta: genera rechazos y una suspensión "sucia".
