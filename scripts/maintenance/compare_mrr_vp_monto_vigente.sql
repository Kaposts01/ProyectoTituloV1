-- Comparacion MRR VirtualPOS: monto de la suscripcion (actual) vs monto vigente = ultimo monto cobrado (SOLO SELECT, sin escrituras).
-- Uso: psql "$DATABASE_URL" -f scripts/maintenance/compare_mrr_vp_monto_vigente.sql
-- Lee las tablas centralizadas (subscriptions/charges/plans, source virtualpos1/virtualpos2): las mismas que alimentan el dashboard.
-- monto_vigente: amount del ultimo cargo 'pagado'/'procesando' con charge_date <= hoy (hay cargos programados hasta 2031);
-- desempate por charge_date desc, external_id desc; sin cargos validos -> amount de la suscripcion, luego del plan.
-- Los montos se guardan como texto; se castean solo si son numericos.

WITH ultimo_cargo AS (
    SELECT DISTINCT ON (c.source, c.subscription_external_id)
           c.source, c.subscription_external_id,
           c.amount::numeric AS monto
    FROM charges c
    WHERE c.source LIKE 'virtualpos%' AND c.subscription_external_id IS NOT NULL
      AND c.charge_date IS NOT NULL
      AND lower(trim(c.status)) IN ('pagado', 'procesando')
      AND substr(c.charge_date, 1, 10) <= to_char(current_date, 'YYYY-MM-DD')
      AND c.amount ~ '^\s*\d+(\.\d+)?\s*$'
    ORDER BY c.source, c.subscription_external_id, c.charge_date DESC, c.external_id DESC
),
activas AS (
    SELECT s.source, s.external_id, s.client_social_id,
           CASE WHEN s.amount ~ '^\s*\d+(\.\d+)?\s*$' THEN s.amount::numeric END AS monto_sub,
           CASE WHEN p.amount ~ '^\s*\d+(\.\d+)?\s*$' THEN p.amount::numeric END AS monto_plan
    FROM subscriptions s
    LEFT JOIN plans p ON p.source = s.source AND p.external_id = s.plan_external_id
    WHERE upper(s.status) = 'ACTIVA' AND s.source LIKE 'virtualpos%'
)
SELECT a.source,
       COUNT(*)                                                         AS suscripciones_activas,
       COUNT(u.subscription_external_id)                                AS con_cargo_vigente,
       COALESCE(SUM(a.monto_sub), 0)                                    AS mrr_actual,
       COALESCE(SUM(COALESCE(u.monto, a.monto_sub, a.monto_plan)), 0)   AS mrr_vigente,
       COALESCE(SUM(COALESCE(u.monto, a.monto_sub, a.monto_plan)), 0)
         - COALESCE(SUM(a.monto_sub), 0)                                AS diferencia,
       COUNT(*) FILTER (WHERE u.monto IS NOT NULL AND u.monto IS DISTINCT FROM a.monto_sub) AS suscripciones_que_cambian
FROM activas a
LEFT JOIN ultimo_cargo u ON u.source = a.source AND u.subscription_external_id = a.external_id
GROUP BY ROLLUP (a.source)
ORDER BY a.source NULLS LAST;
