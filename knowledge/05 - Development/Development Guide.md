# Development Guide

## Mapa de desarrollo

- [README principal](../../README.md)
- [Backend](../../app/)
- [Frontend](../../frontend/)
- [Tests](../../tests/)
- [Migraciones Alembic](../../alembic/)
- [Scripts operativos](../../scripts/)

## Comandos verificados

Desde la raiz del repositorio, la documentacion indica:

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload
.\.venv\Scripts\python.exe scripts\sync_virtualpos.py
.\.venv\Scripts\python.exe scripts\sync_toku.py
.\.venv\Scripts\python.exe scripts\sync_payku.py
python -m pytest
ruff check app tests alembic scripts
```

Para el frontend, `frontend/package.json` define `npm run dev`, `npm run build`, `npm run lint` y `npm run preview`.

## Referencias tecnicas

- [Operacion local](../../README.md)
- [Instrucciones del proyecto](../../AGENTS.md)
- [Estado de tareas](../../docs/tasks.md)
