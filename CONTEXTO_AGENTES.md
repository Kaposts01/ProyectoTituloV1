# Contexto para agentes: CRM SynkmetriX

Ficha corta que leen el líder y los especialistas (`backend`, `api`, `frontend`) antes de trabajar aquí. El detalle está en `CLAUDE.md`, `AGENTS.md`, `handoff.md`, `docs/tasks.md` y `docs/operations/estado-produccion.md`. Escrita el 2026-11-16, después del traslado a `01-Trabajo` (d232). Si algo no calza, mandan esos archivos.

## Qué es

CRM de socios y donantes de la organización. Centraliza socios, suscripciones, cobros y pagos de cuatro canales: VirtualPOS, Toku y Payku (por API) y TCH (por Excel). Está en uso real: **el puerto 8000 es producción**.

## Ubicación y git

- Carpeta: `C:\Users\Usuario\Proyectos\01-Trabajo\CRM_projectoTitulo`
- Rama principal: `master`. Remoto: `https://github.com/Kaposts01/ProyectoTituloV1`. Cada push, merge y migración la autoriza el usuario en el chat del CRM.
- Tareas: colección `crm_tareas` de la Bandeja. Fichas de decisión: `dNNN`.
- Reportes de proveedores (con datos personales, fuera del repo): `01-Trabajo\Reportes-Canales\<canal>`.
- Respaldos: `01-Trabajo\CRM_projectoTitulo-respaldos` (`scripts\maintenance\backup_db.ps1`).

## Stack

| Parte | Tecnología | Carpeta |
|---|---|---|
| Backend | FastAPI, SQLAlchemy, Alembic, Python 3.14 (`.venv`) | `app\`, `alembic\`, `scripts\` |
| Frontend | React + Vite + TypeScript | `frontend\` |
| Base | PostgreSQL 17 en Docker (`compose.yaml`, `name: crm_projectotitulo`) | volumen `crm_projectotitulo_postgres_data` |

## Entornos

| Entorno | Backend | Frontend | Base |
|---|---|---|---|
| Producción | `127.0.0.1:8000` (`--reload`) | `5173`: build servida con `vite preview` (d247). Tras cada pull: `npm run build` y reiniciar el 5173; sin rebuild queda la versión anterior | `crm` |
| Sandbox | `127.0.0.1:8001` (`scripts\run_sandbox_backend.ps1`, **sin** reload: reiniciar tras cada merge) | `5174` (`npm run dev:sandbox`) | `crm_sandbox` |
| Pruebas | — | — | `crm_test` (pytest la borra y la recrea en cada sesión) |

Postgres en `127.0.0.1:5433`. Comandos para levantar todo: `00-Sistema-Agentico\REANUDAR_SESIONES.md`.

## Pruebas

- Backend: `$env:PYTHONPATH='.'; .venv\Scripts\pytest.exe -q -p no:cacheprovider --basetemp=<carpeta temporal>`.
  - Desde un worktree: `CRM_DOTENV_PATH` apuntando al `.env` del checkout principal.
  - Con `frontend\dist` presente fallan 4 pruebas de `test_authz_route_matrix` en local; en el CI pasan.
- Si cambias una función compartida, incluye en la prueba acotada a quienes la llaman (`git grep`).
- Estilo: `ruff check .`. Frontend: `cd frontend; npx tsc --noEmit; npm run lint`.
- El CI de GitHub (backend y frontend) tiene que estar en verde antes del merge.

## Reglas propias

- **El `.venv` es de producción.** Instalar o cambiar paquetes se hace con el usuario.
- **Escrituras a proveedores:** solo con las banderas `*_WRITES_ENABLED` (y en sandbox `*_SANDBOX_WRITES_ENABLED` con su armado) y con instrucción explícita. Nunca en una prueba sin autorización.
- **Identidad de socios:** leer `docs\decisions\ADR-001-identidad-centralizada-socios.md` antes de tocar matching, deduplicación o fusión. RUT, correo o teléfono no son una identidad universal.
- **Migraciones:** se aplican en `crm` y `crm_sandbox` en una ventana: respaldo, detener 8000 y 8001 (por puerto), `alembic upgrade head` con `APP_ENV` comprobado, merge, levantar y `/health`. Integrar antes de migrar hace caer producción por el `--reload`.
- **Borrados masivos:** comprobar antes que cada FK que apunta a la tabla tenga índice (la 0081 nació de eso).
- **Scripts contra producción:** `APP_ENV=production` y sin `DATABASE_URL` en el entorno. Comprobar que imprima «production crm» antes de seguir.
- Valores del `.env`: nunca se imprimen; solo se mira si la variable tiene valor.
- Nada de datos personales en el repo, en los documentos ni en las capturas. Las capturas, solo del sandbox con datos sintéticos.
- 20 logins fallidos desde una IP la bloquean, y todo el uso local sale de `127.0.0.1`.
- Trabajo pesado (recargas, Core, pytest completa, graphify): pedir turno al Orquestador. Tope de CPU y RAM: 90 %.

## Pendiente conocido

d224 (estados de cobro), PK-07 y PK-09 (prueba de 1 CLP en Payku, con confirmación antes de cada escritura). Estado al día en `docs\operations\estado-produccion.md`.
