"""Sondea la API de Payku para entender la estructura de paginación de transacciones."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from app.integrations.payku.client import PaykuClient


async def main():
    async with PaykuClient() as client:
        for per_page in [50, 100]:
            print(f"\n=== Página 1, per_page={per_page} ===")
            r = await client.list_transactions(page=1, per_page=per_page, date_init="2025-01-01")
            print(f"Tipo: {type(r).__name__}")
            if isinstance(r, dict):
                print(f"Claves: {list(r.keys())}")
                for key, val in r.items():
                    if isinstance(val, list):
                        print(f"  '{key}' es lista con {len(val)} elementos")
                        if val:
                            print(f"    Primer elemento keys: {list(val[0].keys()) if isinstance(val[0], dict) else val[0]}")
                    elif not isinstance(val, (dict, list)):
                        print(f"  '{key}': {val}")
                    else:
                        print(f"  '{key}': {json.dumps(val)[:200]}")
            elif isinstance(r, list):
                print(f"Lista directa con {len(r)} elementos")
                if r:
                    print(f"  Primer elemento keys: {list(r[0].keys()) if isinstance(r[0], dict) else r[0]}")

        # Probar páginas más allá del total real para ver qué retorna
        for page_num in [100, 1000, 9999]:
            print(f"\n=== Página {page_num}, per_page=50, date_init=2026-01-01 ===")
            r2 = await client.list_transactions(page=page_num, per_page=50, date_init="2026-01-01")
            if isinstance(r2, dict):
                tx = r2.get("transaction") or []
                print(f"  Registros: {len(tx)}")
                if tx:
                    print(f"  Campos observados: {sorted(tx[0]) if isinstance(tx[0], dict) else []}")
            elif isinstance(r2, list):
                print(f"  Lista: {len(r2)}")


asyncio.run(main())
