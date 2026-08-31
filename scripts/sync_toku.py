import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.toku_sync import sync_toku


async def main() -> None:
    with SessionLocal() as db:
        run = await sync_toku(db)
        print(f"Toku sync completed: {run.id} ({run.records_processed} records)")


if __name__ == "__main__":
    asyncio.run(main())
