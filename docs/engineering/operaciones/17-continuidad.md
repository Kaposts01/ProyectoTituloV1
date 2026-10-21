# Plan de Continuidad del Negocio — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Garantizar que las operaciones de recaudación y consulta de socios puedan continuar ante fallas del sistema.

---

## 1. Contexto de criticidad

SynkmetriX CRM centraliza datos de ~40,000 socios activos provenientes de VirtualPOS, Toku, Payku y TCH. Los procesos de negocio que dependen del sistema:

| Proceso | Dependencia del CRM | Criticidad |
|---------|-------------------|-----------|
| Consulta de estado de socios | Alta — operadores usan el CRM para resolver consultas | Alta |
| Carga mensual de recaudación TCH | Media — puede retrasarse hasta 48h | Media |
| Reconciliación de pagos | Alta — detectar rechazos y gestionar reintentos | Alta |
| Deduplicación cross-canal | Media — proceso periódico, no tiempo real | Media |
| Reportes de recaudación | Media — pueden generarse con datos del día anterior | Media |

---

## 2. Escenarios de contingencia

### Escenario A — API no disponible (corto plazo < 4h)

**Impacto:** Operadores no pueden consultar el CRM.

**Procedimiento:**
1. Notificar al equipo que el sistema está en mantenimiento
2. Consultas urgentes de socios: acceder directamente a la plataforma del proveedor (VirtualPOS, Toku, Payku)
3. Consultas TCH: acceder al último Excel cargado

**Tiempo máximo tolerable:** 4 horas sin escalar a P1.

### Escenario B — PostgreSQL caído o datos corruptos

**Impacto:** Sistema completo no funcional; pérdida potencial de datos si no hay backup.

**Procedimiento:**
1. Activar modo solo-lectura desde backups si está disponible
2. Notificar P1 al equipo de tecnología
3. Restaurar desde último backup verificado (ver `16-disponibilidad.md`)
4. Re-sincronizar desde proveedores para recuperar datos post-backup
5. Re-ejecutar ETL Core

**Datos que NO son recuperables:**
- Decisiones de merge manual (`client_match_candidates` con `status=accepted`) si no hay backup
- Runs de sync/ETL posteriores al último backup

**Datos que SÍ son recuperables:**
- Todo lo que está en `source_records` (siempre se puede re-sincronizar)
- `tch_transacciones` y demás tablas de canal (re-cargar desde Excel)
- Core Layer completo (reconstruible desde staging)

### Escenario C — Proveedor externo caído (VP / Toku / Payku)

**Impacto:** Sync no se puede ejecutar para ese proveedor.

**Procedimiento:**
1. El sistema continúa operando con datos del último sync
2. Registrar la falla en `SyncRun` con `status='failed'`
3. Monitorear el estado del proveedor
4. Re-ejecutar sync cuando el proveedor vuelva a estar disponible
5. Los datos de Core reflejan el estado al momento del último sync exitoso

**Máximo de datos "stale" aceptable:** 48 horas.

### Escenario D — Pérdida del host completo

**Impacto:** Sistema completamente no disponible; riesgo de pérdida de datos.

**Procedimiento:**
1. Recuperar último backup de PostgreSQL desde almacenamiento externo
2. Instalar Docker en nuevo host
3. Restaurar configuración desde git + `.env` desde respaldo seguro
4. `docker compose up -d`
5. Restaurar BD desde backup
6. Verificar migraciones: `alembic current`
7. Re-sincronizar todos los proveedores
8. Re-ejecutar ETL Core

**Tiempo estimado de recuperación total:** 2–4 horas con backup disponible.

---

## 3. Prioridades de recuperación

En caso de recursos limitados, restaurar en este orden:

1. **PostgreSQL con tablas de staging** — sin staging no hay nada
2. **API en modo solo-lectura** — operadores pueden consultar
3. **Sync de proveedores** — datos frescos
4. **ETL Core** — Core Layer reconstruible
5. **Frontend** — última prioridad (backend es suficiente vía API)

---

## 4. Datos críticos y su ubicación

| Dato | Ubicación primaria | Recuperable sin backup |
|------|-------------------|----------------------|
| Socios y mandatos TCH | `tch_clientes`, `tch_suscripciones` | Sí (re-cargar Excel) |
| Transacciones TCH históricas | `tch_transacciones` | Sí (29 archivos Excel) |
| Suscripciones VP | `vp_subscriptions`, `source_records` | Sí (re-sync) |
| Pagos VP históricos | `vp_payments`, `source_records` | Sí (re-sync) |
| Datos Toku | `tk_*`, `source_records` | Sí (re-sync) |
| Datos Payku | `p_*`, `source_records` | Sí (re-sync) |
| Core Layer | `core_*` | Sí (re-ETL desde staging) |
| Decisiones de merge | `client_match_candidates` | **No** — requiere backup |
| Configuración de usuarios | Auth tables | **No** — requiere backup |

---

## 5. Comunicación en incidentes

| Situación | A quién notificar | Cómo | En cuánto tiempo |
|-----------|-----------------|------|-----------------|
| P1 (sistema caído) | Líder técnico + equipo datos | Directo / llamada | Inmediatamente |
| P2 (sync fallida > 24h) | Equipo datos | Chat interno | < 1 hora |
| P3 (datos stale) | Equipo operativo | Email/chat | < 4 horas |
| Mantenimiento planificado | Todos los usuarios | Email | 24h antes |

---

*Documento generado el 2026-10-20.*
