-- Comparacion MRR/ARPU: formula ACTUAL vs criterio nuevo de tasks.md (SOLO SELECT, sin escrituras).
-- Uso: psql "$DATABASE_URL" -f scripts/maintenance/compare_mrr_payku_tch.sql
-- Los montos se guardan como texto; se castean solo si son numericos.

-- ===== PAYKU: MRR actual (suma subscription.amount de activas, tabla centralizada) =====
SELECT 'payku_actual' AS metodo,
       COUNT(*) AS suscripciones_activas,
       COALESCE(SUM(CASE WHEN amount ~ '^\d+(\.\d+)?$' THEN amount::numeric END), 0) AS mrr,
       COUNT(DISTINCT NULLIF(client_social_id, '')) AS clientes_activos
FROM subscriptions
WHERE source = 'payku' AND lower(status) = 'active';

-- ===== PAYKU: MRR nuevo (ultima transaccion success de cada suscripcion activa) =====
WITH activas AS (
    SELECT external_id, client_social_id
    FROM subscriptions
    WHERE source = 'payku' AND lower(status) = 'active'
),
ultima_success AS (
    SELECT DISTINCT ON (t.subscription_id)
           t.subscription_id,
           CASE WHEN t.amount ~ '^\d+(\.\d+)?$' THEN t.amount::numeric END AS monto
    FROM p_transactions t
    WHERE lower(t.status) = 'success' AND t.subscription_id IS NOT NULL
    ORDER BY t.subscription_id, t.created_at_api DESC
)
SELECT 'payku_nuevo' AS metodo,
       COUNT(a.external_id)                        AS suscripciones_activas,
       COUNT(u.subscription_id)                    AS activas_con_success,
       COALESCE(SUM(u.monto), 0)                   AS mrr,
       COUNT(DISTINCT NULLIF(a.client_social_id, '')) FILTER (WHERE u.subscription_id IS NOT NULL) AS clientes_activos
FROM activas a
LEFT JOIN ultima_success u ON u.subscription_id = a.external_id;

-- ===== TCH: valor ACTUAL (TchSuscripcion VIGENTE) =====
SELECT 'tch_actual' AS metodo,
       COUNT(*) AS suscripciones_vigentes,
       COALESCE(SUM(CASE WHEN equivalente_pesos ~ '^\d+(\.\d+)?$' THEN equivalente_pesos::numeric END), 0) AS mrr,
       COUNT(DISTINCT cliente_rut) AS clientes_activos,
       ROUND(COALESCE(SUM(CASE WHEN equivalente_pesos ~ '^\d+(\.\d+)?$' THEN equivalente_pesos::numeric END), 0)
             / NULLIF(COUNT(DISTINCT cliente_rut), 0), 0) AS arpu
FROM tch_suscripciones
WHERE estado = 'VIGENTE';

-- ===== TCH: criterio nuevo (tch_recaudacion_mensual, ultimo periodo con aceptadas > 0) =====
SELECT 'tch_nuevo' AS metodo,
       periodo,
       aceptadas_cantidad AS activos,
       aceptadas_monto::numeric AS mrr,
       ROUND(aceptadas_monto::numeric / NULLIF(aceptadas_cantidad, 0), 0) AS arpu,
       rechazadas_cantidad,
       rechazadas_monto::numeric AS rechazadas_monto
FROM tch_recaudacion_mensual
WHERE aceptadas_cantidad > 0
ORDER BY periodo DESC
LIMIT 1;
