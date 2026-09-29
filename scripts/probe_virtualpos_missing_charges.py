"""Read-only probe for missing VirtualPOS Charge histories in the local CSV report."""

import argparse
import asyncio
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Direct execution places scripts/ first on sys.path; add the project root for app imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.virtualpos.client import VirtualPOSClient

DEFAULT_INPUT = Path("reports/virtualpos_unlinked_payments.csv")


def records_from_response(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [record for record in response if isinstance(record, dict)]
    if isinstance(response, dict):
        for key in ("data", "results", "items", "charges"):
            if isinstance(response.get(key), list):
                return [record for record in response[key] if isinstance(record, dict)]
    return []


def payment_uuid_from_charge(charge: dict[str, Any]) -> str | None:
    payment = charge.get("payment")
    if not isinstance(payment, dict):
        return None
    order = payment.get("order")
    if not isinstance(order, dict) or order.get("uuid") is None:
        return None
    return str(order["uuid"])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Report not found: {args.input}. Run the export script first.")

    with args.input.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    samples: dict[str, list[tuple[str, set[str]]]] = {}
    for platform in ("virtualpos1", "virtualpos2"):
        candidates = [
            row
            for row in rows
            if row["platform"] == platform
            and row["evidence_class"]
            == "cancelled_subscription_missing_local_charges_payment_before_or_on_cancel"
        ]
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in candidates:
            grouped.setdefault(row["candidate_subscription_ids"], []).append(row)
        if grouped:
            sorted_samples = sorted(grouped.items(), key=lambda item: item[1][0]["payment_date"])
            selected_ids = {
                sorted_samples[0][0],
                sorted_samples[-1][0],
                max(grouped, key=lambda subscription_id: len(grouped[subscription_id])),
            }
            samples[platform] = [
                (subscription_id, {row["payment_uuid"] for row in grouped[subscription_id]})
                for subscription_id in selected_ids
            ]

    if not samples:
        raise SystemExit("No unambiguous cancelled-subscription samples found in the report.")

    for platform, platform_samples in samples.items():
        async with VirtualPOSClient(platform) as client:
            for sample_number, (subscription_id, expected_payment_uuids) in enumerate(platform_samples, start=1):
                response = await client.list_charges(subscription_id, page=1, limit=100)
                charges = records_from_response(response)
                charge_payment_uuids = {uuid for charge in charges if (uuid := payment_uuid_from_charge(charge))}
                status_counts = Counter(str(charge.get("status", "unknown")) for charge in charges)

                print(
                    {
                        "platform": platform,
                        "sample": sample_number,
                        "provider_response_keys": sorted(response) if isinstance(response, dict) else [],
                        "provider_error_code": response.get("error", {}).get("error_code")
                        if isinstance(response, dict) and isinstance(response.get("error"), dict)
                        else None,
                        "provider_charge_count": len(charges),
                        "provider_charge_statuses": dict(sorted(status_counts.items())),
                        "local_unlinked_payments_for_sample": len(expected_payment_uuids),
                        "uuid_matches": len(expected_payment_uuids & charge_payment_uuids),
                    }
                )


if __name__ == "__main__":
    asyncio.run(main())
