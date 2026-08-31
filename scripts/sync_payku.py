import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.payku_sync import sync_payku


async def main() -> None:
    with SessionLocal() as db:
        run = await sync_payku(db)
        print(f"Payku sync completed: {run.id} ({run.records_processed} records)")


if __name__ == "__main__":
    asyncio.run(main())
