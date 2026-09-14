/*
 * QUERIES SQL ÚTILES PARA CRM SUSCRIPCIONES
 *
 * Casos de uso operacionales, reportes y análisis
 * Para usar una vez que la BD esté implementada
 */

-- ============================================================================
-- 1. VALIDACIÓN DE INTEGRIDAD (POST-CARGA)
-- ============================================================================

-- Verificar que no hay transacciones huérfanas
SELECT COUNT(*) as transacciones_sin_suscripcion
FROM transacciones_mensuales tm
WHERE NOT EXISTS (
    SELECT 1 FROM suscripciones s
    WHERE s.id_suscripcion = tm.id_suscripcion
);

-- Verificar conteo de registros por tabla
SELECT
    'clientes' as tabla, COUNT(*) as registros FROM clientes
UNION ALL SELECT 'suscripciones', COUNT(*) FROM suscripciones
UNION ALL SELECT 'transacciones_mensuales', COUNT(*) FROM transacciones_mensuales
UNION ALL SELECT 'transacciones_detalles', COUNT(*) FROM transacciones_detalles
ORDER BY tabla;

-- Duplicados por ficha (no debería haber)
SELECT numero_ficha, COUNT(*) as duplicados
FROM suscripciones
GROUP BY numero_ficha
HAVING COUNT(*) > 1;

-- Duplicados de periodo/suscripción (no debería haber)
SELECT id_suscripcion, periodo, COUNT(*) as duplicados
FROM transacciones_mensuales
GROUP BY id_suscripcion, periodo
HAVING COUNT(*) > 1;

-- ============================================================================
-- 2. EXPLORACIÓN DE DATOS
-- ============================================================================

-- Últimas 10 suscripciones agregadas
SELECT s.numero_ficha, s.numero_mandato, c.nombre, c.rut,
       b.nombre as banco, s.fecha_activacion, s.estado, s.created_at
FROM suscripciones s
JOIN clientes c ON s.id_cliente = c.id_cliente
JOIN bancos b ON s.id_banco = b.id_banco
ORDER BY s.created_at DESC
LIMIT 10;

-- Suscripciones por banco (vigentes)
SELECT b.nombre as banco, COUNT(*) as total
FROM suscripciones s
JOIN bancos b ON s.id_banco = b.id_banco
WHERE s.estado = 'VIGENTE'
GROUP BY b.id_banco, b.nombre
ORDER BY total DESC;

-- Suscripciones por origen (estrategia de captación)
SELECT o.nombre as origen, COUNT(*) as total,
       COUNT(CASE WHEN s.estado = 'VIGENTE' THEN 1 END) as vigentes,
       COUNT(CASE WHEN s.estado = 'ELIMINADA' THEN 1 END) as eliminadas
FROM suscripciones s
LEFT JOIN origenes o ON s.id_origen = o.id_origen
GROUP BY s.id_origen, o.nombre
ORDER BY total DESC;

-- Clientes con múltiples mandatos
SELECT c.nombre, c.apellido, c.rut, COUNT(*) as mandatos_vigentes
FROM suscripciones s
JOIN clientes c ON s.id_cliente = c.id_cliente
WHERE s.estado = 'VIGENTE'
GROUP BY s.id_cliente, c.nombre, c.apellido, c.rut
HAVING COUNT(*) > 1
ORDER BY mandatos_vigentes DESC;

-- ============================================================================
-- 3. ANÁLISIS DE TRANSACCIONES
-- ============================================================================

-- Tasa de aceptación por mes (últimos 6 meses)
SELECT
    tm.periodo,
    COUNT(*) as total_cargos,
    SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN 1 ELSE 0 END) as aceptados,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) as rechazados,
    ROUND(100.0 * SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN 1 ELSE 0 END) / COUNT(*), 2) as tasa_aceptacion
FROM transacciones_mensuales tm
WHERE tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 6 MONTH), '%Y-%m')
GROUP BY tm.periodo
ORDER BY tm.periodo DESC;

-- Ingresos mensuales consolidados
SELECT
    tm.periodo,
    COUNT(DISTINCT tm.id_suscripcion) as mandatos_activos,
    SUM(tm.monto) as total_facturado,
    SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN tm.monto ELSE 0 END) as ingresos_realizados,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN tm.monto ELSE 0 END) as ingresos_rechazados
FROM transacciones_mensuales tm
WHERE tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 6 MONTH), '%Y-%m')
GROUP BY tm.periodo
ORDER BY tm.periodo DESC;

-- Tasa de aceptación por banco
SELECT
    b.nombre as banco,
    COUNT(DISTINCT s.id_suscripcion) as mandatos,
    COUNT(DISTINCT tm.id_transaccion) as total_cargos,
    SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN 1 ELSE 0 END) as aceptados,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) as rechazados,
    ROUND(100.0 * SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN 1 ELSE 0 END) / COUNT(DISTINCT tm.id_transaccion), 2) as tasa_aceptacion
FROM suscripciones s
JOIN bancos b ON s.id_banco = b.id_banco
JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
WHERE s.estado = 'VIGENTE' AND tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 3 MONTH), '%Y-%m')
GROUP BY b.id_banco, b.nombre
ORDER BY tasa_aceptacion ASC;

-- Motivos de rechazo más comunes (últimos 3 meses)
SELECT
    td.razon_rechazo,
    COUNT(*) as cantidad,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM transacciones_detalles
                               WHERE estado_detalle = 'RECHAZADA'
                               AND fecha_procesamiento >= DATE_SUB(NOW(), INTERVAL 3 MONTH)), 2) as porcentaje
FROM transacciones_detalles td
WHERE td.estado_detalle = 'RECHAZADA'
  AND td.fecha_procesamiento >= DATE_SUB(NOW(), INTERVAL 3 MONTH)
GROUP BY td.razon_rechazo
ORDER BY cantidad DESC
LIMIT 10;

-- ============================================================================
-- 4. DETECCIÓN DE PROBLEMAS (ALERTAS AUTOMÁTICAS)
-- ============================================================================

-- Mandatos sin cargos en últimos 2 meses (potencial cancelación)
SELECT s.numero_ficha, s.numero_mandato, c.nombre, c.rut, b.nombre as banco,
       MAX(tm.fecha_cargo) as ultimo_cargo
FROM suscripciones s
JOIN clientes c ON s.id_cliente = c.id_cliente
JOIN bancos b ON s.id_banco = b.id_banco
LEFT JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
WHERE s.estado = 'VIGENTE'
GROUP BY s.id_suscripcion
HAVING MAX(tm.fecha_cargo) < DATE_SUB(CURDATE(), INTERVAL 2 MONTH)
ORDER BY MAX(tm.fecha_cargo) DESC;

-- Tarjetas vencidas (múltiples rechazos por "tarjeta vencida")
SELECT c.nombre, c.apellido, c.rut,
       GROUP_CONCAT(s.numero_mandato) as mandatos,
       COUNT(DISTINCT tm.periodo) as periodos_fallidos,
       MAX(td.fecha_procesamiento) as ultimo_intento
FROM clientes c
JOIN suscripciones s ON c.id_cliente = s.id_cliente
JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
JOIN transacciones_detalles td ON tm.id_transaccion = td.id_transaccion
WHERE td.razon_rechazo LIKE '%vencid%'
  AND s.estado = 'VIGENTE'
  AND td.fecha_procesamiento >= DATE_SUB(NOW(), INTERVAL 2 MONTH)
GROUP BY c.id_cliente
ORDER BY ultimo_intento DESC;

-- Clientes con alta tasa de rechazo (para contacto proactivo)
SELECT c.nombre, c.apellido, c.rut,
       COUNT(DISTINCT tm.periodo) as periodos_cobrados,
       SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) as cargos_rechazados,
       ROUND(100.0 * SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) / COUNT(*), 2) as tasa_rechazo
FROM clientes c
JOIN suscripciones s ON c.id_cliente = s.id_cliente
JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
WHERE s.estado = 'VIGENTE'
  AND tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 3 MONTH), '%Y-%m')
GROUP BY c.id_cliente
HAVING tasa_rechazo > 30
ORDER BY tasa_rechazo DESC;

-- Reintentos necesarios (transacciones rechazadas con solo 1 intento)
SELECT tm.id_transaccion, s.numero_ficha, c.nombre, c.rut, b.nombre as banco,
       tm.periodo, tm.monto, MAX(td.fecha_procesamiento) as fecha_rechazo,
       td.razon_rechazo
FROM transacciones_mensuales tm
JOIN suscripciones s ON tm.id_suscripcion = s.id_suscripcion
JOIN clientes c ON s.id_cliente = c.id_cliente
JOIN bancos b ON s.id_banco = b.id_banco
JOIN transacciones_detalles td ON tm.id_transaccion = td.id_transaccion
WHERE tm.estado_consolidado = 'RECHAZADA'
  AND s.estado = 'VIGENTE'
  AND tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 1 MONTH), '%Y-%m')
  AND (SELECT COUNT(*) FROM transacciones_detalles WHERE id_transaccion = tm.id_transaccion) = 1
ORDER BY td.fecha_procesamiento DESC;

-- ============================================================================
-- 5. ANÁLISIS POR CENTRO DE COSTO
-- ============================================================================

-- Desempeño por centro de costo
SELECT
    cc.nombre as centro_costo,
    COUNT(DISTINCT s.id_suscripcion) as mandatos_vigentes,
    COUNT(DISTINCT tm.id_transaccion) as total_cargos_mes,
    SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN tm.monto ELSE 0 END) as ingresos_aceptados,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN tm.monto ELSE 0 END) as ingresos_rechazados,
    ROUND(100.0 * SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN 1 ELSE 0 END) / COUNT(DISTINCT tm.id_transaccion), 2) as tasa_aceptacion
FROM suscripciones s
LEFT JOIN centros_costo cc ON s.id_centro_costo = cc.id_centro
LEFT JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
    AND tm.periodo = DATE_FORMAT(LAST_DAY(DATE_SUB(NOW(), INTERVAL 1 MONTH)), '%Y-%m')
WHERE s.estado = 'VIGENTE'
GROUP BY s.id_centro_costo, cc.nombre
ORDER BY ingresos_aceptados DESC;

-- ============================================================================
-- 6. REPORTES HISTÓRICOS (TENDENCIAS)
-- ============================================================================

-- Evolución de mandatos activos (trimestral)
SELECT
    DATE_TRUNC(s.fecha_activacion, QUARTER) as trimestre,
    COUNT(*) as nuevos_mandatos,
    SUM(CASE WHEN s.estado = 'VIGENTE' THEN 1 ELSE 0 END) as aun_vigentes,
    SUM(CASE WHEN s.estado = 'ELIMINADA' THEN 1 ELSE 0 END) as cancelados
FROM suscripciones s
GROUP BY DATE_TRUNC(s.fecha_activacion, QUARTER)
ORDER BY trimestre DESC;

-- Tasa de retención (por cohorte de activación)
SELECT
    DATE_TRUNC(s.fecha_activacion, MONTH) as cohorte,
    COUNT(*) as mandatos_al_inicio,
    SUM(CASE WHEN s.estado = 'VIGENTE' THEN 1 ELSE 0 END) as aun_vigentes,
    ROUND(100.0 * SUM(CASE WHEN s.estado = 'VIGENTE' THEN 1 ELSE 0 END) / COUNT(*), 2) as tasa_retencion_actual
FROM suscripciones s
WHERE s.fecha_activacion >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
GROUP BY DATE_TRUNC(s.fecha_activacion, MONTH)
ORDER BY cohorte DESC;

-- Ingresos por mes (últimos 12 meses)
SELECT
    tm.periodo,
    COUNT(DISTINCT tm.id_suscripcion) as mandatos,
    COUNT(DISTINCT tm.id_transaccion) as cargos,
    SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN tm.monto ELSE 0 END) as ingresos_aceptados,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN tm.monto ELSE 0 END) as ingresos_rechazados,
    (SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN tm.monto ELSE 0 END) -
     LAG(SUM(CASE WHEN tm.estado_consolidado = 'ACEPTADA' THEN tm.monto ELSE 0 END))
     OVER (ORDER BY tm.periodo)) as variacion_mes_anterior
FROM transacciones_mensuales tm
WHERE tm.periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 12 MONTH), '%Y-%m')
GROUP BY tm.periodo
ORDER BY tm.periodo DESC;

-- ============================================================================
-- 7. QUERIES PARA ML (REINTENTOS Y PREDICCIÓN)
-- ============================================================================

-- Dataset para entrenar modelo de predicción de rechazos
SELECT
    s.numero_ficha,
    c.rut,
    s.tipo_mandato,
    b.nombre as banco,
    s.tipo_cuenta,
    (YEAR(NOW()) - YEAR(c.fecha_nacimiento)) as edad_aprox,
    COUNT(DISTINCT tm.id_transaccion) as cargos_totales,
    SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) as rechazos_pasados,
    ROUND(100.0 * SUM(CASE WHEN tm.estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) / COUNT(*), 2) as tasa_rechazo_historica,
    (SELECT COUNT(*) FROM transacciones_detalles td
     JOIN transacciones_mensuales tm2 ON td.id_transaccion = tm2.id_transaccion
     WHERE tm2.id_suscripcion = s.id_suscripcion
     AND td.razon_rechazo LIKE '%vencid%') as rechazos_tarjeta_vencida,
    (SELECT MAX(fecha_procesamiento) FROM transacciones_detalles td
     JOIN transacciones_mensuales tm2 ON td.id_transaccion = tm2.id_transaccion
     WHERE tm2.id_suscripcion = s.id_suscripcion
     AND td.estado_detalle = 'RECHAZADA') as ultimo_rechazo,
    -- Target: ¿Se rechazará el siguiente cargo?
    (SELECT CASE
             WHEN COUNT(*) = 0 THEN 0  -- No hay rechazos recientes
             WHEN ROUND(100.0 * SUM(CASE WHEN estado_consolidado = 'RECHAZADA' THEN 1 ELSE 0 END) / COUNT(*), 2) > 50 THEN 1  -- Alto riesgo
             ELSE 0.5  -- Riesgo moderado
        END
     FROM transacciones_mensuales
     WHERE id_suscripcion = s.id_suscripcion
     AND periodo >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 3 MONTH), '%Y-%m')
    ) as probabilidad_rechazo
FROM suscripciones s
JOIN clientes c ON s.id_cliente = c.id_cliente
JOIN bancos b ON s.id_banco = b.id_banco
LEFT JOIN transacciones_mensuales tm ON s.id_suscripcion = tm.id_suscripcion
WHERE s.estado = 'VIGENTE'
GROUP BY s.id_suscripcion
ORDER BY probabilidad_rechazo DESC;

-- ============================================================================
-- 8. REPORTES EJECUTIVOS
-- ============================================================================

-- Dashboard Executive Summary (1 mes actual)
SELECT
    'MANDATOS' as metrica,
    (SELECT COUNT(*) FROM suscripciones WHERE estado = 'VIGENTE') as valor
UNION ALL SELECT 'MANDATOS NUEVOS (MES)',
    COUNT(*) FROM suscripciones
    WHERE estado = 'VIGENTE'
    AND DATE_FORMAT(created_at, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')
UNION ALL SELECT 'CARGOS TOTALES (MES)',
    COUNT(*) FROM transacciones_mensuales
    WHERE periodo = DATE_FORMAT(NOW(), '%Y-%m')
UNION ALL SELECT 'CARGOS ACEPTADOS (MES)',
    COUNT(*) FROM transacciones_mensuales
    WHERE periodo = DATE_FORMAT(NOW(), '%Y-%m')
    AND estado_consolidado = 'ACEPTADA'
UNION ALL SELECT 'CARGOS RECHAZADOS (MES)',
    COUNT(*) FROM transacciones_mensuales
    WHERE periodo = DATE_FORMAT(NOW(), '%Y-%m')
    AND estado_consolidado = 'RECHAZADA'
UNION ALL SELECT 'INGRESOS (MES)',
    SUM(monto) FROM transacciones_mensuales
    WHERE periodo = DATE_FORMAT(NOW(), '%Y-%m')
    AND estado_consolidado = 'ACEPTADA';

/*
 * NOTAS:
 *
 * - Reemplazar NOW() con CURRENT_DATE si usas fechas sin hora
 * - Algunos motores SQL (MYSQL vs POSTGRESQL) tienen diferentes funciones de fecha
 * - DATE_TRUNC es PostgreSQL; usar DATE_FORMAT o similar en MySQL
 * - Crear vistas para queries frecuentes
 * - Crear índices en: (id_suscripcion, periodo), (estado_consolidado), (fecha_procesamiento)
 */
