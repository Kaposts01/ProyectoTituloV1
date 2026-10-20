# Suscripción de consumo

Documentación oficial: https://docs.payku.com/cl/api/consumption-subscriptions/

**Autenticación:** `Bearer` + `Sign` ✅

---

## Qué es

"El conjunto de métodos que permitirán … la creación de clientes, planes, suscripciones y realizar transacciones de planes de consumo. El principal uso … es para realizar **cargos únicos** a un cliente por un servicio o producto." ✅

💡 Es lo mismo que la suscripción normal, pero **nosotros decidimos cuándo y cuánto cobrar** (con `POST /api/sutransaction`). Payku no cobra solo.

🎨 **Analogía:** es como dejar la tarjeta registrada en una app de delivery: cada pedido se cobra cuando ocurre, no todos los meses.

💡 **Para TECHO:** sirve si queremos cobrar montos distintos en fechas que decidimos nosotros (p. ej. aportes extraordinarios a socios que ya tienen tarjeta inscrita). Para la cuota mensual fija, conviene el plan de **monto fijo**.

---

## Endpoints

Son los mismos de la API de Suscripción (algunos con barra final en la documentación):

| Operación | Endpoint | Documento |
|---|---|---|
| Crear cliente | `POST /api/suclient` | [customers.md](customers.md) |
| Crear plan | `POST /api/suplan` | [plans.md](plans.md) |
| Crear suscripción | `POST /api/sususcription` | [subscriptions.md](subscriptions.md) |
| Crear transacción (cobro) | `POST /api/sutransaction` (+ `card`, `marketplace` opcionales) | [subscription-charges.md](subscription-charges.md#3-crear-cobro-planes-de-consumo) |
| Eliminar tarjeta | `POST /api/suscriptionsdeletecards` | [cards.md](cards.md) |

⚠️ La documentación escribe varias rutas con **barra final** (`/api/suclient/`, `/api/suplan/`, `/api/sususcription/`, `/api/sutransaction/`, `/api/suscriptionsdeletecards/`), pero los ejemplos cURL **no** la usan. Como la barra cambia la firma (`%2Fapi%2Fsuplan%2F` ≠ `%2Fapi%2Fsuplan`), usa **sin barra final**, igual que los ejemplos. Ver [postman.md](postman.md): algunos scripts antiguos de la colección firman con barra final.

---

## Diferencias respecto de la suscripción normal

| Tema | Suscripción (monto fijo) | Consumo |
|---|---|---|
| Quién dispara el cobro | Payku, automático (desde el mes siguiente) ✅ | Nosotros, con `sutransaction` ✅ |
| Monto | Definido por el plan (o `amount` en monto variable) | Lo enviamos en cada cobro (`amount`) ✅ |
| Elegir tarjeta | — | `card` = `identifier` de `active_cards` ✅ |
| Validación inicial de $50 | Sí ✅ | Sí (mismo endpoint de creación) ✅ |

---

## URL directa a la pasarela ✅

Para enviar al cliente directo a Webpay con sus datos ya cargados:

```text
https://BASE_URL/suscripcion/index?idplan=607&verif=b4280f5e&nombre=vicente&apellido=borjas&email=example@example.com&telefono=986523565&direct_full=true
```

Otros parámetros se concatenan con `&`. ✅
⚠️ No está documentado de dónde salen `idplan` (numérico, distinto del `pl…`) ni `verif`. 💡 Probablemente del panel de Payku (link del plan).
