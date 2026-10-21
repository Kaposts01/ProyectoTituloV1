# Plan de Mantención — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Rutinas de mantención preventiva, correctiva y evolutiva del sistema.

---

## 1. Mantención rutinaria (operador)

### Diaria

| Tarea | Cómo verificar | Acción si falla |
|-------|---------------|----------------|
| Verificar último SyncRun | `GET /sync/runs?limit=3` | Re-ejecutar sync del proveedor afectado |
| Verificar último EtlRun | `GET /etl/runs?limit=3` | Revisar logs; re-ejecutar si la causa se resolvió |
| Verificar contenedores Docker | `docker compose ps` | `docker compose up -d` |
| Revisar espacio en disco | `df -h` | Limpiar logs o backups antiguos |

### Mensual

| Tarea | Descripción |
|-------|-------------|
| **Cargar Excel TCH** | Procesar el reporte mensual TCH cuando llega |
| **Revisar candidatos de merge** | Procesar `client_match_candidates` acumulados |
| **Backup verificado** | Confirmar que el backup diario del mes existe y es restaurable |
| **Revisar logs de errores** | Buscar patrones de error recurrentes en FastAPI logs |
| **Actualizar `tch_recaudacion_mensual`** | Verificar que el mes quedó registrado correctamente |

### Trimestral

| Tarea | Descripción |
|-------|-------------|
| Rotar credenciales de proveedor | Si las APIs lo requieren o recomiendan |
| Revisar volumen de `source_records` | Evaluar si es necesario archivar records muy antiguos |
| Revisar índices de PostgreSQL | `VACUUM ANALYZE` en tablas de > 100k filas |
| Actualizar dependencias Python | `pip list --outdated`; evaluar impacto antes de actualizar |

---

## 2. Comandos de mantención frecuentes

### Verificación del sistema

```bash
# Estado de contenedores
docker compose ps

# Salud de la BD
docker exec crm-postgres-1 psql -U crm -c "SELECT version();"

# Espacio en tablas grandes
docker exec crm-postgres-1 psql -U crm -c "
SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::text)) AS size
FROM pg_tables WHERE schemaname='public'
ORDER BY pg_total_relation_size(tablename::text) DESC LIMIT 10;"

# Estado de migraciones
.venv/Scripts/alembic.exe current
```

### Sincronización y ETL

```bash
# Sync individual
curl -X POST http://localhost:8000/sync/virtualpos1
curl -X POST http://localhost:8000/sync/toku
curl -X POST http://localhost:8000/sync/payku

# ETL global
curl -X POST http://localhost:8000/etl/core/all

# Ver últimos runs
curl http://localhost:8000/sync/runs?limit=5
curl http://localhost:8000/etl/runs?limit=5
```

### Carga TCH

```bash
# Cargar un archivo Excel TCH
PYTHONPATH=. .venv/Scripts/python.exe -m app.etl.tch.load \
    --file "C:/Users/Usuario/Downloads/20260930 TCH IG SEPTIEMBRE 2026.XLSX (1)/20260930 TCH IG SEPTIEMBRE 2026.XLSX"
```

### Mantención de PostgreSQL

```bash
# VACUUM en tablas grandes (no bloquea escrituras)
docker exec crm-postgres-1 psql -U crm -c "VACUUM ANALYZE tch_transacciones;"
docker exec crm-postgres-1 psql -U crm -c "VACUUM ANALYZE source_records;"
docker exec crm-postgres-1 psql -U crm -c "VACUUM ANALYZE vp_payments;"

# Backup manual
docker exec crm-postgres-1 pg_dump -U crm crm > backup_manual_$(date +%Y%m%d_%H%M).sql
```

---

## 3. Mantención correctiva — diagnóstico de problemas comunes

### "La sync falla silenciosamente"

```bash
# Ver el último run con status failed
docker exec crm-postgres-1 psql -U crm -c "
SELECT provider, status, error_message, started_at
FROM sync_runs ORDER BY started_at DESC LIMIT 5;"

# Ver logs del contenedor
docker compose logs api --tail 100 | grep -i error
```

**Causas frecuentes:**
- Credencial expirada: actualizar `.env` + reiniciar
- Timeout de red: reintento manual
- API proveedor caída: esperar y reintentar

### "El Core Layer tiene datos inconsistentes"

```bash
# Verificar EtlRun
docker exec crm-postgres-1 psql -U crm -c "
SELECT provider, status, records_created, records_updated, error_message
FROM etl_runs ORDER BY started_at DESC LIMIT 10;"

# Comparar staging vs Core
# VirtualPOS
docker exec crm-postgres-1 psql -U crm -c "
SELECT COUNT(*) FROM vp_payments WHERE status='pagado';"  -- debe ~= core_payments con source VP

# Re-ejecutar ETL del proveedor afectado
curl -X POST http://localhost:8000/etl/core/virtualpos
```

### "PostgreSQL usa demasiado disco"

```bash
# Ver tamaño de la BD completa
docker exec crm-postgres-1 psql -U crm -c "SELECT pg_size_pretty(pg_database_size('crm'));"

# Identificar tablas más grandes
docker exec crm-postgres-1 psql -U crm -c "
SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::text))
FROM pg_tables WHERE schemaname='public'
ORDER BY pg_total_relation_size(tablename::text) DESC LIMIT 10;"

# Archivar source_records muy antiguos (con precaución)
# Solo si se confirma que los datos ya están en staging y Core
-- No ejecutar sin confirmación explícita
```

---

## 4. Mantención evolutiva (equipo técnico)

### Agregar un nuevo proveedor

1. Crear conector en `app/connectors/{provider}_connector.py`
2. Crear modelos SQLAlchemy en `app/models/{provider}_channel.py`
3. Crear migración Alembic
4. Crear servicio sync en `app/services/{provider}_sync.py`
5. Crear ETL Core en `app/services/core_{provider}_etl.py`
6. Agregar endpoints en `app/routers/`
7. Crear tests de integración
8. Documentar en `docs/integrations/{provider}.md`
9. Actualizar `docs/engineering/datos/09-analisis-contratos-api.md`

### Aplicar una migración en producción

```bash
# 1. Backup previo (obligatorio)
docker exec crm-postgres-1 pg_dump -U crm crm > backup_pre_migration_$(date +%Y%m%d).sql

# 2. Verificar la migración en staging primero
PYTHONPATH=. .venv/Scripts/alembic.exe upgrade head

# 3. Confirmar que alembic current coincide con la migración esperada
.venv/Scripts/alembic.exe current

# 4. Verificar que la aplicación inicia correctamente
docker compose restart api
curl http://localhost:8000/health
```

### Actualizar dependencias Python

```bash
# Ver outdated
.venv/Scripts/pip.exe list --outdated

# Actualizar una dependencia específica (evaluar impacto antes)
.venv/Scripts/pip.exe install --upgrade {package}

# Verificar que los tests siguen pasando
PYTHONPATH=. .venv/Scripts/pytest.exe tests/ -x

# Actualizar requirements.txt
.venv/Scripts/pip.exe freeze > requirements.txt
```

---

## 5. Health stack de referencia

Comandos del ciclo de validación antes de merge:

```bash
# Typecheck frontend
cd frontend && npx tsc --noEmit

# Lint Python
ruff check .

# Lint frontend
cd frontend && npm run lint

# Tests Python
PYTHONPATH=. .venv/Scripts/pytest.exe
```

---

*Documento generado el 2026-10-20.*
