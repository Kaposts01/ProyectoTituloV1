"""Export paid VirtualPOS payments lacking a locally matched Charge.

The report uses the provider's authoritative reverse relationship when present:
Charge.payment.order.uuid == Payment.order.uuid. Remaining rows are enriched
with subscription evidence by platform and client RUT, but ambiguous rows are
never treated as an automatic financial match.
"""

import argparse
import csv
import sys
from pathlib import Path

# Direct execution places scripts/ first on sys.path; add the project root for app imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.session import SessionLocal

DEFAULT_OUTPUT = Path("reports/virtualpos_unlinked_payments.csv")
DEFAULT_SUBSCRIPTIONS_OUTPUT = Path("reports/virtualpos_subscriptions_without_charge_history.csv")


QUERY = """
    WITH unlinked_payments AS (
        SELECT
            p.source AS platform,
            p.external_id AS payment_uuid,
            p.payment_date,
            p.amount AS payment_amount,
            p.currency AS payment_currency,
            p.raw_payload->'order'->>'payment_method' AS payment_method,
            p.raw_payload->'order'->>'payment_type_code' AS payment_type_code,
            p.raw_payload->'order'->>'merchant_internal_code' AS merchant_internal_code,
            p.raw_payload->'order'->>'merchant_internal_channel' AS merchant_internal_channel,
            p.raw_payload->'client'->>'social_id' AS client_social_id
        FROM payments p
        WHERE p.source IN ('virtualpos1', 'virtualpos2')
          AND lower(p.status) = 'pagado'
          AND NOT EXISTS (
              SELECT 1
              FROM charges c
              WHERE c.source = p.source
                AND c.raw_payload->'payment'->'order'->>'uuid' = p.external_id
          )
    ),
    subscription_evidence AS (
        SELECT
            u.platform,
            u.payment_uuid,
            count(s.external_id) AS candidate_subscription_count,
            string_agg(s.external_id, '|' ORDER BY s.external_id) AS candidate_subscription_ids,
            string_agg(lower(coalesce(s.status, '')), '|' ORDER BY s.external_id) AS candidate_subscription_statuses,
            string_agg(coalesce(s.plan_external_id, ''), '|' ORDER BY s.external_id) AS candidate_plan_ids,
            string_agg(coalesce(s.suscription_date, ''), '|' ORDER BY s.external_id) AS candidate_subscription_dates,
            string_agg(coalesce(s.canceled_at, ''), '|' ORDER BY s.external_id) AS candidate_canceled_at_dates,
            count(s.external_id) FILTER (
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM charges c
                    WHERE c.source = s.source
                      AND c.subscription_external_id = s.external_id
                )
            ) AS candidates_without_local_charges
        FROM unlinked_payments u
        LEFT JOIN subscriptions s
          ON s.source = u.platform
         AND s.client_social_id = u.client_social_id
        GROUP BY u.platform, u.payment_uuid
    )
    SELECT
        u.*,
        e.candidate_subscription_count,
        e.candidate_subscription_ids,
        e.candidate_subscription_statuses,
        e.candidate_plan_ids,
        e.candidate_subscription_dates,
        e.candidate_canceled_at_dates,
        e.candidates_without_local_charges,
        CASE
            WHEN e.candidate_subscription_count = 0 THEN 'no_local_subscription'
            WHEN e.candidate_subscription_count > 1 THEN 'multiple_subscription_candidates'
            WHEN e.candidate_subscription_statuses = 'cancelada'
                 AND e.candidates_without_local_charges = 1
                 AND left(u.payment_date, 10) <= left(e.candidate_canceled_at_dates, 10)
                THEN 'cancelled_subscription_missing_local_charges_payment_before_or_on_cancel'
            WHEN e.candidate_subscription_statuses = 'cancelada'
                 AND left(u.payment_date, 10) > left(e.candidate_canceled_at_dates, 10)
                THEN 'payment_after_cancel_requires_provider_review'
            ELSE 'single_subscription_requires_review'
        END AS evidence_class,
        CASE
            WHEN e.candidate_subscription_count = 1
                 AND left(e.candidate_canceled_at_dates, 10) ~ '^\\d{4}-\\d{2}-\\d{2}$'
                 AND left(u.payment_date, 10) ~ '^\\d{4}-\\d{2}-\\d{2}$'
                THEN (left(u.payment_date, 10)::date - left(e.candidate_canceled_at_dates, 10)::date)
        END AS days_from_cancellation
    FROM unlinked_payments u
    JOIN subscription_evidence e
      ON e.platform = u.platform
     AND e.payment_uuid = u.payment_uuid
    ORDER BY u.platform, u.payment_date, u.payment_uuid
    """


SUBSCRIPTIONS_WITHOUT_CHARGES_QUERY = """
    SELECT
        s.source AS platform,
        s.external_id AS subscription_id,
        s.client_social_id,
        s.status AS subscription_status,
        s.plan_external_id AS plan_id,
        s.suscription_date AS subscription_date,
        s.canceled_at
    FROM subscriptions s
    WHERE s.source IN ('virtualpos1', 'virtualpos2')
      AND NOT EXISTS (
          SELECT 1
          FROM charges c
          WHERE c.source = s.source
            AND c.subscription_external_id = s.external_id
      )
    ORDER BY s.source, s.canceled_at, s.external_id
    """


def main() -> None:
    from sqlalchemy import text

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--subscriptions-output", type=Path, default=DEFAULT_SUBSCRIPTIONS_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.subscriptions_output.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        for output, query in (
            (args.output, QUERY),
            (args.subscriptions_output, SUBSCRIPTIONS_WITHOUT_CHARGES_QUERY),
        ):
            with output.open("w", newline="", encoding="utf-8-sig") as file:
                result = db.execute(text(query))
                writer = csv.DictWriter(file, fieldnames=list(result.keys()))
                writer.writeheader()
                writer.writerows(row._mapping for row in result)

    print(f"Exported {args.output}")
    print(f"Exported {args.subscriptions_output}")


if __name__ == "__main__":
    main()
