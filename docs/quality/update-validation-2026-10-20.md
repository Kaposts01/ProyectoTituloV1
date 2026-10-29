# Validacion de actualizacion 4604258 — 2026-10-20

Resultado inicial: validacion ejecutada con hallazgos. Correcciones y nueva evidencia al final de este informe.

## Evidencia

- `python -m pytest -q --tb=short -ra`: 265 passed, 1 failed, 1 warning, 24.74 s. Base PostgreSQL aislada, datos sinteticos, URLs de proveedor invalidas y secretos ficticios. Sin pruebas contra crm operativo.
- `python -m ruff check app tests alembic scripts`: 5 errores: dos BLE001 en tests/test_client_match_detector.py (72, 78); tres I001 en tests/test_core_etl_helpers.py:6, tests/test_staging_api.py:305 y tests/test_webhooks_virtualpos.py:3.
- `python -m pip check`: sin incompatibilidades.
- `npm run lint`: exit 0, 11 advertencias.
- `npm run build`: exit 0; bundle principal 838.06 kB, advertencia de tamano superior a 500 kB.
- `alembic upgrade head`: cadena completa aplicada en base aislada hasta 20261020_0031.
- `alembic check`: falla. alembic/env.py no importa los tres modelos stg_*_webhook_event; autogenerate propone eliminar sus tablas e indices. Solo se inspecciono; no se aplicaron eliminaciones.
- Smoke HTTP local: API health 200, OpenAPI 200, Vite 200 y auth/me sin sesion via proxy 401 esperado. No equivale a validacion funcional de todos los flujos.

## Hallazgos

1. Metadata Alembic incompleta para las tres tablas nuevas de webhooks. Corregir los imports y volver a verificar consistencia antes de generar nuevas migraciones.
2. `test_payku_consolidation_preserves_subscription_dates_and_rut` falla: espera canceled_at='2099-02-01' usando payload.end, pero obtiene None. El codigo obtiene la cancelacion desde logs de transicion. La documentacion de Payku resources/subscriptions.md describe end como ambiguo; resolver el contrato y la fixture sin restaurar una inferencia no verificada.
3. Ruff bloquea CI con cinco errores. El fixture pg_session captura Exception ampliamente; revisar su manejo para no ocultar errores como falta de PostgreSQL.
4. La base operativa sigue en 20261007_0028. Las migraciones 0029-0031 no se aplicaron a ella durante esta validacion.

## Limites y artefactos

Entorno local Python 3.14.7 y PostgreSQL 18; proyecto declara Python 3.14.5 y CI PostgreSQL 17. No se certifica reproducibilidad exacta en CI. No se probaron interacciones visuales, servicios externos ni se publicaron cambios. No se modifico codigo funcional ni se corrigieron los hallazgos.

Logs locales ignorados: .local/validation-migrations.log, .local/validation-pytest.log y .local/validation-alembic-check.log. Base aislada conservada para diagnostico: synkmetrix_validation_568eac70a1; nombre tambien en .local/validation-db-name.txt. No contiene datos importados del CRM.

## Correcciones verificadas posteriores (2026-10-20)

- Registrados los tres modelos de webhooks en alembic/env.py. `alembic check` en base aislada pasa sin operaciones nuevas. CI incorpora este check despues del upgrade para detectar regresiones.
- Prueba Payku alineada con evidencia de transiciones: tres casos cubren ultima cancelacion, cancelacion sin evidencia y suscripcion activa con cancelacion anterior. Se conservan las aserciones de monto, RUT y fecha de alta; no se cambio el comportamiento financiero para acomodar la prueba.
- Fixture del detector de coincidencias usa transaccion externa y savepoints; ya no oculta errores como skips ni conserva commits de las pruebas.
- Ordenados imports detectados por Ruff. Validacion global: `ruff check app tests alembic scripts` pasa.
- Suite completa en base aislada: **268 passed**, 1 advertencia de deprecacion Starlette/httpx, 19.64 segundos.
- Base operativa actualizada de 0028 a 0031, despues de respaldo local ignorado `.local/backups/crm-before-0031-20261020-185454.dump` (20.282.703 bytes). No se modificaron migraciones aplicadas ni se ejecutaron operaciones de proveedor. El respaldo se genero correctamente; no se hizo ensayo de restauracion.
- Smoke autenticado via proxy Vite: login, auth/me, dashboard/general y logout respondieron 200.
- Frontend sin modificaciones en esta correccion; conserva build exitoso y las 11 advertencias previamente registradas. Persisten aviso de bundle grande y diferencias de runtime respecto de CI. No se certifican flujos visuales ni integraciones externas.
