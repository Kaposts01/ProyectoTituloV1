import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from app.core.config import settings


async def probe_key(label: str, key: str) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.trytoku.com",
        timeout=15,
        headers={"Accept": "application/json", "x-api-key": key},
    ) as c:
        r = await c.get("/customers", params={"page_size": 10})
        if r.status_code != 200:
            print(f"{label}: HTTP {r.status_code}")
            return
        data = r.json()
        items = data.get("items", [])
        next_cur = bool(data.get("next_cursor"))
        print(f"{label}: {len(items)} clientes, next_cursor={next_cur}")
        if items and isinstance(items[0], dict):
            print(f"    campos observados: {sorted(items[0])}")

        # También suscripciones
        r2 = await c.get("/subscriptions", params={"page_size": 10})
        if r2.status_code == 200:
            d2 = r2.json()
            subs = d2.get("items", [])
            active = [s for s in subs if (s.get("recurring") or {}).get("status") == "ACTIVE"]
            print(f"    > {len(subs)} subs en primera pagina, {len(active)} ACTIVE")


async def main() -> None:
    print("=== TOKU_API_KEY ===")
    await probe_key("api_key", settings.toku_api_key)
    print()
    print("=== TOKU_ACCOUNT_KEY ===")
    await probe_key("account_key", settings.toku_account_key)


asyncio.run(main())
