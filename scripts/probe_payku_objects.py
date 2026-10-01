"""Sondea todos los endpoints de Payku para mapear objetos, conteos y paginacion."""
import asyncio
import sys
sys.path.insert(0, ".")

from app.integrations.payku.client import PaykuClient


def first_list(response):
    """Retorna la primera lista encontrada en un dict de respuesta."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for v in response.values():
            if isinstance(v, list):
                return v
    return []


def pag_info(response):
    if not isinstance(response, dict):
        return "N/A"
    for key in ("meta", "pagination", "links"):
        if key in response and isinstance(response[key], dict):
            return f"{key}={response[key]}"
    for key in ("total", "last_page", "total_pages", "next_page", "next_cursor"):
        if key in response:
            return f"'{key}'={response[key]}"
    return "SIN metadata"


async def probe_paginated(fetch_fn, per_page=100, max_pages=8):
    """Recorre hasta max_pages para estimar total. Retorna (total_seen, note)."""
    total = 0
    for page in range(1, max_pages + 1):
        try:
            r = await fetch_fn(page, per_page)
        except Exception as e:
            return total, f"Error p{page}: {e}"
        records = first_list(r)
        total += len(records)
        if len(records) < per_page:
            return total, f"termina en p{page} ({len(records)} < {per_page})"
        if page == max_pages:
            return total, f"mas de {total} (limite {max_pages} pags alcanzado)"
    return total, "ok"


async def main():
    async with PaykuClient() as client:

        # ── Clientes ─────────────────────────────────────────────────────
        print("=== CLIENTES /api/suclient/customers ===")
        r = await client.list_clients(page=1, per_page=100)
        recs = first_list(r)
        print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
        print(f"Paginacion p1: {pag_info(r)}")
        print(f"Registros p1: {len(recs)}")
        if recs:
            print(f"Campos: {list(recs[0].keys())}")
        total, note = await probe_paginated(
            lambda p, pp: client.list_clients(page=p, per_page=pp))
        print(f"Total estimado: {total} ({note})")

        # ── Planes ───────────────────────────────────────────────────────
        print("\n=== PLANES /api/suplan/plans ===")
        r = await client.list_plans()
        recs = first_list(r)
        print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
        print(f"Total planes: {len(recs)}")
        if recs:
            print(f"Campos: {list(recs[0].keys())}")

        # ── Suscripciones ────────────────────────────────────────────────
        print("\n=== SUSCRIPCIONES /api/sususcription ===")
        r = await client.list_subscriptions(page=1, per_page=100)
        recs = first_list(r)
        print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
        print(f"Paginacion p1: {pag_info(r)}")
        print(f"Registros p1: {len(recs)}")
        if recs:
            print(f"Campos: {list(recs[0].keys())}")
            sub0 = recs[0]
            if isinstance(sub0.get("transactions"), list):
                print(f"  *** Tiene 'transactions' embebidas ({len(sub0['transactions'])} en sub[0])")
            if isinstance(sub0.get("client"), dict):
                print(f"  Cliente embebido: {list(sub0['client'].keys())}")
            if isinstance(sub0.get("plan"), dict):
                print(f"  Plan embebido: {list(sub0['plan'].keys())}")
        total, note = await probe_paginated(
            lambda p, pp: client.list_subscriptions(page=p, per_page=pp))
        print(f"Total estimado: {total} ({note})")

        # ── Suscripciones v3 ─────────────────────────────────────────────
        print("\n=== SUSCRIPCIONES v3 /api/sususcriptionv3 ===")
        try:
            r = await client.list_subscriptions_v3(page=1, per_page=100)
            recs = first_list(r)
            print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
            print(f"Registros p1: {len(recs)}")
            if recs:
                print(f"Campos: {list(recs[0].keys())}")
        except Exception as e:
            print(f"Error: {e}")

        # ── Transacciones sin filtro (pag 1) ─────────────────────────────
        print("\n=== TRANSACCIONES /api/transaction (p1, sin filtro) ===")
        r = await client.list_transactions(page=1, per_page=100)
        recs = first_list(r)
        print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
        print(f"Paginacion p1: {pag_info(r)}")
        print(f"Registros p1: {len(recs)}")
        if recs:
            print(f"Campos: {list(recs[0].keys())}")
            print(f"Fecha mas reciente: {recs[0].get('created_at')}")
            print(f"Fecha mas antigua (p1): {recs[-1].get('created_at')}")

        # ── Transacciones 2021 (posible ataque) ──────────────────────────
        print("\n=== TRANSACCIONES 2021 (date_init=2021-01-01 date_end=2021-12-31) ===")
        try:
            r = await client.list_transactions(page=1, per_page=100,
                                               date_init="2021-01-01", date_end="2021-12-31")
            recs21 = first_list(r)
            print(f"Registros p1 en 2021: {len(recs21)}")
            if recs21:
                statuses = {}
                for t in recs21:
                    s = t.get("status", "?")
                    statuses[s] = statuses.get(s, 0) + 1
                print(f"Distribucion status: {statuses}")
            total21, note21 = await probe_paginated(
                lambda p, pp: client.list_transactions(page=p, per_page=pp,
                    date_init="2021-01-01", date_end="2021-12-31"), max_pages=5)
            print(f"Total 2021 (estimado): {total21} ({note21})")
        except Exception as e:
            print(f"Error: {e}")

        # ── Transacciones 2022 ────────────────────────────────────────────
        print("\n=== TRANSACCIONES 2022 (date_init=2022-01-01 date_end=2022-12-31) ===")
        try:
            r = await client.list_transactions(page=1, per_page=100,
                                               date_init="2022-01-01", date_end="2022-12-31")
            recs22 = first_list(r)
            print(f"Registros p1 en 2022: {len(recs22)}")
            if recs22:
                statuses = {}
                for t in recs22:
                    s = t.get("status", "?")
                    statuses[s] = statuses.get(s, 0) + 1
                print(f"Distribucion status: {statuses}")
            total22, note22 = await probe_paginated(
                lambda p, pp: client.list_transactions(page=p, per_page=pp,
                    date_init="2022-01-01", date_end="2022-12-31"), max_pages=5)
            print(f"Total 2022 (estimado): {total22} ({note22})")
        except Exception as e:
            print(f"Error: {e}")

        # ── Transacciones 2026 ────────────────────────────────────────────
        print("\n=== TRANSACCIONES 2026 (date_init=2026-01-01) ===")
        total26, note26 = await probe_paginated(
            lambda p, pp: client.list_transactions(page=p, per_page=pp,
                date_init="2026-01-01"), max_pages=8)
        print(f"Total 2026 (estimado): {total26} ({note26})")

        # ── Wallet Movimientos ────────────────────────────────────────────
        print("\n=== WALLET /api/wallet/list ===")
        try:
            r = await client.list_wallet_movements(page=1, per_page=100)
            recs = first_list(r)
            print(f"Claves: {list(r.keys()) if isinstance(r, dict) else type(r)}")
            print(f"Registros p1: {len(recs)}")
            if recs:
                print(f"Campos: {list(recs[0].keys())}")
        except Exception as e:
            print(f"Error: {e}")

        print("\n=== RESUMEN DE PAGINACION PAYKU ===")
        print("Todos los endpoints: {\"status\": ..., \"<objeto>\": [...]}")
        print("SIN metadata de paginacion (no total_pages, no next_cursor)")
        print("Fin de pagina = len(records) < per_page")
        print("Riesgo: si total es multiplo exacto de per_page, hace 1 req extra con []")


asyncio.run(main())
