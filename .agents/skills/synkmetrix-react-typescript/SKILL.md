---
name: synkmetrix-react-typescript
description: 'Implementar o refactorizar interfaces React/TypeScript de SynkmetriX: componentes, formularios, efectos, rutas, cache y accesibilidad. Usar para comportamiento frontend; las definiciones financieras de dashboards corresponden a la especialidad de metricas.'
---

# SynkmetriX · Frontend

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Mapa de trabajo

Parte de `frontend/src/App.tsx`, `routes.ts`, `apiCache.ts`, componente afectado y contrato API consumido. El proyecto ya tiene resolucion de rutas e historial: no agregues un router, gestor de estado o cliente de datos solo para extraer un componente.

## Estado y limites

- Identifica estado de servidor, navegacion, formulario y presentacion. Evita copiar en estado un valor derivable de props o datos actuales; reserva efectos para sincronizacion externa.
- Modela estados incompatibles con uniones discriminadas. Recibe datos externos como desconocidos hasta estrechar o validar los campos relevantes; una asercion TypeScript no valida JSON.
- Controla solicitudes obsoletas al cambiar filtro o ruta: cancelacion y/o identidad de solicitud. Incluye el contexto real de cuenta, canal y filtros en claves de cache.
- Tras escritura, sincronizacion, cambio de sesion o permisos, revisa invalidacion y respuestas en vuelo: una solicitud anterior no debe repoblar una cache invalidada ni compartir datos entre usuarios.
- Conserva paginacion, orden, filtros y comportamiento atras/adelante durante extracciones. Los terminos personales no deben filtrarse a query parameters; usa identificadores permitidos y conserva las excepciones vigentes.
- Mantén cookie de sesion y cabecera CSRF a traves de helpers existentes. La UI adapta visibilidad y feedback, pero FastAPI conserva el control de permisos.
- En formularios conserva datos introducidos ante error, muestra validacion junto al campo, evita doble envio y diferencia confirmacion de estado optimista.
- Usa etiquetas, navegacion de teclado y foco coherentes en modales y menus. Mantén estados de carga, error, vacio y acceso denegado sin aparentar ausencia de datos cuando fallo una solicitud.

## Refactorizacion incremental

Extrae una funcionalidad cohesionada de `App.tsx` hacia componentes, hooks o funciones puras segun su responsabilidad. Haz explicitas sus entradas y callbacks y evita trasladar todo el estado global a un hook gigante. Mantén estilos y selectores existentes salvo cambio visual pedido. No conviertas cada fragmento en una abstraccion ni memoices sin un problema observable.

## Validacion y entrega

Ejecuta lint y build desde `frontend/`. Comprueba las interacciones afectadas, rutas directas, historial, permisos y vista movil cuando aplique. Si no existe infraestructura de pruebas UI, no la instales automaticamente: usa verificaciones manuales o un test focalizado en la infraestructura disponible y declara su alcance. Entrega comportamiento conservado y casos verificados.

Consulta [casos de revision](references/review.md) para cambios de efectos, cache o extraccion.
