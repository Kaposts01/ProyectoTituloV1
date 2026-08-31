# Tareas del proyecto

Este archivo es la fuente de estado del proyecto. Debe actualizarse al iniciar, bloquear, completar o modificar una tarea.

## Hito 1: VirtualPOS Sandbox (solo lectura)

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-01 | Inicializar Git, entorno Python y configuración segura | Completada | `.venv`, `.gitignore`, `.env.example` y `requirements.txt` disponibles; `.env` no se versiona. |
| VP-02 | Crear API FastAPI y persistencia PostgreSQL | Completada | API saludable, modelos y migración inicial definidos. |
| VP-03 | Implementar autenticación y cliente VirtualPOS | Completada | Firma HS256 generada localmente y peticiones solo de lectura. |
| VP-04 | Persistir staging idempotente y ejecuciones de sincronización | Completada | Repetir una sincronización no duplica registros externos. |
| VP-05 | Normalizar clientes, suscripciones y pagos | Pendiente | Las vistas canónicas preservan la referencia al origen. |
| VP-06 | Exponer consulta y estado de sincronización | Pendiente | Endpoints documentados y cubiertos por pruebas. |
| VP-07 | Validar contra Sandbox y documentar resultados | Pendiente | Ejecución real registrada sin exponer secretos. |

## Decisiones vigentes

- Backend: FastAPI y Python.
- Base de datos: PostgreSQL.
- Fuente inicial: VirtualPOS Sandbox.
- Operación contra proveedores: solo lectura durante el MVP.
- Secretos: exclusivamente en `.env` o en el gestor de secretos del entorno de despliegue.

## Verificación local

- Fecha: 2026-08-30.
- Entorno: Python 3.14 en `.venv` y PostgreSQL 17 mediante Docker Compose en `localhost:5433`.
- Resultado: pruebas unitarias y lint correctos; migración `20260830_0001` aplicada.
- El lanzador `python scripts\sync_virtualpos.py` fue verificado localmente tras corregir la resolución de imports.
- VP-07 está listo para validación: las credenciales Sandbox fueron configuradas manualmente en `.env`; el entorno local de Postman no exporta sus valores secretos.

## Próximas tareas priorizadas

| ID | Tarea | Estado | Criterio de aceptación |
| --- | --- | --- | --- |
| VP-08 | Inspeccionar y documentar los payloads reales de Sandbox | Pendiente | Se definen campos, identificadores y paginación por recurso. |
| VP-09 | Completar paginación y sincronización incremental | Pendiente | Todas las páginas se obtienen y ejecuciones sucesivas procesan solo cambios necesarios. |
| VP-10 | Normalizar modelo canónico | Pendiente | Clientes, suscripciones, cargos y pagos se materializan desde staging. |
| VP-11 | Crear API de consulta del CRM | Pendiente | Endpoints paginados para clientes, suscripciones, pagos y detalle. |
| VP-12 | Añadir pruebas de integración del sincronizador | Pendiente | Respuestas simuladas cubren éxito, paginación, duplicados y errores. |
| VP-13 | Programar sincronizaciones y alertas | Pendiente | Ejecución periódica con reintentos y registro de fallos. |
| VP-14 | Iniciar frontend CRM | Pendiente | Dashboard y vistas de clientes/suscripciones consumen la API. |
