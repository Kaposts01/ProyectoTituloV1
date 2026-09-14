import asyncio
import sys
from pathlib import Path

# Direct execution places scripts/ first on sys.path; add the project root for app imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.channel_consolidation import consolidate_to_canonical
from app.services.virtualpos_sync import sync_virtualpos


async def main() -> None:
    with SessionLocal() as db:
        for platform in ("virtualpos1", "virtualpos2"):
            run = await sync_virtualpos(db, platform)
            print(f"VirtualPOS {platform} sync completed: {run.id} ({run.records_processed} records)")
        print(f"VirtualPOS consolidation completed: {consolidate_to_canonical(db, ['virtualpos'])} records")


if __name__ == "__main__":
    asyncio.run(main())
