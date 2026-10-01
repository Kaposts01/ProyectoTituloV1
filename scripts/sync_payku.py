import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.channel_consolidation import consolidate_to_centralized
from app.services.payku_sync import sync_payku
from app.services.sync_progress import TerminalProgress


async def main() -> None:
    with SessionLocal() as db:
        progress = TerminalProgress("Payku")
        run = await sync_payku(db, progress.update)
        progress.finish()
        print(f"Payku sync completed: {run.id} ({run.records_processed} records)")
        print(f"Payku consolidation completed: {consolidate_to_centralized(db, ['payku'])} records")


if __name__ == "__main__":
    asyncio.run(main())
