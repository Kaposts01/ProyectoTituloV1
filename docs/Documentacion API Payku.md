# Integracion Payku

## Alcance en este proyecto

La integracion activa es exclusivamente de lectura y alimenta staging local. El sincronizador consulta clientes, planes, suscripciones y transacciones mediante `GET`; no crea pagos, suscripciones, anulaciones ni movimientos de wallet.

El cliente usa la URL y las credenciales configuradas en `.env`:

- `PAYKU_BASE_URL`
- `PAYKU_API_KEY`
- `PAYKU_SECRET_KEY`
- `PAYKU_TIMEOUT_SECONDS`

La clave API se envia como `Authorization: Bearer` y las consultas incluyen la cabecera `Sign`, calculada con HMAC SHA-256. Las credenciales no se documentan, registran ni devuelven por la API local.

## Recursos sincronizados

| Recurso staging | Consulta Payku | Estado |
| --- | --- | --- |
| `client` | `/api/suclient/customers` | Validado localmente |
| `plan` | `/api/suplan/plans` | Validado localmente |
| `subscription` | `/api/sususcription` | Validado localmente |
| `transaction` | `/api/transaction` | Pendiente: excede el timeout local predeterminado |

Las listas de clientes, suscripciones y transacciones se solicitan con `page` y `per_page`; los planes se consultan sin paginacion. Las respuestas se guardan en `source_records` con la fuente `payku`.

## Operacion

Con la base de datos disponible y las migraciones aplicadas, ejecuta:

```powershell
.\.venv\Scripts\python.exe scripts\sync_payku.py
```

Si la coleccion de transacciones demora mas de 30 segundos, incrementa `PAYKU_TIMEOUT_SECONDS` en `.env` y vuelve a ejecutar. No reduzcas el alcance de lectura ni uses endpoints de escritura para resolver el timeout.

## Referencia externa y seguridad

La documentacion oficial se encuentra en `https://docs.payku.com/`. Se conserva fuera de este repositorio porque incluye operaciones que no forman parte del CRM read-only.

No agregues ejemplos de tarjetas, CVV/CVC, tokens, firmas ni claves privadas a este documento o a otros archivos versionados.
