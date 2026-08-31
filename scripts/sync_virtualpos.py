import asyncio
import sys
from pathlib import Path

# Direct execution places scripts/ first on sys.path; add the project root for app imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.virtualpos_sync import sync_virtualpos


async def main() -> None:
    with SessionLocal() as db:
        run = await sync_virtualpos(db)
        print(f"VirtualPOS sync completed: {run.id} ({run.records_processed} records)")


if __name__ == "__main__":
    asyncio.run(main())
