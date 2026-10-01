import asyncio
from app.integrations.virtualpos.client import VirtualPOSClient


async def main() -> None:
    for plat in ["virtualpos1", "virtualpos2"]:
        async with VirtualPOSClient(plat) as c:
            r = await c.list_clients(page=1, limit=3)
            print(f"=== {plat} ===")
            if isinstance(r, dict):
                print(f"  keys: {list(r.keys())}")
                for k, v in r.items():
                    if isinstance(v, list):
                        first_keys = sorted(v[0]) if v and isinstance(v[0], dict) else []
                        print(f"  {k}: {len(v)} registros, campos={first_keys}")
                    else:
                        print(f"  {k}: {type(v).__name__}")
            elif isinstance(r, list):
                print(f"  lista de {len(r)} items")
                if r:
                    print(f"  [0] keys: {sorted(r[0]) if isinstance(r[0], dict) else []}")
            print()


asyncio.run(main())
