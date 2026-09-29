"""Investiga por qué hay más pagos que cargos en VirtualPOS.

Hipótesis principal: list_subscriptions() de la API no devuelve suscripciones
canceladas, por lo que sus cargos nunca se descargan, pero sus pagos PAT sí
aparecen en el endpoint global /v3/payments.
"""
import json
from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()

PAID   = "('pagado','aceptado','accepted','paid','aprobado','aprobada','cobrado','cobrada','aceptada')"
VP     = "('virtualpos1','virtualpos2')"
ACTIVE = "('activa','activo','active','vigente')"
CANCEL = "('cancelada','cancelado','cancelled','canceled','inactiva','inactivo','inactive','baja','dado de baja')"

try:
    # ── 1. Distribución de estados de suscripciones ──────────────────────────
    r = db.execute(text(f"""
        SELECT source, lower(status) as st, COUNT(*) as qty
        FROM subscriptions
        WHERE source IN {VP}
        GROUP BY source, lower(status)
        ORDER BY source, qty DESC
    """))
    print("Estado de suscripciones por fuente:")
    for row in r:
        print(f"  {row[0]:15s} {str(row[1] or 'NULL'):30s} {row[2]:>8,}")

    # ── 2. ¿Cuántas suscripciones tienen canceled_at? ──────────────────────
    r = db.execute(text(f"""
        SELECT source,
               COUNT(*) FILTER (WHERE canceled_at IS NOT NULL) as con_cancelacion,
               COUNT(*) FILTER (WHERE canceled_at IS NULL)     as sin_cancelacion,
               COUNT(*) as total
        FROM subscriptions WHERE source IN {VP}
        GROUP BY source
    """))
    print("\nSuscripciones con/sin canceled_at:")
    for row in r:
        print(f"  {row[0]:15s} con_cancelacion={row[1]:>6,}  sin={row[2]:>6,}  total={row[3]:>6,}")

    # ── 3. Cargos por estado de suscripción ─────────────────────────────────
    r = db.execute(text(f"""
        SELECT lower(s.status) as sub_status,
               COUNT(DISTINCT c.id) as num_charges,
               COUNT(DISTINCT c.id) FILTER (WHERE lower(c.status) IN {PAID}) as paid_charges
        FROM subscriptions s
        LEFT JOIN charges c ON c.subscription_external_id = s.external_id AND c.source = s.source
        WHERE s.source IN {VP}
        GROUP BY lower(s.status)
        ORDER BY num_charges DESC
        LIMIT 15
    """))
    print("\nCargos por estado de suscripción:")
    print(f"  {'sub_status':30s} {'total_cargos':>14} {'cargos_pagados':>16}")
    for row in r:
        print(f"  {str(row[0] or 'NULL'):30s} {row[1]:>14,} {row[2]:>16,}")

    # ── 4. ¿Los 5618 pagos autónomos corresponden a suscripciones canceladas?
    #       Buscamos si el RUT del pago existe en suscripciones pero con estado cancelado
    r = db.execute(text(f"""
        SELECT COUNT(DISTINCT p.external_id) as autonomous_payments_with_rut_in_cancelled_sub
        FROM payments p
        WHERE p.source IN {VP}
          AND lower(p.status) IN {PAID}
          AND NOT EXISTS (
              SELECT 1 FROM charges c
              WHERE c.source = p.source
                AND c.raw_payload->'payment'->'order'->>'uuid' = p.external_id
          )
          AND EXISTS (
              SELECT 1 FROM subscriptions s
              WHERE s.source = p.source
                AND s.client_social_id = p.raw_payload->'client'->>'social_id'
                AND lower(s.status) NOT IN ('activa','activo','active','vigente')
          )
    """))
    print(f"\nPagos autónomos cuyo RUT aparece en una suscripción NO activa: {r.scalar():,}")

    r = db.execute(text(f"""
        SELECT COUNT(DISTINCT p.external_id)
        FROM payments p
        WHERE p.source IN {VP}
          AND lower(p.status) IN {PAID}
          AND NOT EXISTS (
              SELECT 1 FROM charges c
              WHERE c.source = p.source
                AND c.raw_payload->'payment'->'order'->>'uuid' = p.external_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM subscriptions s
              WHERE s.source = p.source
                AND s.client_social_id = p.raw_payload->'client'->>'social_id'
          )
    """))
    print(f"Pagos autónomos cuyo RUT NO aparece en ninguna suscripción:     {r.scalar():,}")

    # ── 5. ¿Cuántos cargos existen para suscripciones canceladas vs activas? ─
    r = db.execute(text(f"""
        SELECT
            CASE WHEN lower(s.status) IN ('activa','activo','active','vigente')
                 THEN 'ACTIVA' ELSE 'NO ACTIVA' END as tipo,
            COUNT(DISTINCT s.external_id) as subs,
            COUNT(c.id) as total_charges,
            COUNT(c.id) FILTER (WHERE lower(c.status) IN {PAID}) as paid_charges
        FROM subscriptions s
        LEFT JOIN charges c ON c.subscription_external_id = s.external_id AND c.source = s.source
        WHERE s.source IN {VP}
        GROUP BY tipo
    """))
    print("\nCargos según si la suscripción está activa o no:")
    for row in r:
        print(f"  {row[0]:10s}: subs={row[1]:,}  total_charges={row[2]:,}  paid_charges={row[3]:,}")

    # ── 6. Suscripciones sin NINGÚN cargo en la DB ───────────────────────────
    r = db.execute(text(f"""
        SELECT source,
               CASE WHEN lower(status) IN ('activa','activo','active','vigente')
                    THEN 'ACTIVA' ELSE 'NO ACTIVA' END as tipo,
               COUNT(*) as qty
        FROM subscriptions s
        WHERE s.source IN {VP}
          AND NOT EXISTS (
              SELECT 1 FROM charges c
              WHERE c.subscription_external_id = s.external_id AND c.source = s.source
          )
        GROUP BY source, tipo
        ORDER BY source, qty DESC
    """))
    print("\nSuscripciones sin ningún cargo en la DB:")
    for row in r:
        print(f"  {row[0]:15s} {row[1]:10s}: {row[2]:,}")

    # ── 7. Pagos autónomos por mes (¿hay un patrón temporal?) ───────────────
    r = db.execute(text(f"""
        SELECT
            date_trunc('month', p.payment_date) as mes,
            COUNT(*) as qty,
            SUM(p.amount::numeric) as total
        FROM payments p
        WHERE p.source IN {VP}
          AND lower(p.status) IN {PAID}
          AND NOT EXISTS (
              SELECT 1 FROM charges c
              WHERE c.source = p.source
                AND c.raw_payload->'payment'->'order'->>'uuid' = p.external_id
          )
        GROUP BY mes
        ORDER BY mes DESC
        LIMIT 18
    """))
    print("\nPagos autónomos por mes (más recientes primero):")
    for row in r:
        print(f"  {str(row[0])[:7]}  count={int(row[1]):>5,}  monto=${int(row[2] or 0):>12,}")

    # ── 8. Resumen ejecutivo ─────────────────────────────────────────────────
    print("\n=== RESUMEN EJECUTIVO ===")
    r1 = db.execute(text(f"SELECT COUNT(*) FROM charges WHERE source IN {VP} AND lower(status) IN {PAID}"))
    r2 = db.execute(text(f"SELECT COUNT(*) FROM payments WHERE source IN {VP} AND lower(status) IN {PAID}"))
    charged = r1.scalar()
    paid = r2.scalar()
    print(f"Cargos pagados:           {charged:>8,}")
    print(f"Transacciones pagadas:    {paid:>8,}")
    print(f"Diferencia:               {paid - charged:>8,}")

finally:
    db.close()
