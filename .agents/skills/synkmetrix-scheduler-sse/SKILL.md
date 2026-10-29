---
name: synkmetrix-scheduler-sse
description: Implementar o revisar APScheduler, orquestacion de sincronizaciones y progreso SSE en SynkmetriX. Usar para ejecuciones duplicadas, reinicios, estados parciales, cancelacion o streams; no sustituir SSE por WebSocket ni introducir una cola sin una necesidad aprobada.
---

# SynkmetriX · Jobs y SSE

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Mapa y modelo de ejecucion

Lee `app/main.py`, `app/scheduler/engine.py`, `jobs/sync_all.py`, `event_bus.py`, rutas de scheduler y consumidor EventSource en frontend. Establece proceso que programa, proceso que ejecuta, fuente durable del estado, frecuencia/zona horaria y politica actual de solapamiento.

## Decisiones de confiabilidad

- No confundas singleton en Python o max_instances local con exclusion entre workers. Analiza reload, varias instancias y jobstore compartido; si necesitas exclusion distribuida, elige una estrategia compatible con PostgreSQL y define liberacion ante fallo.
- Distingue hora local de programacion y timestamps de ejecucion; considera cambio de horario de America/Santiago. Mantén funciones persistidas importables y argumentos serializables.
- Una corrida tiene identidad estable, etapas y resultados por canal. Fallar consolidacion o un canal no debe terminar con un exito global sin evidencia de incompletitud.
- Reanudar, reintentar y reprogramar son acciones distintas. Preserva idempotencia de ingesta y evita repetir efectos remotos. Define quien puede disparar, detener o ver cada corrida.
- No marques automaticamente como fallidas todas las corridas running de otros workers al reiniciar uno. La recuperacion debe comprobar propiedad o expiracion segun el diseno autorizado.
- El bus actual esta en memoria: replay y suscriptores pertenecen al proceso. No prometas recuperacion despues de reinicio ni entrega entre workers sin almacenamiento o transporte compartido.
- En SSE revisa autenticacion y permisos, desconexion, limpieza de suscriptores, heartbeat si hace falta, limite de historial/colas y cierre terminal. La falta de eventos no prueba que el job fallo.
- El cliente debe poder reconciliarse contra estado durable tras reconexion, perder el stream o abrir tarde. No emitas PII ni secretos y no uses porcentajes cuando no existe denominador verificable.

## Validacion y entrega

Simula doble disparo, fallo parcial, desconexion/reconexion y reinicio sin llamadas reales a proveedores. Prueba exclusion en el ambito que el cambio dice cubrir; un test de un proceso no demuestra exclusion distribuida. Verifica permisos y resultado final persistido ademas de los eventos visibles. No migres a Celery, Redis o WebSocket como requisito automatico.

Consulta [casos de revision](references/review.md) para fallos de reanudacion o concurrencia.
