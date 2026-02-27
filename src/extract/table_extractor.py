"""Generic extraction for individual dataset sections from Lotsearch reports."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.extract.dataset_listing import DatasetListingEntry
from src.ingest.section_splitter import SectionContent

# Pattern for detecting "No records in buffer" across various cell layouts
_NO_RECORDS_RE = re.compile(r"[Nn]o\s+records\s+in\s*\n?\s*buffer", re.IGNORECASE)


class ExtractedSection(BaseModel):
    """Structured extraction from a single dataset section."""

    dataset_name: str
    heading: str
    raw_text: str
    tables: list[dict] = Field(default_factory=list)
    table_headers: list[list[str]] = Field(default_factory=list)
    hit_counts: dict = Field(default_factory=dict)
    custodian: str = ""
    has_no_records: bool = False


def _clean_header(header: str | None) -> str:
    """Normalise a table header cell: collapse whitespace, strip."""
    if header is None:
        return ""
    return " ".join(header.split())


def _table_to_dicts(table: list[list[str]]) -> tuple[list[str], list[dict], bool]:
    """Convert a list-of-lists table to list-of-dicts using the first row as keys.

    Returns:
        (headers, rows_as_dicts, has_no_records)
    """
    if not table or len(table) < 1:
        return [], [], False

    # First row is headers
    headers = [_clean_header(h) for h in table[0]]

    rows: list[dict] = []
    has_no_records = False

    for row in table[1:]:
        # Check for "No records in buffer" rows
        row_text = " ".join(cell or "" for cell in row)
        if _NO_RECORDS_RE.search(row_text):
            has_no_records = True
            # Still include the row as a dict so the data is preserved
            row_dict = _row_to_dict(headers, row)
            row_dict["_no_records"] = True
            rows.append(row_dict)
            continue

        row_dict = _row_to_dict(headers, row)
        rows.append(row_dict)

    return headers, rows, has_no_records


def _row_to_dict(headers: list[str], row: list[str]) -> dict:
    """Map a row's cells to the corresponding headers."""
    result: dict = {}
    for i, header in enumerate(headers):
        if i < len(row):
            result[header] = row[i] if row[i] is not None else ""
        else:
            result[header] = ""
    # Include any extra cells beyond the header count
    for i in range(len(headers), len(row)):
        result[f"_col_{i}"] = row[i] if row[i] is not None else ""
    return result


def _is_map_legend_table(table: list[list[str]]) -> bool:
    """Detect tables that are really map legend artifacts (not data tables).

    Map pages produce tables with garbled text from legend boxes and compass
    roses — these typically have cells with just numbers or single characters,
    and the first row doesn't look like data column headers.
    """
    if not table or len(table) < 1:
        return True

    first_row = table[0]
    # Map legend tables often have None/empty cells or very short cells
    non_empty = [c for c in first_row if c and len(c.strip()) > 2]
    if len(non_empty) <= 1:
        return True

    # Check for "Legend" text in any cell (legend boxes extracted as tables)
    for row in table:
        for cell in row:
            if cell and "Legend" in cell and "Site Boundary" in cell:
                return True

    return False


def extract_section(
    section: SectionContent,
    listing_entry: DatasetListingEntry | None = None,
) -> ExtractedSection:
    """Extract structured data from a dataset section.

    Takes raw section content and optionally a matching dataset listing entry,
    and produces a structured extraction with tables converted to list-of-dicts.

    Args:
        section: SectionContent from the section splitter.
        listing_entry: Optional matching DatasetListingEntry for hit counts and metadata.

    Returns:
        ExtractedSection with structured tables and metadata.
    """
    dataset_name = listing_entry.dataset_name if listing_entry else section.heading
    custodian = listing_entry.custodian if listing_entry else ""

    hit_counts = {}
    if listing_entry:
        hit_counts = {
            "onsite": listing_entry.count_onsite,
            "within_100m": listing_entry.count_within_100m,
            "within_buffer": listing_entry.count_within_buffer,
        }

    all_tables: list[dict] = []
    all_headers: list[list[str]] = []
    any_no_records = False

    for table in section.tables:
        # Skip map legend artifact tables
        if _is_map_legend_table(table):
            continue

        headers, row_dicts, has_no_records = _table_to_dicts(table)
        if has_no_records:
            any_no_records = True

        if headers:
            all_headers.append(headers)
        all_tables.extend(row_dicts)

    return ExtractedSection(
        dataset_name=dataset_name,
        heading=section.heading,
        raw_text=section.text,
        tables=all_tables,
        table_headers=all_headers,
        hit_counts=hit_counts,
        custodian=custodian,
        has_no_records=any_no_records,
    )
