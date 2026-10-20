# Sandbox: datos de prueba

> Fuente: https://virtualpos.readme.io/reference/datos-de-prueba-sandbox · Verificado: 2026-10-12

- Base URL: `https://api.virtualpos-sandbox.com`
- Portal (llaves `api_key` / `secret_key`): `https://comercios.virtualpos-sandbox.com` → Perfil > Configuración de cuenta > Integración
- Checkout sandbox: `https://pay.virtualpos-sandbox.com/...`

## Tarjetas

| Tipo | Número | Datos | Resultado |
| --- | --- | --- | --- |
| Crédito VISA | `4051 8856 0044 6623` | CVV `123`, cualquier vencimiento | ✅ Aprobada |
| Crédito AMEX | `3700 0000 0002 032` | CVV `1234`, cualquier vencimiento | ✅ Aprobada |
| Crédito MASTERCARD | `5186 0595 5959 0568` | CVV `123`, cualquier vencimiento | ❌ Rechazada |
| Débito | `4051 8842 3993 7763` | — | ✅ Aprobada |
| Débito | `5186 0085 4123 3829` | — | ❌ Rechazada |
| Prepago VISA | `4051 8860 0005 6590` | CVV `123`, cualquier vencimiento | ✅ Aprobada |
| Prepago MASTERCARD | `5186 1741 1062 9480` | CVV `123`, cualquier vencimiento | ❌ Rechazada |

**Simulador de banco** (formulario RUT + clave): RUT `11.111.111-1`, clave `123`.

## Casos de prueba sugeridos (**Recomendación**)

| # | Caso | Tarjeta | Esperado |
| --- | --- | --- | --- |
| 1 | Pago Web Checkout aprobado | VISA crédito | Payment `pagado`, webhook recibido |
| 2 | Pago rechazado | MASTERCARD crédito | Payment `rechazado`; reintento con el mismo `uuid` |
| 3 | Suscripción OK | VISA crédito | Suscription `ACTIVA`, `charge_program` creado |
| 4 | Suscripción con tarjeta rechazada | Débito `5186…3829` | `SUSCRIPCION_FALLIDA` (a verificar) |
| 5 | Cargo rechazado → link de cambio de tarjeta → reintento | MASTERCARD → VISA | Cargo `pagado` tras *Reintentar* |
| 6 | Idempotencia de cargo | — | Segundo *Crear Charge* con mismo `internal_code` → `E-086` (a verificar: el mensaje dice "utilizado para autorizar") |
| 7 | Webhook duplicado | — | Un solo registro en BD |

> Las tarjetas son de prueba públicas de VirtualPOS. Aun así, no las guardes en repos ni en la colección (la colección v2 usa variables).
