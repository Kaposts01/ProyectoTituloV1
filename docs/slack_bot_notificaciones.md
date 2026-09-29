# Slack Bot de Notificaciones — Documentación de la API

> Referencia para implementar un bot que notifique acciones automáticas del CRM vía Slack.
> Fuente oficial: [docs.slack.dev](https://docs.slack.dev)

---

## Índice

1. [Opciones de integración](#1-opciones-de-integración)
2. [Crear la Slack App](#2-crear-la-slack-app)
3. [Incoming Webhooks (opción simple)](#3-incoming-webhooks-opción-simple)
4. [Web API — chat.postMessage (opción completa)](#4-web-api--chatpostmessage-opción-completa)
5. [Formatear mensajes con Block Kit](#5-formatear-mensajes-con-block-kit)
6. [Programar mensajes](#6-programar-mensajes)
7. [Mensajes efímeros](#7-mensajes-efímeros)
8. [Instalación de dependencias Python](#8-instalación-de-dependencias-python)
9. [Rate limits y errores comunes](#9-rate-limits-y-errores-comunes)
10. [Ejemplos para el CRM](#10-ejemplos-para-el-crm)

---

## 1. Opciones de integración

| Método | Cuándo usarlo | Complejidad |
|---|---|---|
| **Incoming Webhook** | Notificaciones simples, sin necesidad de leer canales | Baja |
| **Web API (`chat.postMessage`)** | Hilos, mensajes enriquecidos, gestión de canales | Media |
| **Bolt Framework** | Bots interactivos con botones/modales | Alta |

**Recomendación para este CRM:** Empezar con Incoming Webhooks para alertas automáticas; migrar a `chat.postMessage` si se necesitan hilos o respuestas interactivas.

---

## 2. Crear la Slack App

### Paso 1 — Ir al portal de apps
```
https://api.slack.com/apps
```
Clic en **"Create New App"** → **"From scratch"** → dar nombre y seleccionar workspace.

### Paso 2 — Añadir scopes (para Web API)
En el menú lateral: **OAuth & Permissions** → sección **Bot Token Scopes**:

| Scope | Para qué sirve |
|---|---|
| `chat:write` | Enviar mensajes como el bot |
| `chat:write.public` | Enviar a canales públicos sin ser miembro |
| `chat:write.customize` | Personalizar nombre/ícono del bot |
| `channels:read` | Listar canales disponibles |
| `incoming-webhook` | Para flujo OAuth con webhooks |

### Paso 3 — Instalar en el workspace
**OAuth & Permissions** → **"Install to Workspace"** → autorizar.

### Paso 4 — Copiar el Bot Token
Después de instalar, aparece el **Bot User OAuth Token**:
```
xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
```
Guardar como variable de entorno `SLACK_BOT_TOKEN`.

---

## 3. Incoming Webhooks (opción simple)

### Habilitación
1. En la configuración de tu app: **Incoming Webhooks** → activar.
2. Clic en **"Add New Webhook to Workspace"**.
3. Seleccionar canal destino → **Authorize**.
4. Copiar la URL generada:

```
https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX
```

> **Seguridad:** nunca subas esta URL a git. Usar variable de entorno `SLACK_WEBHOOK_URL`.

### Enviar mensaje con cURL
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Hola desde el CRM!"}' \
  "$SLACK_WEBHOOK_URL"
```

### Enviar mensaje con Python
```python
import os
from slack_sdk.webhook import WebhookClient

webhook = WebhookClient(os.environ["SLACK_WEBHOOK_URL"])

response = webhook.send(text="Hola desde el CRM!")
assert response.status_code == 200
assert response.body == "ok"
```

### Enviar mensaje enriquecido (Block Kit)
```python
response = webhook.send(
    text="Reporte de sincronización",  # fallback para notificaciones
    blocks=[
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Reporte de Sincronización"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Fecha:*\n2026-09-20"},
                {"type": "mrkdwn", "text": "*Estado:*\n✅ Exitoso"}
            ]
        }
    ]
)
```

### Limitaciones de Webhooks
- No se pueden borrar mensajes publicados vía webhook.
- No se puede cambiar canal, nombre de usuario ni ícono (usa la config de la app).
- Sin acceso a historial ni respuestas en hilos (para eso usar Web API).

---

## 4. Web API — chat.postMessage (opción completa)

**Endpoint:**
```
POST https://slack.com/api/chat.postMessage
```

**Headers requeridos:**
```
Authorization: Bearer xoxb-your-token
Content-Type: application/json
```

### Parámetros principales

| Parámetro | Tipo | Requerido | Descripción |
|---|---|---|---|
| `channel` | string | Sí | ID del canal (`C123ABC`) o nombre (`#canal`) |
| `text` | string | No* | Texto del mensaje (máx. 4.000 caracteres) |
| `blocks` | array | No | Bloques Block Kit para mensajes enriquecidos |
| `thread_ts` | string | No | Timestamp del mensaje padre (para responder en hilo) |
| `reply_broadcast` | boolean | No | Mostrar respuesta también en el canal |
| `username` | string | No | Nombre personalizado del bot |
| `icon_emoji` | string | No | Emoji como ícono (ej: `:bar_chart:`) |
| `icon_url` | string | No | URL de imagen como ícono |
| `mrkdwn` | boolean | No | Habilitar markdown (default: `true`) |

> *`text` o `blocks` debe estar presente.

### Ejemplo con cURL
```bash
curl -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "C123ABC456",
    "text": "Nueva sincronización completada"
  }'
```

### Ejemplo con Python (slack_sdk)
```python
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

try:
    response = client.chat_postMessage(
        channel="C123ABC456",
        text="Nueva sincronización completada"
    )
    ts = response["ts"]  # timestamp para responder en hilo
except SlackApiError as e:
    print(f"Error: {e.response['error']}")
```

### Response exitoso
```json
{
  "ok": true,
  "channel": "C123ABC456",
  "ts": "1503435956.000247",
  "message": {
    "text": "Nueva sincronización completada",
    "bot_id": "B123ABC456",
    "type": "message",
    "subtype": "bot_message",
    "ts": "1503435956.000247"
  }
}
```

### Responder en un hilo
```python
response = client.chat_postMessage(
    channel="C123ABC456",
    thread_ts="1503435956.000247",
    text="Detalle del error en el registro #4521"
)
```

---

## 5. Formatear mensajes con Block Kit

Block Kit permite construir mensajes visuales con secciones, tablas, botones e imágenes. Límite: **50 bloques por mensaje**.

> **Importante:** incluir siempre el campo `text` de nivel superior como fallback para notificaciones push y lectores de pantalla.

### Tipos de bloques

| Tipo | Descripción |
|---|---|
| `header` | Título grande en la parte superior |
| `section` | Texto con soporte markdown + campo accessory opcional |
| `divider` | Línea separadora horizontal |
| `image` | Imagen con título y texto alternativo |
| `actions` | Fila de botones interactivos |
| `context` | Texto pequeño / metadata al pie |
| `rich_text` | Texto enriquecido con listas, código, citas |

### Estructura base
```json
{
  "channel": "C123ABC456",
  "text": "Resumen del reporte (fallback)",
  "blocks": [
    { "type": "BLOQUE_1" },
    { "type": "BLOQUE_2" }
  ]
}
```

### Ejemplo de mensaje de reporte
```python
client.chat_postMessage(
    channel="#crm-alertas",
    text="Reporte de sincronización TCH",
    blocks=[
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":bar_chart: Reporte de Sincronización TCH"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Fecha:*\n2026-09-20"},
                {"type": "mrkdwn", "text": "*Registros procesados:*\n3.842"},
                {"type": "mrkdwn", "text": "*Estado:*\n✅ Exitoso"},
                {"type": "mrkdwn", "text": "*Duración:*\n2m 14s"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Generado automáticamente por el CRM"
                }
            ]
        }
    ]
)
```

### Herramienta visual
Usar el **Block Kit Builder** oficial para diseñar bloques visualmente:
```
https://app.slack.com/block-kit-builder
```

---

## 6. Programar mensajes

```python
import time

client.chat_scheduleMessage(
    channel="#crm-alertas",
    post_at=int(time.time()) + 3600,  # en 1 hora
    text="Recordatorio: revisar sincronización de la noche"
)
```

- `post_at`: timestamp Unix (entero).
- Máximo 120 días hacia el futuro.
- Scope requerido: `chat:write`.

### Listar mensajes programados
```python
client.chat_scheduledMessages_list(channel="C123ABC456")
```

### Cancelar un mensaje programado
```python
client.chat_deleteScheduledMessage(
    channel="C123ABC456",
    scheduled_message_id="Q1234567890"
)
```

---

## 7. Mensajes efímeros

Solo visibles para un usuario específico. Útiles para confirmaciones o errores que no deben ver todos.

```python
client.chat_postEphemeral(
    channel="C123ABC456",
    user="U123ABC456",
    text="Solo tú puedes ver este mensaje de error."
)
```

Scope requerido: `chat:write`.

---

## 8. Instalación de dependencias Python

```bash
pip install slack_sdk python-dotenv
```

### Variables de entorno recomendadas
```bash
# .env (nunca en git — añadir a .gitignore)
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxx
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
SLACK_CHANNEL_ID=C123ABC456
```

### Uso con python-dotenv
```python
from dotenv import load_dotenv
import os

load_dotenv()

SLACK_TOKEN = os.environ["SLACK_BOT_TOKEN"]
CHANNEL = os.environ["SLACK_CHANNEL_ID"]
```

---

## 9. Rate limits y errores comunes

### Rate limits de la Web API
- **Tier 3** (métodos de mensajería): ~50 requests/minuto por workspace.
- Respuesta HTTP `429` cuando se supera el límite; incluye header `Retry-After`.

```python
import time
from slack_sdk.errors import SlackApiError

try:
    client.chat_postMessage(channel=CHANNEL, text="Mensaje")
except SlackApiError as e:
    if e.response["error"] == "ratelimited":
        retry_after = int(e.response.headers.get("Retry-After", 1))
        time.sleep(retry_after)
```

### Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `channel_not_found` | ID de canal inválido o bot no está en el canal | Invitar el bot al canal |
| `not_in_channel` | Bot no es miembro del canal | Invitar manualmente o usar `chat:write.public` |
| `missing_scope` | Token sin el scope necesario | Añadir scope en OAuth & Permissions y reinstalar |
| `invalid_auth` | Token incorrecto o expirado | Regenerar token |
| `no_text` | Ni `text` ni `blocks` en el payload | Incluir al menos uno |
| `rate_limited` | Demasiadas requests por minuto | Respetar `Retry-After` |
| `invalid_payload` | JSON malformado | Validar estructura JSON |
| `channel_is_archived` | Canal archivado | Usar canal activo |
| `invalid_token` (webhook) | URL de webhook expirada o inválida | Regenerar webhook en la app |
| `no_service` (webhook) | Webhook deshabilitado o removido | Reactivar en configuración de la app |

---

## 10. Ejemplos para el CRM

### Alerta de sincronización completada
```python
from datetime import datetime
from slack_sdk import WebClient
import os

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

def notificar_sync_completada(registros: int, duracion_s: float, errores: int):
    emoji = "✅" if errores == 0 else "⚠️"
    client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        text=f"{emoji} Sincronización TCH completada: {registros:,} registros",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} Sincronización TCH"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Registros:*\n{registros:,}"},
                    {"type": "mrkdwn", "text": f"*Duración:*\n{duracion_s:.1f}s"},
                    {"type": "mrkdwn", "text": f"*Errores:*\n{errores}"},
                    {"type": "mrkdwn", "text": f"*Fecha:*\n{datetime.now():%Y-%m-%d %H:%M}"},
                ]
            }
        ]
    )
```

### Alerta de error crítico
```python
def notificar_error(operacion: str, error: str):
    client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        text=f"❌ Error en {operacion}",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"❌ Error en {operacion}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Mensaje:*\n```{error}```"}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"CRM · {datetime.now():%Y-%m-%d %H:%M:%S}"}
                ]
            }
        ]
    )
```

### Reporte diario con APScheduler
```python
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

@scheduler.scheduled_job("cron", hour=8, minute=0)
def reporte_diario():
    notificar_sync_completada(registros=5_000, duracion_s=45.2, errores=0)

scheduler.start()
```

---

## Referencias oficiales

- [Envío y programación de mensajes](https://docs.slack.dev/messaging/sending-and-scheduling-messages)
- [Referencia: chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage)
- [Incoming Webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)
- [Block Kit](https://docs.slack.dev/block-kit/)
- [Block Kit Builder (visual)](https://app.slack.com/block-kit-builder)
- [Python SDK (slack_sdk)](https://docs.slack.dev/tools/python-slack-sdk/)
- [Portal de apps Slack](https://api.slack.com/apps)
