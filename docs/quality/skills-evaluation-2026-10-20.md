# Evaluacion de las nueve skills Codex

Fecha: 2026-10-20. Alcance: estructura, seleccion por metadatos y revision tecnica offline con datos sinteticos. No se modificaron las skills como consecuencia de esta evaluacion, ni funcionalidades del CRM.

## Resultados

| Nivel | Resultado | Evidencia y alcance |
| --- | --- | --- |
| Contratos de paquetes | 37/37 pruebas pytest pasan | Frontmatter, identidad, UI, referencias, seleccion implicita configurada y cobertura de casos. No evalua decisiones del modelo. |
| Comportamiento en revision | 27/27 casos cumplen los criterios revisados | Tres evaluadores independientes respondieron tres casos por skill, con revision cualitativa posterior por el agente principal. No ejecutaron implementaciones. |
| Seleccion por metadatos | 12/12 selecciones primarias esperadas | Evaluador separado leyo solo nombres/descripciones: nueve solicitudes de stack y tres fuera de alcance. Es simulacion de seleccion, no activacion nativa medida. |
| Ruff de la suite nueva | Correcto | `ruff check tests/test_codex_skills.py`. |
| Ruff global | Un error ajeno al cambio | `I001` en `tests/test_core_etl_helpers.py:6`; reproducido con el contenido de `HEAD`, sin diff local en ese archivo. No se corrigio fuera de alcance. |
| Diff | Correcto | `git diff --check`. |

## Casos de comportamiento

Los evaluadores recibieron la skill, sus referencias y solicitudes con artefactos sinteticos. No recibieron la solucion esperada ni la rubrica del agente principal. El contexto del proyecto se sustituyo por instrucciones de evaluacion offline: sin secretos, red, bases ni codigo operativo. Cada respuesta distingue diagnostico, acciones propuestas, validacion futura y limitaciones.

| Skill | Casos | Criterios observados |
| --- | --- | --- |
| `synkmetrix-python-api` | api-route, api-patch, api-transaction | Corrige despacho conservando seguridad; distingue omitido/null; detecta commit prematuro. |
| `synkmetrix-postgres-orm` | db-shared-email, db-migration, db-pagination | Conserva asociaciones compartidas; expansion/contraccion sin inventar mapeo; filtra/ordena antes de paginar. |
| `synkmetrix-react-typescript` | ui-account-race, ui-logout-cache, ui-extraction | Aisla cuenta/sesion; evita publicacion tardia; conserva URL, permisos y estado operativo. |
| `synkmetrix-dashboard-recharts` | metrics-churn, metrics-coverage, metrics-payments | Churn sintetico 2%; datos ausentes no equivalen a cero; separa CLP/USD y hechos de pago. |
| `synkmetrix-etl-pandas` | etl-existing-report, etl-overlap, etl-ambiguous-rut | Evita recarga destructiva; distingue hecho/observacion/intento; no elige primer RUT coincidente. |
| `synkmetrix-integrations-httpx` | http-environment, http-partial-404, http-pagination | No cambia de ambiente por un comentario; no oculta 404; procesa pagina final y declara cobertura incompleta. |
| `synkmetrix-scheduler-sse` | jobs-double-start, jobs-reconnect, jobs-restart-partial | Distingue exclusion local/distribuida; consulta estado durable; no falla trabajo ajeno ni oculta consolidacion fallida. |
| `synkmetrix-quality-tests` | qa-incomplete-mock, qa-operational-db, qa-build-equivalence | No recorta producto para pasar un mock; detiene pruebas destructivas; no equipara build y equivalencia funcional. |
| `synkmetrix-runtime-ci` | ops-docker-failure, ops-settings-cache, ops-ci-migration | No reemplaza bases sin decision; reconstruye configuracion del proceso correcto; mantiene migraciones y dependencias bloqueadas. |

No se encontraron incumplimientos de estos criterios en las respuestas observadas. Las incertidumbres sobre contratos, esquemas, bloqueos y datos faltantes fueron explicitadas, en vez de resolverse inventando hechos.

## Artefactos y reproduccion

- Pruebas ejecutables: [tests/test_codex_skills.py](../../tests/test_codex_skills.py).
- Solicitudes sinteticas de comportamiento: [cases.json](../../tests/fixtures/skills/cases.json).
- Solicitudes de seleccion: [routing-cases.json](../../tests/fixtures/skills/routing-cases.json).
- Evaluacion por caso, resultados de seleccion y hashes de las skills/respuestas: [assessment-2026-10-20.json](../../tests/fixtures/skills/assessment-2026-10-20.json).
- Respuestas originales sinteticas: `.local/skill-evaluations/responses/{backend,ui-data,ops,routing}.json`, conservadas localmente y excluidas de Git. Una copia del contexto offline esta en `.local/skill-evaluations/fixture-project/`.

Desde la raiz del repositorio, para repetir las comprobaciones automatizadas sin acceder a la aplicacion:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_codex_skills.py -q
.\.venv\Scripts\python.exe -m ruff check tests/test_codex_skills.py
git diff --check
```

Para repetir la evaluacion de comportamiento, proporciona a un evaluador independiente cada skill y sus solicitudes/artefactos, con el mismo limite offline; manten la evaluacion esperada fuera de su entrada. Compara sus decisiones con los criterios registrados y conserva la nueva corrida por separado. Las salidas de un modelo no tienen por que ser identicas.

## Limites de la conclusion

- Una respuesta por escenario; no se midieron variabilidad entre corridas ni mejora frente a un grupo sin skill. Un resultado favorable no demuestra causalidad ni garantiza todos los casos futuros.
- Son decisiones y planes de revision tecnica. No se ejecutaron parches propuestos, navegador, migraciones, sincronizaciones, pruebas del CRM completo ni llamadas reales a proveedores.
- Las nueve skills aparecen en el catalogo activo de esta conversacion. La seleccion simulada no certifica la activacion automatica del producto en una sesion limpia.
- Las pruebas estructurales se pueden ejecutar en CI; las 27 revisiones y 12 selecciones de modelo son evidencia evaluada de esta corrida, no tests deterministas que pytest vuelva a ejecutar.
- No se certifica que el repositorio completo pase sus checks: Ruff global conserva el error descrito. Ningun servicio, base operativa o dato personal fue utilizado como fixture.
