"""Import existing BDlocales into central channel tables without provider requests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.bdlocales_import import import_bdlocales
from app.services.channel_consolidation import consolidate_to_canonical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("all", "virtualpos", "toku", "payku"), default="all")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    sources = None if args.source == "all" else [args.source]
    db = SessionLocal()
    try:
        summary = import_bdlocales(db, sources, args.batch_size)
        consolidated = consolidate_to_canonical(db, sources or ["virtualpos", "toku", "payku"])
        for table, count in sorted(summary.counts.items()):
            print(f"{table}: {count}")
        print(f"canonical: {consolidated}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
