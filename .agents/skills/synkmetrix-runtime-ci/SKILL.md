---
name: synkmetrix-runtime-ci
description: Preparar o diagnosticar entorno local, arranque Uvicorn/Vite/PostgreSQL, Docker Compose y CI GitHub Actions de SynkmetriX. Usar para configuracion o ejecucion reproducible; no desplegar, publicar ni reemplazar bases operativas por defecto.
---

# SynkmetriX · Entorno y CI

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Inventario antes de actuar

Lee `.python-version`, `requirements.lock`, `frontend/package-lock.json`, scripts npm, `compose.yaml`, configuracion Vite y workflow CI segun la tarea. Revisa primero servicios, puertos, entorno virtual, logs y presencia de `.env` sin mostrar sus valores. Un endpoint health 200 no demuestra acceso a base ni autenticacion.

## Arranque y configuracion

- Reutiliza servicios del proyecto cuando sean correctos; identifica propietario y directorio antes de detener procesos. Inicia procesos de fondo ocultos en Windows, con logs en `logs/`, e informa como identificar sus servicios.
- Instala Python desde `requirements.lock` y frontend con `npm ci`. Usa versiones declaradas; si el entorno difiere, explicita la desviacion antes de certificar reproducibilidad y no reescribas locks para que coincidan con tu maquina.
- Conserva configuracion publica separada de secretos. Variables expuestas al bundle frontend no pueden contener credenciales. No uses cuentas reales o flags de escritura para un smoke test.
- Aplica migraciones al destino verificado antes de API/sync. No cambies conexion, version PostgreSQL ni volumen para ocultar un fallo de autenticacion o Docker: una instancia nueva vacia requiere una decision de entorno.
- Docker/WSL puede depender de virtualizacion y reinicio del equipo. Diagnostica primero y comunica el requisito concreto; no restaures fabrica, borres volumenes ni reinicies el equipo por iniciativa propia.
- Preserva el proxy Vite hacia la API y escucha local salvo exposicion solicitada. Distingue Vite dev, build servido por FastAPI y acceso remoto: cambiar uno no implica desplegar los otros.
- `.env` se lee con settings cacheados: verifica recarga/reinicio del proceso correcto tras cambios de configuracion. No reintentes llamadas externas con secretos antiguos ni supongas que tocar un formulario reinicio la API.

## Integracion continua

Mantén CI alineado con locks, version runtime y migraciones. Usa PostgreSQL de servicio con credenciales sinteticas, checks backend y lint/build frontend del proyecto. No elimines checks, amplíes permisos ni expongas secretos en forks para obtener verde. Valida sintaxis y efectos de workflow sin publicar ni disparar ejecuciones externas no autorizadas.

## Verificacion y entrega

Comprueba puertos, readiness PostgreSQL, revision Alembic, health, autenticacion y proxy mediante solicitudes locales sin imprimir tokens. No ejecutes sincronizaciones de proveedor como efecto colateral de levantar servidores. Informa URLs, procesos/logs, configuracion pendiente y limitaciones de CI que no ejecutaste. Una preparacion local no prueba un despliegue productivo.

Consulta [casos de revision](references/review.md) para incidentes de entorno y drift de configuracion.
