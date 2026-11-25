# ML-11: API sintetica, revisiones y permisos

Fecha: 2026-11-25. **API implementada y probada con usuarios/datos sinteticos, apagada en el CRM.** Sin entrenamiento, carga/inferencia de modelos, proveedores, subida de archivos o activacion real. El socio validara datos y entorno completos. ADR-002 sigue Proposed.

## Alcance y arranque seguro

Router `app/api/v1/routes/ml.py`, montado en `/api/v1/ml` dentro del router autenticado existente. Usa JWT/cookie, version de sesion, usuario activo y roles/permisos reales de SynkmetriX. No crea otra autenticacion ni inicia el lifespan/scheduler para probar.

`ML_REJECTIONS_API_ENABLED=false` por defecto en Settings y `.env.example`; no se modifica `.env`/`.env.local`. La API exige ademas base descartable PostgreSQL cuyo nombre termine en `_test`. Apagada responde 503 antes de consultar tablas ML. Sin sesion valida responde 401. Es una preparacion aislada; activar una variable no habilita modelos reales o cobros.

La revision **20261125_0086**, posterior a 0085, solo siembra doce permisos; no crea tablas o asignaciones de rol. Se aplico exclusivamente a `crm_ml_registry_test`. QA sigue en 0082; original intacta. No migrar QA/original copiando comandos de pruebas. Las migraciones aplicadas anteriormente no cambiaron.

## Matriz de autorizacion

Toda ruta exige **permiso ML + acceso a cuenta + permiso existente del recurso/canal**. No basta el permiso de Dashboard ni una vista unificada general. La comprobacion ocurre antes de buscar el objeto o verificar archivos.

| Capacidad | Permiso ML |
|---|---|
| Resultados y conteos de lotes | `ml.rejections.read` |
| Etiquetas y su historial | `ml.labels.read` |
| Propuesta inicial/correccion | `ml.labels.propose` |
| Aprobar, rechazar, abstenerse o retirar | `ml.labels.review` |
| Metadatos/version actual del registro | `ml.artifacts.read` |
| Aprobar un artefacto sintetico | `ml.artifacts.review` |
| Publicar, revertir o deshabilitar solo en simulacion | `ml.artifacts.simulate` |

A cada capacidad se suma `ml.<cuenta>.access`, con cuentas `virtualpos1`, `virtualpos2`, `toku`, `payku`, `tch`. VP1 no concede VP2 aunque compartan permisos historicos VirtualPOS.

| Fuente | charge | payment / transaction | subscription_state |
|---|---|---|---|
| VP1/VP2 | `virtualpos.charges.view` | `virtualpos.payments.view` | `virtualpos.subscriptions.view` |
| Toku | `toku.invoices.view` | `toku.transactions.view` | `toku.subscriptions.view` |
| Payku | `payku.transactions.view` | `payku.transactions.view` | `payku.subscriptions.view` |
| TCH | `tch.transacciones.view` | `tch.transacciones.view` | `tch.suscripciones.view` |

Artefactos/versiones abarcan la cuenta completa: requieren **todos** sus permisos de recurso de la tabla, ademas de capacidad ML y acceso a cuenta. No permitir que un permiso de un solo listado gestione un modelo para todos los recursos.

Los nombres ML no terminan en `.view`; no se incorporan automaticamente a soporte/ejecutivo por el sembrador actual. `seed_permissions` conserva su comportamiento existente de dar todo el catalogo a admin cuando se ejecuta explicitamente; la migracion 0086 por si sola no otorga acceso. No se ejecutaron esos sembradores en QA/original. Se deben revisar asignaciones de negocio antes del piloto. Downgrade se bloquea si hay permisos ML asignados para no retirar accesos silenciosamente.

## Contratos HTTP

Prefijo comun `/api/v1/ml`; `source` es una cuenta concreta y `resource` uno de charge/payment/transaction/subscription_state. Identificadores opacos internos, nunca RUT/email como ruta.

| Metodo y ruta relativa | Comportamiento |
|---|---|
| GET `/{source}/{resource}/labels` | Pagina de contextos revisados y ultima revision, sin N+1. El historial se obtiene por detalle. |
| GET `/{source}/{resource}/labels/{uuid}` | Contexto, revision actual e historial paginado. |
| POST `/{source}/{resource}/labels` | Propuesta ML-03 con UUID de solicitud, contexto saneado y revision de privacidad explicita. |
| POST `/{source}/{resource}/labels/{uuid}/revisions` | Evento append-only con revision esperada, decision/categoria/gravedad/motivo. Contexto recuperado del servidor. |
| GET `/{source}/{resource}/results` | Resultados persistidos sinteticos, paginados y filtrados por recurso/cuenta. |
| GET `/{source}/{resource}/results/{sha}` | Un resultado ya guardado, sin recalcularlo. |
| GET `/{source}/{resource}/batches/{sha}` | Conteos solo del recurso autorizado, sin total/estado global que revele otros recursos. |
| GET `/{source}/artifacts/{sha}` | ID, cuenta, tarea, candidato, proposito y estado de entrenamiento. Sin rutas, pesos, glosas o descriptor privado. |
| GET `/{source}/releases/{p1\|p2}` | Revision y puntero simulado actual; revision cero si no existe, sin crear estado. Permite recargar tras conflicto. |
| POST `/{source}/artifacts/{sha}/approval` | Nueva verificacion privada y aprobacion por actor independiente. |
| POST `/{source}/releases/{p1\|p2}/simulation` | Transicion simulada promoted/rolled_back/disabled con revision esperada. |

Limites: paginas entre 1 y 100 filas; offset entre 0 y 10.000; orden estable por fecha+ID o numero de revision. No son cursores para exportaciones masivas. Listar etiquetas realiza una pagina y una consulta agrupada de revisiones, no una consulta por etiqueta.

Todos los POST requieren `X-CSRF-Token` correspondiente a la sesion y `synthetic: true` booleano estricto. Los cuerpos rechazan campos extra, actor seleccionado por cliente, rutas/archivos/claves y tipos ambiguos. El actor y quien revisa privacidad salen del usuario autenticado. El texto debe cumplir ML-03; la declaracion humana de privacidad no garantiza anonimizarlo. No poner glosas, secretos o atributos personales en URLs.

Propuestas usan la idempotencia por UUID ML-03; una repeticion devuelve el mismo evento, no una revision nueva. La respuesta de escritura es el evento solicitado; GET muestra el estado mas reciente. Revision obsoleta, autoaprobacion o transicion incompatible devuelven 409. Una correccion/retirada no recupera una aprobacion historica. Permisos se vuelven a obtener del servidor en cada peticion; el JWT no conserva una copia permanente de ellos.

Los cambios usan los servicios ML-03/08 existentes con savepoints, y la ruta controla commit/rollback de su sesion. No confirma tareas del ETL/worker. Autorizacion/validacion se hace antes de la escritura. Las respuestas privadas llevan `Cache-Control: no-store`. Los 422 no repiten valores ni nombres arbitrarios de campos; errores de persistencia se reducen a 503 sin SQL/credenciales/paths. Un 404 no distingue inexistente de otro ambito para quien ya tiene permiso sobre el ambito solicitado; quien no lo tiene recibe 403 antes de la busqueda.

## Artefactos y operaciones que siguen bloqueadas

Registro inicial y archivos permanecen offline: no existe endpoint para subir, registrar, elegir rutas o suministrar una clave HMAC. El verificador usa la ruta guardada y el directorio/clave fijos del servidor en `.local/ml-private`, con las protecciones ML-05/08. Comprueba firma, bytes, identidad, cuenta, proposito sintetico y compatibilidad antes de cada aprobacion/transicion; incluso deshabilitar verifica el artefacto activo si existe. Fallo devuelve 409 y no avanza la revision.

GET de metadatos/version no abre archivos ni carga modelos. La aprobacion usa dos actores distintos segun ML-08. La publicacion y rollback solo mueven el puntero **sintetico**; el CRM no lo consume y no se llama a un cargador. Un artefacto marcado reviewed-real se rechaza, aun dentro de una base de pruebas. La inspeccion privada no equivale a aislamiento de inferencia ni evita que un administrador cambie archivos posteriormente.

No hay rutas train, predict, activate, upload, export, enqueue o process. GET no etiqueta, entrena, calcula recomendaciones, crea lotes o consulta proveedores. No se exponen flags de habilitacion por HTTP. Resultados mantienen probabilidad/confianza nulas y ejecucion prohibida. El proposito sintetico identifica fixtures, no un modelo validado.

La guarda *_test y la marca synthetic son limites de esta entrega, no un detector de datos ficticios: nunca restaurar datos reales, renombrar una base y asumir que se ha saneado. El entorno del socio necesita auditoria y autorizacion separadas antes de ampliar esa frontera.

## Validacion

**569 pruebas distintas aprobadas:** 385 puras y 184 de PostgreSQL/API/ETL/permisos, incluidas 39 nuevas de ML-11. Ruff completo y revision del diff sin errores. La advertencia de TestClient descrita abajo no implica un fallo.

Pruebas con el router real, JWT firmado/CSRF reales y PostgreSQL descartable; no se sustituye get_current_user por un usuario omnipotente. Se monta FastAPI sin lifespan de app.main. Transportes HTTP externos y puntos de inferencia se bloquean en las pruebas de API.

La suite nueva cubre veinte combinaciones fuente/recurso con ausencia de cada permiso; sesion ausente/inactiva/revocada; cambio de rol con el mismo token; CSRF en propuestas/revisiones/artefactos/simulacion; actor falsificado; tipos/PII/contextos invalidos sin eco; autoaprobacion, idempotencia y revision obsoleta; correccion/retiro; recursos/cuentas cruzados; lotes mixtos; lectura sin calculo; metadatos acotados; bytes corruptos, incompatibilidad, tarea equivocada, rollback/deshabilitacion simulados y rechazo de artefactos reales.

Comando de regresiones con base descartable y configuracion sintetica resuelta antes de pytest. Conftest recrea public y migra: no usar QA/original. El wrapper local con la URL queda ignorado, sin publicarlo.

~~~powershell
.venv/Scripts/python.exe -m pytest tests/test_ml_batches.py tests/test_ml_artifact_registry.py tests/test_ml_annotations.py tests/test_ml_core_reader.py tests/test_sync_core_etl.py tests/test_core_etl_helpers.py tests/test_cancellation_permissions.py tests/test_export_permissions.py tests/test_ml_api.py --basetemp=.local/pytest-ml11-regressions -q
.venv/Scripts/ruff.exe check app tests alembic scripts
~~~

Tambien se repiten las 385 pruebas puras ML-02 a ML-10, sin conftest/DB. La suite de API emite una advertencia existente de Starlette/TestClient sobre HTTPX; no se silencia ni se cambian dependencias por esta entrega. No hay pruebas de carga, navegador o datos reales; no se modifica frontend.

## Entrega al socio y pendientes

El socio revisara nomenclatura de permisos y asignaciones por cuenta/recurso, etiquetas/privacidad de sus glosas, cobertura/conciliacion, independencia de revisores y custodia de archivos/clave. Las pruebas locales no certifican precision ni calibracion. La activacion real requiere modelos/evaluacion legitimos, cargador e inferencia confiables, pruebas operativas y aprobacion; no se entrega por tener API.

ML-11 queda preparado como **API sintetica apagada**, sin permisos nuevos en QA/original. ML-12 (interfaz piloto) no se inicia automaticamente. Sin entrenamiento, modelos cargados, skills incluidas, push o contacto con el socio.
