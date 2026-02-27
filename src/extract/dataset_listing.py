"""Parse the master dataset listing table from Lotsearch PDF reports."""

from __future__ import annotations

import re

from pydantic import BaseModel

from src.ingest.pdf_extractor import PDFContent

# Expected column headers (normalised to single-line lowercase) for validation
_EXPECTED_HEADER_COLS = {
    "dataset name",
    "custodian",
    "supply",
    "currency",
    "update",
    "dataset",
    "no.",
}


class DatasetListingEntry(BaseModel):
    """A single row from the dataset listing table."""

    dataset_name: str
    custodian: str
    supply_date: str | None = None
    currency_date: str | None = None
    update_frequency: str | None = None
    buffer_m: int | None = None
    count_onsite: int | None = None
    count_within_100m: int | None = None
    count_within_buffer: int | None = None
    has_hits: bool = False


def _is_header_row(row: list[str]) -> bool:
    """Check whether a row is the column header row."""
    if not row or len(row) < 6:
        return False
    # Flatten multiline header cells and check for known keywords
    first_cell = (row[0] or "").replace("\n", " ").strip().lower()
    return first_cell == "dataset name"


def _clean_cell(cell: str | None) -> str:
    """Clean a cell value: collapse internal newlines, strip whitespace."""
    if cell is None:
        return ""
    return " ".join(cell.split())


def _parse_dash_or_none(value: str) -> str | None:
    """Return None for dash/empty values, otherwise the cleaned string."""
    cleaned = value.strip()
    if cleaned in ("-", "", "–", "—"):
        return None
    return cleaned


def _parse_int_or_none(value: str) -> int | None:
    """Parse a count value: '-' -> None, '0' -> 0, '23' -> 23."""
    cleaned = value.strip()
    if cleaned in ("-", "", "–", "—"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_buffer(value: str) -> int | None:
    """Parse buffer distance like '1000m' -> 1000, '-' -> None."""
    cleaned = value.strip()
    if cleaned in ("-", "", "–", "—"):
        return None
    match = re.match(r"(\d+)\s*m?", cleaned)
    if match:
        return int(match.group(1))
    return None


def _parse_row(row: list[str]) -> DatasetListingEntry:
    """Parse a single data row into a DatasetListingEntry."""
    # Pad row to 9 columns if short
    padded = row + [""] * max(0, 9 - len(row))

    dataset_name = _clean_cell(padded[0])
    custodian = _clean_cell(padded[1])
    supply_date = _parse_dash_or_none(_clean_cell(padded[2]))
    currency_date = _parse_dash_or_none(_clean_cell(padded[3]))
    update_frequency = _parse_dash_or_none(_clean_cell(padded[4]))
    buffer_m = _parse_buffer(_clean_cell(padded[5]))
    count_onsite = _parse_int_or_none(_clean_cell(padded[6]))
    count_100m = _parse_int_or_none(_clean_cell(padded[7]))
    count_buffer = _parse_int_or_none(_clean_cell(padded[8]))

    # has_hits: True if any numeric count > 0
    has_hits = any(
        c is not None and c > 0
        for c in (count_onsite, count_100m, count_buffer)
    )

    return DatasetListingEntry(
        dataset_name=dataset_name,
        custodian=custodian,
        supply_date=supply_date,
        currency_date=currency_date,
        update_frequency=update_frequency,
        buffer_m=buffer_m,
        count_onsite=count_onsite,
        count_within_100m=count_100m,
        count_within_buffer=count_buffer,
        has_hits=has_hits,
    )


def parse_dataset_listing(pdf_content: PDFContent) -> list[DatasetListingEntry]:
    """Parse the dataset listing table from a Lotsearch PDF.

    The table appears on pages 2-4 (sometimes fewer) and has a consistent
    9-column format. Each continuation page repeats the header row.

    Args:
        pdf_content: Pre-extracted PDFContent from pdf_extractor.

    Returns:
        List of DatasetListingEntry, one per dataset row.

    Raises:
        ValueError: If no dataset listing table is found.
    """
    entries: list[DatasetListingEntry] = []
    found_table = False

    # Scan pages 1-5 (0-indexed: 0-4) for the dataset listing tables
    for page in pdf_content.pages[:6]:
        for table in page.tables:
            if not table or len(table) < 2:
                continue

            # Check if this table has the dataset listing header
            if not _is_header_row(table[0]):
                continue

            found_table = True

            # Parse data rows (skip the header)
            for row in table[1:]:
                if not row or len(row) < 2:
                    continue
                # Skip rows where the first cell is empty (artifact rows)
                first_cell = _clean_cell(row[0])
                if not first_cell:
                    continue
                entries.append(_parse_row(row))

    if not found_table:
        raise ValueError("No dataset listing table found in the first 6 pages")

    return entries
