from io import StringIO

from app.services.sync_progress import TerminalProgress, pagination_totals


def test_pagination_totals_reads_record_and_page_totals() -> None:
    assert pagination_totals({"pagination": {"total": 250, "pages": 3}}) == (250, 3)
    assert pagination_totals({"meta": {"total_pages": 2}}) == (None, 2)
    assert pagination_totals({"data": []}) == (None, None)


def test_terminal_progress_uses_percent_when_totals_are_available() -> None:
    stream = StringIO()
    progress = TerminalProgress("Toku", stream)

    progress.update("subscription", 1, 50, 200, 4)
    progress.update("transaction", 2, 125, None, 4)
    progress.update("plan", 1, 8, None, None)
    progress.finish()

    assert stream.getvalue() == (
        "\rToku subscription: 25% (50/200 records)"
        "\rToku transaction: 50% (page 2/4, 125 records)"
        "\rToku plan: page 1, 8 records\n"
    )
