---
name: synkmetrix-integrations-httpx
description: Implementar, diagnosticar o revisar conectores HTTPX y sincronizaciones API de VirtualPOS, Toku y Payku en SynkmetriX. Usar para autenticacion, paginacion, retries y contratos de origen; no para ETL Excel ni para habilitar escrituras por tener una clave.
---

# SynkmetriX · Integraciones

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Contrato antes de transporte

Aplica `.opencode/skills/provider-integration/SKILL.md` y lee solo `docs/integrations/<proveedor>.md`, cliente, sincronizador y pruebas afectados. Comprueba documentacion oficial del proveedor para endpoints y scopes que cambien; Context7 sirve para bibliotecas, no para inventar contratos del proveedor.

## Implementacion y diagnostico

- Verifica host, esquema, ambiente y presencia de credenciales sin mostrar valores. API key y secret pueden ser especificos de cuenta y ambiente. No pruebes una clave en produccion si solo esta autorizado Sandbox ni recorras hosts hasta que alguno acepte la clave.
- Conserva firma y autenticacion dentro del cliente. No imprimas URL con query sensible, headers, JWT, cuerpos de error o datos de tarjeta. El navegador consume solo la API interna.
- Usa timeouts explicitos y cierre de clientes. Clasifica DNS/conexion, timeout, HTTP de autenticacion, rate limit, recurso ausente, respuesta no JSON y envelope invalido antes de actuar.
- Pagina segun contrato por recurso: cursor o numero de pagina, senal de termino, limites y orden. Una pagina vacia debe ser una respuesta valida, no un fallback de parseo. Alcanzar el guard de paginas requiere declarar cobertura incompleta.
- Limita reintentos a fallos transitorios y operaciones seguras; respeta Retry-After y usa espera acotada cuando aplique. No repitas una escritura de pago porque el transporte no confirmo su resultado.
- Conserva staging saneado e identidad por fuente, recurso e ID externo. El conector obtiene y persiste origen; las reglas financieras e identidad del Core pertenecen a otra etapa.
- Deja resultado durable en `sync_runs`, incluyendo fallos previos a la primera pagina. Decide si el contrato permite progreso por recurso o exige rollback completo; no ocultes commits parciales.
- Ante 404/403 de un recurso, no sustituyas por lista vacia ni presentes exito completo. Una carga acotada autorizada debe listar recursos incluidos/excluidos y conservar la evidencia del fallo. No inventes una ruta alternativa a partir de nombres similares.
- Mantén escrituras fuera de la sincronizacion. La skill no autoriza acciones WR, activar flags ni cambiar ambientes; aplica los limites de `AGENTS.md` y del pedido humano.

## Validacion y entrega

Usa respuestas sinteticas y transporte simulado para firma, paginacion, 401/403/404, rate limit, timeout y saneamiento segun el cambio. Ejecuta una lectura real solo dentro de la autorizacion y entorno acordados, y detente ante credenciales invalidas o contrato desconocido que impida continuar con seguridad. Informa cobertura por recurso, resultado y siguiente dependencia concreta.

Consulta [casos de revision](references/review.md) para errores de contratos o fallos parciales.
