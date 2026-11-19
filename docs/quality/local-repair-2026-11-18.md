# Reparacion y operacion local — 2026-11-18

> **Registro histórico del equipo de cabarca (18/11).** Describe su checkout local (PostgreSQL 18 nativo, `.env.local`, copia de QA), no el entorno de este proyecto. El estado vigente está en `docs/memory/PROJECT_STATE.md`.

## Alcance

Rama `codex/actualizacion-20261118`. Cambios exclusivamente locales; no push ni merge a master. Este informe actualiza los limites de `update-comparison-2026-11-18.md`.

## Correcciones

- Snapshots: se normalizan los IDs React useId en orden de aparicion, conservando IDs distintos y relaciones id/aria-controls/aria-describedby. Se compararon los originales: la diferencia era el contador global de React. Tres pruebas puras protegen referencias correctas, referencias rotas y IDs normales; 27 pruebas focalizadas de staging y normalizacion pasan. Los snapshots solo cambian en los IDs normalizados.
- Dependencias: Vite 8.3.8, Vitest y coverage-v8 5.1.0, source-map-js 1.2.2, plugin-react 6.1.1 transitivamente. Package lock actualizado. No se uso audit fix --force ni se degradaron versiones mayores.
- Desarrollo local: Vite escucha por defecto en 127.0.0.1 y no acepta cualquier hostname. El proxy sigue en 127.0.0.1:8000.
- Datos centralizados: modelo Core y revision nueva 20261118_0082 conservan atributos compartidos por cliente/fuente y evitan duplicados con client_id null. Se recuperan y adaptan las pruebas de integridad al modelo actual. No se cambian migraciones historicas ni se reasignan identidades.
- Backend: las conexiones SQL fijan UTC para evitar fechas del dia anterior en PostgreSQL configurado con America/Santiago. Una prueba real comprueba SHOW timezone y la lectura de un timestamptz; las consultas de negocio que usan Chile mantienen su conversion explicita. Se clasifican las dos rutas publicas de la SPA en la matriz de permisos y se aislan las variables opcionales en las pruebas de alias de proveedores.
- PostgreSQL 18 nativo: se arranco la instancia existente de `.local/postgres18/data` en 127.0.0.1:5433. Las conexiones de validacion usan IPv4; localhost podia intentar IPv6 donde esta instancia no escucha.

## Respaldo, copia y cuarentena autorizada

- Respaldo custom de crm: `.local/backups/crm-before-local-repair-20261118.dump`, 20.404.093 bytes. Restaurado correctamente en `crm_qa_local_20261118`.
- crm original permanece en su revision local 20261020_0032 y no se migra. Aquella 0032 aplico atributos y no source_status; se agregaron source_status y su indice SOLO en la copia antes de continuar la cadena publicada.
- El usuario autorizo guardar todos los grupos de suscripciones VirtualPOS conflictivas en cuarentena. Ocho filas se conservaron en `local_repair_archive.vp_subscriptions`, con su estructura previa a las migraciones. La proyeccion queda con 12 filas; 12 + 8 = 20 originales. No se eligio un ganador ni se inventaron estados de cancelacion. Los datos archivados requieren revision antes de volver a la proyeccion migrada.
- Copia migrada hasta 0082; alembic check no detecta operaciones pendientes. Hay advertencia previa de ciclo FK billing_change_requests/write_runs, sin cambio destructivo.
- Permisos y roles actualizados solo en la copia. No se repitio ETL, importacion ni sincronizacion de proveedores.

## Operacion

- API: http://127.0.0.1:8000, frontend: http://127.0.0.1:5173.
- Backend usa `.env.local` (ignorado), APP_ENV=qa, SANDBOX_DATABASE_URL hacia la copia y clave JWT separada. Scheduler y escrituras de proveedores apagados; llaves de proveedores sandbox vacias.
- La configuracion original .env se conserva. No iniciar el backend actualizado con el comando uvicorn sin seleccionar .env.local: apuntaria a la base original antigua.
- Tras reiniciar Windows, arrancar la instancia existente (no initdb): `& "C:/Program Files/PostgreSQL/18/bin/pg_ctl.exe" start -D "$PWD/.local/postgres18/data" -l "$PWD/logs/postgres18.log" -o "-h 127.0.0.1 -p 5433"`.
- Reinicio backend desde PowerShell en la raiz: `./scripts/run_local_backend.ps1`.
- Reinicio frontend: `npm.cmd --prefix frontend run dev`.
- Logs: `logs/local-api.out.log`, `logs/local-api.err.log`, `logs/local-frontend.out.log`, `logs/local-frontend.err.log`. IDs de los procesos iniciados en `.local/local-runtime-processes.json` (pueden ser wrappers de Windows; confirmar el proceso que escucha antes de detener).
- Usuario y contrasena existentes conservados en la copia. Login verificado sin imprimir contrasenas, cookies ni tokens.
- Smoke HTTP: health, heartbeat, login, auth/me, dashboard general, resumen TCH, frontend y proxy Vite responden 200. No equivale a una revision visual completa.

## Seguridad de dependencias

`npm audit --omit=dev` da cero vulnerabilidades. La auditoria total sigue reportando siete paquetes de herramientas de desarrollo debido a una sola raiz: picomatch 4.0.7. El registro npm no ofrece una version posterior y el aviso indica que no hay parche publicado. No se oculta la alerta ni se sustituye por un fork no verificado. Las actualizaciones resolvieron los avisos independientes de Vite y source-map-js, aunque el total de paquetes afectados no disminuye por la propagacion de picomatch.

Fuentes: [picomatch GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf), [Vite/launch-editor GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm).

## Validacion final

Frontend completo: 108 archivos y 1.464 pruebas pasan (incluye las tres nuevas de IDs). Lint sin errores y build pasan con las dependencias actualizadas. Ruff y smoke HTTP pasan. La primera suite completa detecto 21 fallos por zona horaria del host, rutas SPA al existir build y variables opcionales del entorno. Tras corregir esas causas, 598 pruebas focalizadas pasan y 21 se omiten por diseno de la matriz de permisos. Resultado final: 3.747 pruebas Python pasan y 23 se omiten por guardas de permisos y rendimiento optativo; tres advertencias previas (Starlette/httpx y ciclo FK). Las migraciones desde cero se ejecutaron en la base descartable de pruebas. No se ejecutaron suites de contrato contra proveedores reales.

Documentacion tecnica consultada (Context7 no disponible): [SQLAlchemy connect_args](https://docs.sqlalchemy.org/en/20/core/engines.html#use-the-connect-args-dictionary-parameter), [PostgreSQL options](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-OPTIONS).

Commits locales de correccion: b499d2b (frontend) y dff48d7 (backend/datos/arranque). Documentacion y cierre se guardan en un commit local posterior. No se ejecuto push.
