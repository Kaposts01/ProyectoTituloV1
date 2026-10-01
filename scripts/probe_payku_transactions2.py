"""Sondea transacciones Payku por anno con filtros de fecha."""
import asyncio
import sys
sys.path.insert(0, ".")

from app.integrations.payku.client import PaykuClient


def first_list(r):
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for v in r.values():
            if isinstance(v, list):
                return v
    return []


async def count_year(client, year, max_pages=6):
    total = 0
    date_i = f"{year}-01-01"
    date_e = f"{year}-12-31"
    for page in range(1, max_pages + 1):
        try:
            r = await client.list_transactions(page=page, per_page=100,
                                               date_init=date_i, date_end=date_e)
        except Exception as e:
            return total, f"error p{page}: {e}"
        recs = first_list(r)
        total += len(recs)
        if len(recs) < 100:
            return total, f"fin en p{page}"
        if page == max_pages:
            return total, f"mas de {total} (limite)"
    return total, "ok"


async def status_sample(client, year):
    r = await client.list_transactions(page=1, per_page=100,
                                       date_init=f"{year}-01-01",
                                       date_end=f"{year}-12-31")
    recs = first_list(r)
    if not recs:
        return {}, 0
    statuses = {}
    emails = set()
    for t in recs:
        s = t.get("status", "?")
        statuses[s] = statuses.get(s, 0) + 1
        e = t.get("email") or ""
        if e:
            emails.add(e)
    return statuses, len(emails)


async def main():
    async with PaykuClient() as client:
        for year in [2021, 2022, 2023, 2024, 2025, 2026]:
            print(f"\n--- {year} ---")
            try:
                total, note = await count_year(client, year)
                statuses, unique_emails = await status_sample(client, year)
                print(f"  Total estimado : {total} ({note})")
                print(f"  Status (p1)    : {statuses}")
                print(f"  Emails unicos  : {unique_emails}")
            except Exception as e:
                print(f"  Error: {e}")

        # Suscripciones con transacciones embebidas
        print("\n--- SUSCRIPCIONES con transactions embebidas (muestra 5) ---")
        r = await client.list_subscriptions(page=1, per_page=10)
        subs = first_list(r)
        embedded_counts = [len(sub.get("transactions") or []) for sub in subs[:5] if isinstance(sub, dict)]
        print(f"  Transacciones embebidas por muestra: {embedded_counts}")


asyncio.run(main())
