import sys
from collections.abc import Callable
from typing import TextIO

ProgressCallback = Callable[[str, int, int, int | None, int | None], None]


def pagination_totals(response: object) -> tuple[int | None, int | None]:
    """Return record and page totals exposed by a provider response."""
    if not isinstance(response, dict):
        return None, None
    for key in ("pagination", "meta"):
        metadata = response.get(key)
        if not isinstance(metadata, dict):
            continue
        total_records = metadata.get("total", metadata.get("total_records"))
        total_pages = metadata.get("total_pages", metadata.get("last_page", metadata.get("pages")))
        return (
            total_records if isinstance(total_records, int) and total_records >= 0 else None,
            total_pages if isinstance(total_pages, int) and total_pages > 0 else None,
        )
    return None, None


class TerminalProgress:
    def __init__(self, provider: str, stream: TextIO | None = None) -> None:
        self.provider = provider
        self.stream = stream or sys.stdout
        self._rendered = False

    def update(
        self,
        resource: str,
        page: int,
        records: int,
        total_records: int | None,
        total_pages: int | None,
    ) -> None:
        if total_records is not None:
            percent = 100 if total_records == 0 else min(100, records * 100 // total_records)
            detail = f"{percent}% ({records}/{total_records} records)"
        elif total_pages is not None:
            percent = min(100, page * 100 // total_pages)
            detail = f"{percent}% (page {page}/{total_pages}, {records} records)"
        else:
            detail = f"page {page}, {records} records"
        print(f"\r{self.provider} {resource}: {detail}", end="", file=self.stream, flush=True)
        self._rendered = True

    def finish(self) -> None:
        if self._rendered:
            print(file=self.stream, flush=True)
