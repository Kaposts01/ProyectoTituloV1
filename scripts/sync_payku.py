import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.channel_consolidation import consolidate_to_canonical
from app.services.payku_sync import sync_payku
from app.services.sync_progress import TerminalProgress


async def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize Payku read-only resources.")
    parser.add_argument(
        "--transaction-start-page",
        type=int,
        default=1,
        help="Resume the transaction collection at this one-based Payku page.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        progress = TerminalProgress("Payku")
        run = await sync_payku(db, progress.update, args.transaction_start_page)
        progress.finish()
        print(f"Payku sync completed: {run.id} ({run.records_processed} records)")
        print(f"Payku consolidation completed: {consolidate_to_canonical(db, ['payku'])} records")


if __name__ == "__main__":
    asyncio.run(main())
