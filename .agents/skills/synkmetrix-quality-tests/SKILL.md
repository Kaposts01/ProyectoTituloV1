---
name: synkmetrix-quality-tests
description: Disenar pruebas significativas, diagnosticar fallos y validar refactorizaciones de SynkmetriX con pytest, Ruff y checks frontend existentes. Usar para QA o regresiones con riesgo; no crear suites redundantes para cada cambio trivial ni certificar produccion con mocks.
---

# SynkmetriX · Calidad

## Contexto y alcance

Ubica la raiz del repositorio y aplica `AGENTS.md` y la memoria vigente antes de cambiar codigo. Consulta Context7 para comportamiento externo que necesite verificacion; si no esta disponible, usa documentacion oficial y declara esa limitacion. Las rutas siguientes son relativas a la raiz del proyecto.

Implementa solo la tarea autorizada, conservando contratos y permisos. Una refactorizacion debe demostrar que preserva comportamiento; no autoriza funciones nuevas ni cambios de arquitectura. Documenta contratos, decisiones y restricciones relevantes, evitando comentarios que narren instrucciones obvias. No cambies dependencias ni agregues herramientas por conveniencia sin justificar su necesidad.

## Elegir evidencia proporcional

Lee la prueba, comportamiento y configuracion afectados; consulta `ruff.toml`, `tests/`, `frontend/package.json` y `.github/workflows/ci.yml` cuando corresponda. Separa problema de codigo, contrato, fixture, entorno y dependencia antes de modificar la prueba.

## Estrategia de pruebas

- Escribe aserciones sobre resultados observables e invariantes: permisos, datos, idempotencia, orden o rollback. No fijes nombres internos, texto de comentarios ni cada llamada incidental para blindar la implementacion.
- En refactorizacion conserva al menos el caso que perderia comportamiento y el borde relevante. Una correccion debe demostrar la falla original con un caso reducido cuando sea viable.
- Mantén datos sinteticos y deterministas. Controla reloj y aleatoriedad donde importen; no copies payloads personales o secretos de produccion a fixtures.
- Separa unitarias puras, contrato de integracion con HTTP simulado y persistencia en PostgreSQL aislado. No ejecutes pruebas que muten datos hasta verificar que DATABASE_URL apunta al entorno descartable previsto.
- Revisa el lifespan de TestClient: iniciar la app puede disparar scheduler o limpieza de corridas. Aisla esos efectos segun la prueba y no uses el arranque real para esconder dependencias.
- Simula el contrato completo que usa el cliente: paginacion, envelope y errores relevantes. Un mock incompleto puede fallar antes del comportamiento bajo prueba; no elimines una rama valida para acomodar un mock viejo.
- Cubre negativos que protegen el cambio: acceso sin permisos, entrada invalida, error de proveedor, ambiguedad o fallo intermedio segun alcance. Evita una matriz exhaustiva sin un riesgo concreto.
- No silencies lint, relajes asserts ni marques xfail solo para pasar CI. Los fallos previos se reportan con evidencia reproducible; no se asumen heredados por aparecer en una nota vieja.
- No agregues frameworks frontend o servicios de test automaticamente. Usa las herramientas instaladas y justifica cualquier ampliacion necesaria.

## Ejecucion y reporte

Ejecuta primero la prueba focalizada y checks pertinentes de `AGENTS.md`; amplia al conjunto necesario para el alcance. Para Python usa `python -m pytest` y `ruff check app tests alembic scripts` desde el entorno del proyecto. Para frontend usa lint/build en `frontend/`. Reporta comando, resultado, advertencias y lo que no pudo ejecutarse. Sintaxis, build y cobertura porcentual no equivalen a correccion funcional.

Consulta [casos de revision](references/review.md) para evaluar suficiencia y seguridad de una suite.
