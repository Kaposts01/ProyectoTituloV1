-- SYNC-GAP-02: auditoria de SOLO LECTURA de cuotas TCH duplicadas.
-- dedupe_key incluye estado y monto, por lo que la misma cuota puede existir mas de una vez
-- (p. ej. RECHAZADA y luego ACEPTADA, o montos distintos). Este script solo hace SELECT.
-- Tabla: tch_transacciones (modelo TchTransaccion). Columnas: numero_ficha, periodo, numero_cuota.
-- No expone RUT ni datos de cuenta.

-- 1) Resumen: grupos (numero_ficha, periodo, numero_cuota) con mas de una fila.
SELECT
    numero_ficha,
    periodo,
    numero_cuota,
    COUNT(*)                              AS filas,
    COUNT(DISTINCT estado)                AS estados_distintos,
    COUNT(DISTINCT monto)                 AS montos_distintos,
    ARRAY_AGG(DISTINCT estado ORDER BY estado) AS estados,
    ARRAY_AGG(DISTINCT monto  ORDER BY monto)  AS montos,
    COUNT(DISTINCT archivo_origen)        AS archivos_distintos
FROM tch_transacciones
GROUP BY numero_ficha, periodo, numero_cuota
HAVING COUNT(*) > 1
ORDER BY filas DESC, numero_ficha, periodo, numero_cuota;

-- 2) Totales: cuantos grupos duplicados y cuantas filas sobrantes.
SELECT
    COUNT(*)                         AS grupos_duplicados,
    COALESCE(SUM(filas), 0)          AS filas_en_grupos,
    COALESCE(SUM(filas - 1), 0)      AS filas_sobrantes
FROM (
    SELECT COUNT(*) AS filas
    FROM tch_transacciones
    GROUP BY numero_ficha, periodo, numero_cuota
    HAVING COUNT(*) > 1
) d;

-- 3) Detalle de filas de los grupos duplicados.
SELECT t.id, t.numero_ficha, t.periodo, t.numero_cuota, t.estado, t.monto, t.archivo_origen, t.dedupe_key
FROM tch_transacciones t
JOIN (
    SELECT numero_ficha, periodo, numero_cuota
    FROM tch_transacciones
    GROUP BY numero_ficha, periodo, numero_cuota
    HAVING COUNT(*) > 1
) d
  ON  t.numero_ficha = d.numero_ficha
  AND t.periodo     IS NOT DISTINCT FROM d.periodo
  AND t.numero_cuota IS NOT DISTINCT FROM d.numero_cuota
ORDER BY t.numero_ficha, t.periodo, t.numero_cuota, t.estado, t.monto;
