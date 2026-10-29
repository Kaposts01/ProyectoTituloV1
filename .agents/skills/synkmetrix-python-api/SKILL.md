---
name: synkmetrix-python-api
description: 'Implementar, revisar o refactorizar servicios Python y endpoints FastAPI/Pydantic de SynkmetriX: contratos, validacion, permisos y errores. Usar para cambios de backend; no para consultas SQL aisladas, conectores de proveedor o cambios solo visuales.'
---

# SynkmetriX · Backend y API

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Mapa de trabajo

Lee `app/api/v1/router.py`, la ruta afectada, sus servicios, `app/core/security.py`, esquemas y pruebas correspondientes. Comprueba cual proyeccion lee el endpoint: `app/models/crm.py`, tablas de canal o `app/models/core.py`; los nombres parecidos no hacen intercambiables sus contratos.

## Criterio de implementacion

- Define entrada, salida, autenticacion, permiso por recurso/canal, CSRF si muta estado y efectos locales/remotos antes de editar. Mantener un boton oculto no sustituye autorizacion backend.
- Revisa precedencia entre rutas estaticas y parametros dinamicos; por ejemplo, un literal de control puede quedar capturado por `/{provider}`. Prueba el despacho, no solo la existencia del handler.
- Separa transporte HTTP de reglas de negocio al extraer responsabilidades reales. No introduzcas capas repository/service/interfaces vacias ni un contenedor de inyeccion para operaciones simples.
- Usa modelos de entrada/salida donde expresen el contrato. Distingue campo omitido, null, cero y cadena vacia; conserva semantica de actualizaciones parciales. Evita exponer columnas internas por serializacion indiscriminada.
- Propaga errores con significado, sin cuerpos de proveedor, cabeceras, PII ni parametros SQL. Limita capturas generales a fronteras que necesiten limpieza y registra el resultado durable de la operacion.
- Determina quien posee la sesion y la transaccion. Un servicio reutilizable no debe confirmar trabajo ajeno de forma oculta; conserva la convencion existente hasta que el alcance autorice cambiarla.
- No ejecutes operaciones bloqueantes largas dentro del event loop. Elige ejecucion sincronica o aislamiento apropiado segun las dependencias reales. BackgroundTasks no es una cola durable: reconoce perdida por reinicio.
- Usa Decimal para reglas monetarias que requieran exactitud y fechas con zona definida; la precision de almacenamiento y la representacion JSON deben acordarse.

## Validacion y entrega

Prueba exito, entrada invalida, acceso sin sesion, permiso insuficiente y CSRF cuando aplique; añade casos de compatibilidad o concurrencia solo si el cambio los afecta. Usa overrides para aislar persistencia y proveedores. Ejecuta los checks Python de `AGENTS.md` en un entorno de pruebas seguro. Entrega contrato antes/despues, pruebas ejecutadas y limitaciones.

Para revisar una extraccion o fallo de contrato, consulta [casos de revision](references/review.md).
