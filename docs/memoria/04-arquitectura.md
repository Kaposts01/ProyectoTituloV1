# Capítulo 4. Arquitectura del sistema

> **Estado:** borrador S6 (DOC-14), revisable. Sin datos personales. Lo dudoso se marca [verificar].
> **Fuentes:** `docs/architecture/overview.md`, `docs/architecture/data-flow.md`, `docs/architecture/database.md`,
> `docs/architecture/integrations.md`, `docs/architecture/security.md`, `docs/data/webhooks.md`,
> `docs/data/sync-idempotency.md`, ADR-001 y el código de `app/` y `frontend/` en `master` (commit `248d515`).

## 4.1 Propósito del capítulo

Este capítulo describe la arquitectura del CRM desarrollado (en adelante, el sistema), cuyo objetivo es centralizar la
información de socios y donantes que hoy está repartida entre cuatro canales de recaudación: tres pasarelas de pago
con API (VirtualPOS, Toku y Payku) y un canal de débito bancario que solo entrega reportes en planillas Excel (TCH).
Se presentan los atributos de calidad que guiaron el diseño, la vista lógica por capas, la vista de procesos (cómo y
cuándo fluyen los datos), la vista de despliegue y las decisiones arquitectónicas principales con sus alternativas.

## 4.2 Atributos de calidad que guían el diseño

El diseño se rige por cinco atributos de calidad, derivados de las restricciones del dominio y de las decisiones
registradas en `docs/tasks.md` §1.5:

1. **Integridad y trazabilidad del dato.** Todo dato del modelo central debe poder rastrearse hasta el identificador
   externo del proveedor y, cuando existe, hasta el registro crudo que lo originó. PostgreSQL es la única fuente de
   verdad de persistencia (`docs/architecture/database.md`).
2. **Idempotencia.** Repetir una sincronización, una consolidación o el procesamiento de un aviso no debe duplicar ni
   alterar datos. Es la propiedad que permite reintentar sin miedo ante fallas de red o de proveedor
   (`docs/data/sync-idempotency.md`).
3. **Seguridad de las operaciones con efectos.** Las lecturas a proveedores son la norma; las escrituras (crear un
   cobro, cancelar una suscripción) son excepcionales, requieren autorización explícita y quedan registradas. Un error
   en este punto tiene consecuencias económicas directas sobre los socios.
4. **Protección de datos personales.** El sistema maneja RUT, correos y datos de tarjeta parciales. Se minimiza lo que
   se almacena (nunca número completo de tarjeta ni código de seguridad) y lo que se registra en bitácoras.
5. **Independencia del proveedor.** Ningún proveedor comparte contrato con otro: cada uno tiene su autenticación,
   paginación, estados y particularidades. El modelo central no debe depender de la forma de ninguno.

La disponibilidad y la escalabilidad horizontal tienen menor prioridad en esta etapa: el sistema opera de forma local
en un equipo que actúa como servidor (decisión d155), y el hosting con alta disponibilidad queda como trabajo futuro.

## 4.3 Vista general: arquitectura por capas

La arquitectura sigue un patrón de canalización de datos en capas, inspirado en los enfoques de *staging* y
*data warehouse*, combinado con una aplicación web transaccional clásica:

```text
Proveedores externos (VirtualPOS x2, Toku, Payku)        Reportes Excel (TCH y reportes descargados)
        |  conectores HTTP (solo GET en la sincronización)        |  importación administrativa
        v                                                         v
  Capa Raw: source_records (payload saneado, clave (source, resource_type, external_id))
        |
        v
  Capa de canal: tablas por proveedor (vp_*, tk_*, p_*, tch_*, *_report_*)
        |  consolidación (channel_consolidation)      |  ETL Core (core_*_etl)
        v                                             v
  Modelo centralizado operativo                 Modelo Core aditivo
  (clients, subscriptions, charges, payments)   (core_clients, external_identities,
        |                                         core_subscriptions, core_charges, core_payments)
        v                                             v
  API interna FastAPI (/api/v1) con sesión, CSRF y permisos
        |
        v
  Interfaz React/Vite (dashboards, fichas, recuperador, operaciones gestionadas)
```

Cada capa tiene una responsabilidad acotada:

- **Conectores** (`app/integrations/virtualpos/`, `app/integrations/toku/`, `app/integrations/payku/`). Encapsulan la
  autenticación, la firma de solicitudes y los reintentos de cada proveedor. Los reintentos comunes viven en
  `app/integrations/http_retry.py` y se aplican **solo a lecturas idempotentes**: un `POST` o un `GET` con efectos no
  se reintenta, porque tras un *timeout* el primer intento pudo haberse ejecutado.
- **Capa Raw** (`app/models/source_record.py`). Guarda la respuesta del proveedor ya saneada en una columna JSONB, con
  restricción de unicidad `(source, resource_type, external_id)`. La escritura se hace en lotes con
  `INSERT ... ON CONFLICT DO UPDATE ... WHERE` el contenido cambió (`app/services/source_record_store.py`), de modo que
  repetir la misma lectura no reescribe filas.
- **Capa de canal** (`app/models/vp.py`, `toku_channel.py`, `payku_channel.py`, `tch.py` y los modelos `*_report.py`).
  Proyecta el dato crudo a columnas tipadas propias de cada proveedor, sin forzar todavía un vocabulario común.
- **Capa centralizada.** Integra los canales bajo un vocabulario común (cliente, suscripción, cobro, pago). Hoy existen
  dos modelos centralizados que conviven (sección 4.6.3).
- **API interna** (`app/api/v1/router.py`, 23 routers). Es el único punto de contacto entre el navegador y los datos:
  el navegador nunca recibe credenciales de proveedores ni llama a sus APIs.
- **Interfaz** (`frontend/src/`). Aplicación de una sola página en React 19 con Vite y Recharts para gráficos,
  organizada por funcionalidades (`frontend/src/features/`: dashboard, virtualpos, toku, tch, recovery, billing,
  cancellations, charges, admin, entre otras).

## 4.4 Pila tecnológica

| Capa | Tecnología | Evidencia |
| --- | --- | --- |
| Backend | Python con FastAPI, Pydantic Settings | `requirements.txt`, `app/main.py`, `app/core/config.py` |
| Persistencia | PostgreSQL 17, SQLAlchemy 2, Alembic (68 revisiones a la fecha) | `compose.yaml`, `app/models/`, `alembic/versions/` |
| Clientes HTTP | httpx (asíncrono) | `app/integrations/*/client.py` |
| Tareas programadas | APScheduler con almacén de trabajos en PostgreSQL | `app/scheduler/engine.py` |
| Frontend | React 19, TypeScript, Vite, Recharts | `frontend/package.json` |
| Pruebas | pytest (unidad e integración), Vitest; suite de contrato separada para sandbox | `tests/`, `tests_contract/virtualpos/` |

La elección de FastAPI responde a la necesidad de combinar rutas síncronas de consulta con clientes HTTP asíncronos
hacia los proveedores y un canal de eventos al navegador (sección 4.5.4). PostgreSQL se eligió por su soporte de JSONB
(para la capa Raw), de `INSERT ... ON CONFLICT` (base de la idempotencia) y de bloqueos consultivos (para garantizar
un único ejecutor de sincronización).

## 4.5 Vista de procesos

### 4.5.1 Sincronización programada

La sincronización completa (`sync_all_channels`, `app/scheduler/jobs/sync_all.py`) corre cada noche a las 02:00, con
un reintento de los canales fallidos a las 04:00 (`app/scheduler/engine.py`). Sus pasos son:

1. **Exclusión mutua.** `app/scheduler/run_lock.py` crea la corrida en `etl_runs` bajo un bloqueo consultivo de
   PostgreSQL; si otra corrida está activa (nocturna, manual o importación de TCH), la nueva se omite o responde 409.
2. **Lectura por canal** hacia la capa Raw y la capa de canal. Las dos cuentas de VirtualPOS se leen por separado.
3. **Consolidación** de todos los canales sincronizados hacia el modelo operativo, una sola vez al final
   (`app/services/channel_consolidation.py`).
4. **ETL Core** por canal (`run_vp_core_etl`, `run_toku_core_etl`, `run_payku_core_etl`), solo para los canales que
   sincronizaron y consolidaron sin error; un fallo deja la corrida como parcial.
5. **Métricas** por fase y recurso, guardadas sin datos personales (`docs/data/sync-idempotency.md`, SYNC-O-01).

Existe además un esquema por niveles «caliente, tibio y frío» (`app/scheduler/jobs/sync_tiers.py`, decisión D10):
lecturas por ventana de fecha cada tres horas en horario diurno, la corrida diaria y una relectura completa semanal.
Está implementado pero **apagado por defecto** detrás de banderas (`SYNC_TIERS_ENABLED`,
`SYNC_WINDOWED_READS_ENABLED`), porque depende de que los filtros de fecha de cada proveedor funcionen como dicen, lo
que no está confirmado para todos (capítulo 11).

### 4.5.2 Reconciliación dirigida

Una sincronización completa toma entre 1,9 y 2,8 horas (`app/services/targeted_reconcile.py`). Para reflejar antes
los cambios probables, un trabajo horario relee solo las suscripciones en «ventana de riesgo»: con un cobro programado
reciente, un rechazo reciente o un cobro pendiente vencido. La relectura usa `refresh_subscription`
(`app/services/subscription_refresh.py`), que solo hace `GET`, falla de forma cerrada y es idempotente.

### 4.5.3 Webhooks

Los receptores de avisos (`app/api/v1/routes/webhooks_toku.py`, `webhooks_virtualpos.py`, `webhooks_payku.py`) siguen
un diseño de **cola con relectura**:

```text
Proveedor --POST--> receptor --> webhook_events (pending) --> procesador (cada minuto)
                                                                   |
               status_change_events <-- consolidación de esa suscripción <-- refresh_subscription (solo GET)
```

El receptor valida (límite de tasa, secreto o firma cuando el proveedor la ofrece, tamaño máximo del cuerpo), enmascara
datos personales y encola con una clave de deduplicación única (`app/services/webhook_intake.py`). El procesador
(`app/services/webhook_processor.py`) toma lotes con `SELECT ... FOR UPDATE SKIP LOCKED`, de modo que dos procesos
nunca tomen el mismo evento, y relee el recurso afectado por API. **El contenido del aviso nunca se aplica
directamente**: solo indica qué recurso mirar. Esta decisión protege contra avisos falsificados en los canales que no
firman sus avisos y vuelve irrelevante el orden de llegada. A la fecha del borrador, el código está probado con
dobles de prueba, pero no hay webhooks registrados en ningún proveedor ni receptores expuestos a internet
(`docs/data/webhooks.md`).

### 4.5.4 Avisos al navegador en tiempo casi real

Para que la interfaz refleje los cambios sin recargar, el backend expone un flujo de eventos del servidor (SSE) en
`GET /api/v1/events/stream` (`app/api/v1/routes/events.py`, decisión D9). La fuente es la tabla
`status_change_events` (solo agregados de estado, sin datos personales), que el flujo relee cada cinco segundos; el
cliente se reconecta con `Last-Event-ID` y, si el flujo no está disponible, invalida su caché cada 60 segundos. Se
descartó WebSocket porque no hay mensajes del navegador al servidor y su manejo de conexión es más costoso.

### 4.5.5 Operaciones con efectos en los proveedores

Las escrituras (cambio de monto gestionado, cancelaciones, tareas manuales) siguen un camino distinto al de la
sincronización:

1. Se originan solo en rutas internas protegidas por sesión, token CSRF y permiso específico (`app/services/rbac.py`).
2. Pasan por una bandera local por proveedor, apagada por defecto (`VIRTUALPOS_WRITES_ENABLED`, `TOKU_WRITES_ENABLED`,
   `PAYKU_WRITES_ENABLED` en `app/core/config.py`).
3. Quedan registradas en `write_runs` (`app/models/write_run.py`).
4. En ambientes no productivos se agregan guardas duras; por ejemplo, Toku comparte el mismo host para pruebas y
   producción, por lo que `app/integrations/toku/write_guard.py` bloquea cualquier escritura que no cumpla las
   condiciones de prueba.

Los cambios de facturación de VirtualPOS (Opción A) se modelan además como solicitudes con flujo de aprobación
(`billing_change_requests` y sus eventos, `app/models/billing.py`), con trabajos programados de renovación, expiración
y verificación de consistencia.

## 4.6 Decisiones arquitectónicas principales

### 4.6.1 Separar la capa Raw del modelo central

**Decisión.** Persistir primero la respuesta saneada del proveedor y transformarla después.
**Alternativa descartada.** Transformar en memoria y escribir directo al modelo central.
**Justificación.** Permite reprocesar sin volver a llamar al proveedor (cuyas APIs tienen límites de tasa y, en el caso
de Payku, historial incompleto), auditar qué dijo el proveedor en cada momento (`source_record_observations` guarda un
hash por versión del contenido) y aislar los cambios de contrato del proveedor.

### 4.6.2 Identidad central con identidades externas (ADR-001)

**Decisión.** Cada socio del modelo Core tiene un identificador interno estable (`core_clients`) y se relaciona con sus
identidades externas por fuente (`external_identities`, única por `(source, resource_type, external_id)`). El RUT, el
correo y el teléfono son atributos y señales de comparación, no claves.
**Alternativas descartadas** (ADR-001): usar el RUT o el correo como clave primaria, o mantener registros por proveedor
sin identidad transversal.
**Justificación.** Un mismo RUT aparece con datos distintos en cada canal, puede venir mal digitado y no existe en todos
los proveedores; fusionar automáticamente por RUT produciría uniones erróneas difíciles de deshacer. El detector de
candidatos (`app/services/client_match_detector.py`) propone pares con evidencia de RUT válido o correo normalizado,
pero **no fusiona**: las fusiones son manuales, auditadas y reversibles. El flujo de revisión y fusión reversible está
parcialmente implementado (CORE-04).

### 4.6.3 Dos modelos centralizados en transición

El sistema mantiene hoy dos representaciones centralizadas:

- El **modelo operativo** (`clients`, `subscriptions`, `charges`, `payments`, `plans`, `payment_methods`;
  `app/models/crm.py`), alimentado por `app/services/channel_consolidation.py` y usado por la mayoría de las pantallas
  y los indicadores.
- El **modelo Core aditivo** (`core_*`; `app/models/core.py`), alimentado por los ETL `app/services/core_*_etl.py`,
  que agrega la identidad de ADR-001, los motivos de rechazo normalizados y las señales derivadas de reportes.

Esta coexistencia es una decisión de transición, no un objetivo: permitió introducir el modelo Core sin interrumpir la
operación. La materialización anterior (`app/services/crm_materialization.py`) está desactivada y conservada solo por
compatibilidad. La convergencia hacia un solo modelo queda como trabajo futuro [verificar con el plan vigente].

### 4.6.4 Lecturas por defecto, escrituras como excepción

Las sincronizaciones y el ETL solo hacen `GET`. Esta regla simplifica el razonamiento sobre fallas (una lectura
repetida es inocua) y acota el riesgo económico a un conjunto pequeño de rutas auditadas.

### 4.6.5 Ambientes por configuración

Un único archivo de configuración define el ambiente con `APP_ENV`. Con `APP_ENV=sandbox` o `qa`, la aplicación usa
exclusivamente las variables `*_SANDBOX_*` y una base de datos distinta (`SANDBOX_DATABASE_URL`), y la validación de
`app/core/config.py` rechaza combinaciones peligrosas (por ejemplo, una URL de sandbox con `APP_ENV=production`, o una
URL de producción con `APP_ENV=sandbox`). Una guarda adicional (`app/db/migration_guard.py`) impide revertir
migraciones sobre bases no seguras; nació de un incidente real en el que una reversión accidental dejó datos
incompletos que hubo que reconstruir.

## 4.7 Vista de despliegue

En la etapa de entrega el sistema opera localmente (d155): un equipo actúa como servidor, con el backend en el puerto
8000, la interfaz en el 5173 y la base `crm`. Un segundo backend en el puerto 8001 apunta a la base `crm_sandbox` para
pruebas contra los ambientes de prueba de los proveedores [verificar puertos al cierre]. PostgreSQL corre en un
contenedor (`compose.yaml`). El respaldo local automatizado con copia en disco externo y en nube cifrada (BCK-01a, d156)
se describe en el capítulo 8.

```text
Equipo servidor (local)
 ├─ PostgreSQL 17 (contenedor): bases crm y crm_sandbox
 ├─ Backend FastAPI :8000 (APP_ENV=production) + APScheduler
 ├─ Backend FastAPI :8001 (APP_ENV=sandbox)
 └─ Frontend Vite :5173
Usuarios internos ── navegador ──> Frontend ──> API (cookie HttpOnly + CSRF)
```

El hosting en la nube con recuperación a un punto en el tiempo (ENV-01, BCK-01 con PITR) y la exposición pública de los
receptores de webhooks quedan fuera de la entrega (capítulo 11).

## 4.8 Riesgos arquitectónicos conocidos

| Riesgo | Efecto | Mitigación actual |
| --- | --- | --- |
| Dos modelos centralizados | Indicadores que pueden diferir según el modelo consultado | Pruebas de paridad por canal (`app/services/vp_parity.py`, auditoría del 2026-10-29) |
| Identidad transversal parcial | El mismo socio puede figurar como dos clientes Core | Detector de candidatos y revisión manual (ADR-001) |
| Trazabilidad incompleta en TCH | Filas centralizadas de TCH sin vínculo a `source_records` | Registro de cargas por hash de archivo (`tch_file_loads`) [verificar estado del backfill] |
| Contratos de proveedor no confirmados | Lecturas por ventana y algunas validaciones sin cerrar | Banderas apagadas y relectura completa semanal; pedidos TER-01 |
| Operación en un solo equipo | Punto único de falla | Respaldo automatizado y restauración verificada (BCK-01a) |

## 4.9 Síntesis

La arquitectura prioriza la integridad, la idempotencia y la seguridad de las operaciones con efectos por sobre la
escalabilidad. La separación en capas (Raw, canal, centralizada) aísla las particularidades de cada proveedor; la
identidad central con identidades externas evita fusiones erróneas; y el diseño de webhooks como señales que disparan
una relectura hace que el sistema sea robusto frente a avisos duplicados, desordenados o no firmados. El capítulo 5
detalla el modelo de datos y la forma en que cada canal se proyecta sobre él.
