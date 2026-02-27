"""Extract text and tables from Lotsearch PDF reports using pdfplumber."""

from __future__ import annotations

from pathlib import Path

import pdfplumber
from pydantic import BaseModel, Field

# Keywords that indicate a map/diagram page rather than a data page
_MAP_KEYWORDS = {"legend", "scale:", "coordinate system", "meters", "metres"}


class PageContent(BaseModel):
    """Extracted content from a single PDF page."""

    page_number: int
    text: str = ""
    tables: list[list[list[str]]] = Field(default_factory=list)
    has_map: bool = False


class PDFContent(BaseModel):
    """Complete extracted content from a PDF."""

    pages: list[PageContent]
    full_text: str = ""
    metadata: dict = Field(default_factory=dict)


def _is_map_page(page: pdfplumber.page.Page, text: str) -> bool:
    """Detect whether a page is primarily a map/diagram.

    Heuristic: low text density relative to page area, or presence of
    map-specific keywords like Legend, Scale:, Coordinate System.
    """
    text_lower = text.lower()
    if any(kw in text_lower for kw in _MAP_KEYWORDS):
        return True

    # Low text density: few characters relative to page area
    page_area = page.width * page.height
    if page_area > 0:
        density = len(text) / page_area
        if density < 0.002 and len(text) < 800:
            return True

    return False


def _extract_tables(page: pdfplumber.page.Page) -> list[list[list[str]]]:
    """Extract tables from a page, trying line-based strategy first then text fallback."""
    tables = page.extract_tables(
        table_settings={
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
        }
    )
    if not tables:
        tables = page.extract_tables(
            table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
            }
        )
    # Normalise None cells to empty strings
    cleaned = []
    for table in tables:
        cleaned_table = []
        for row in table:
            cleaned_table.append([cell if cell is not None else "" for cell in row])
        cleaned.append(cleaned_table)
    return cleaned


def extract_pdf(path: str | Path) -> PDFContent:
    """Extract all text and tables from a Lotsearch PDF report.

    Args:
        path: Path to the PDF file.

    Returns:
        PDFContent with per-page data and concatenated full text.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    pages: list[PageContent] = []
    all_text_parts: list[str] = []

    with pdfplumber.open(path) as pdf:
        metadata = pdf.metadata or {}

        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = _extract_tables(page)
            has_map = _is_map_page(page, text)

            pages.append(
                PageContent(
                    page_number=i + 1,
                    text=text,
                    tables=tables,
                    has_map=has_map,
                )
            )
            all_text_parts.append(text)

    return PDFContent(
        pages=pages,
        full_text="\n\n".join(all_text_parts),
        metadata={k: v for k, v in metadata.items() if v is not None},
    )
