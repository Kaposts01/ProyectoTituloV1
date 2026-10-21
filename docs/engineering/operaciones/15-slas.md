# SLAs — SynkmetriX CRM

**Última actualización:** 2026-10-20
**Propósito:** Definición de niveles de servicio para los componentes críticos del sistema.

---

## 1. Contexto y alcance

SynkmetriX opera en un entorno interno de Techo — no es un servicio público. Los SLAs aplican al equipo de datos/tecnología y a los equipos operativos que dependen del sistema para:
- Consultar el estado de socios y sus pagos
- Ejecutar sincronizaciones y ETL
- Revisar candidatos de merge y rechazos

El sistema corre actualmente en infraestructura local (Docker) y no tiene SLA con SLO formales de producción cloud. Estos SLAs son metas de diseño y operación.

---

## 2. SLAs por componente

### 2.1 API FastAPI (servicio de consulta)

| Indicador | Meta | Medición |
|-----------|------|----------|
| Disponibilidad horario laboral (8:00–20:00 CLT) | ≥ 99% | Uptime check cada 5 min |
| Latencia P95 en endpoints de consulta | ≤ 2 segundos | Logs de respuesta |
| Latencia P95 en endpoints de sincronización (POST) | Asíncrono — respuesta 202 inmediata | Respuesta HTTP |
| Tasa de error 5xx | < 1% | Logs de error |

### 2.2 PostgreSQL (base de datos)

| Indicador | Meta |
|-----------|------|
| Disponibilidad | ≥ 99.5% |
| Tiempo de respuesta a queries simples (< 100k filas) | ≤ 500ms |
| Tiempo de respuesta a queries analíticas (> 500k filas) | ≤ 10s |
| Backup diario exitoso | 100% (sin fallas) |

### 2.3 Sincronización de proveedores

| Proveedor | Frecuencia mínima | Latencia máxima | SLA disponibilidad |
|-----------|------------------|-----------------|-------------------|
| VirtualPOS | 1 vez/día | 5 min | Dependiente de API VP |
| Toku | 1 vez/día | 5 min | Dependiente de API Toku |
| Payku | 1 vez/día | 5 min | Dependiente de API Payku |
| TCH (Excel) | 1 vez/mes | 30 min desde recepción | Manual — no automatizable |

**Nota:** Los SLAs de sync dependen de la disponibilidad de las APIs de terceros. Si una API está caída, se registra `SyncRun.status='failed'` y se reintenta en el siguiente ciclo.

### 2.4 ETL Core (materialización)

| Indicador | Meta |
|-----------|------|
| Latencia por proveedor | ≤ 10 min |
| Latencia global (`/etl/core/all`) | ≤ 30 min |
| Tasa de éxito | ≥ 99% de registros procesados sin error |
| Frecuencia mínima | 1 vez/día (post-sync) |

---

## 3. Definición de incidentes por severidad

| Severidad | Definición | Tiempo de respuesta | Tiempo de resolución |
|-----------|-----------|--------------------|--------------------|
| **P1 — Crítico** | BD caída o inaccesible; pérdida de datos; API completamente no disponible | 15 min | 2 horas |
| **P2 — Alto** | Sync fallida por > 24h; ETL fallido impidiendo consultas; datos incorrectos en Core | 1 hora | 8 horas |
| **P3 — Medio** | Sync parcial; candidatos de match acumulados; TCH no cargado a tiempo | 4 horas | 2 días |
| **P4 — Bajo** | KPI no disponible; documento desactualizado; alerta de umbral cruzado | 1 día | 1 semana |

---

## 4. Exclusiones de SLA

Los SLAs no aplican en los siguientes escenarios:
- Mantenimiento planificado con aviso de 24h de anticipación
- Caídas de APIs de proveedores externos (VirtualPOS, Toku, Payku)
- Carga de archivos TCH fuera del ciclo mensual esperado
- Cambios urgentes de credenciales de proveedor (requieren reinicio manual)
- Accesos desde red externa sin VPN configurada

---

## 5. Contactos operativos

| Rol | Responsabilidad |
|-----|----------------|
| Equipo de datos | Monitoreo diario de SyncRun y EtlRun; carga mensual de TCH |
| Equipo de tecnología | Resolución de P1/P2; migraciones; cambios de infraestructura |
| Área de recaudación | Alertar anomalías en datos de socios; validar cartera mensual |

---

*Documento generado el 2026-10-20.*
