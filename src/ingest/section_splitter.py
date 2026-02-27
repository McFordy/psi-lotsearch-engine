"""Split a Lotsearch PDF into logical dataset sections by detecting headings."""

from __future__ import annotations

from pathlib import Path

import pdfplumber
from pydantic import BaseModel, Field

from src.ingest.pdf_extractor import PDFContent, PageContent

# Minimum font size to consider a character as a potential heading
_HEADING_MIN_SIZE = 14.0

# Font names that indicate bold heading text
_HEADING_BOLD_FONTS = {"Helvetica-Bold"}

# Blue colour ranges for Lotsearch headings (R ~0, G ~0.3, B ~0.5-0.7)
_HEADING_BLUE_RANGE = {
    "r": (0.0, 0.05),
    "g": (0.2, 0.45),
    "b": (0.4, 0.75),
}

# Known Lotsearch dataset section headings (normalised lowercase for matching)
_KNOWN_HEADINGS = {
    "dataset listing",
    "site diagram",
    "topographic data",
    "elevation contours",
    "epa contamination registers & other pollution notices",
    "epa contamination registers",
    "pfas investigation & management programs",
    "defence sites and unexploded ordnance",
    "epa records - preliminary risk screen assessments, audit reports & gqruz",
    "epa records",
    "epa activities - register of permissions",
    "epa activities",
    "epa records - legacy licensed activities & works approvals",
    "waste management facilities and landfills",
    "former gasworks & liquid fuel facilities",
    "former gasworks and liquid fuel facilities",
    "historical business directories",
    "business directory records",
    "dry cleaners, motor garages & service stations",
    "aerial imagery",
    "historical map",
    "features of interest",
    "watertable salinity",
    "hydrogeology & groundwater",
    "depth to watertable",
    "groundwater boreholes",
    "boreholes (earth resources database)",
    "historical mining activity - shafts",
    "historical mining activity",
    "geology",
    "geological structures",
    "atlas of australian soils",
    "soils",
    "victorian soil type mapping",
    "atlas of australian acid sulfate soils",
    "acid sulfate soils",
    "planning zones",
    "planning",
    "planning overlays",
    "heritage",
    "natural hazards",
    "ecological constraints",
    "ecological constraints - native vegetation",
    "ecological constraints - groundwater dependent ecosystems atlas",
    "inflow dependent ecosystems likelihood",
    "location confidences",
}


class SectionContent(BaseModel):
    """A single dataset section extracted from the PDF."""

    heading: str
    page_range: tuple[int, int]  # (start_page, end_page) inclusive, 1-indexed
    text: str = ""
    tables: list[list[list[str]]] = Field(default_factory=list)
    is_map_section: bool = False


def _is_heading_color(color: tuple | list | None) -> bool:
    """Check whether a character colour matches the Lotsearch blue heading colour."""
    if not color or len(color) < 3:
        return False
    r, g, b = color[0], color[1], color[2]
    return (
        _HEADING_BLUE_RANGE["r"][0] <= r <= _HEADING_BLUE_RANGE["r"][1]
        and _HEADING_BLUE_RANGE["g"][0] <= g <= _HEADING_BLUE_RANGE["g"][1]
        and _HEADING_BLUE_RANGE["b"][0] <= b <= _HEADING_BLUE_RANGE["b"][1]
    )


def _extract_heading_from_chars(page: pdfplumber.page.Page) -> str | None:
    """Try to extract a section heading from char-level font properties.

    Lotsearch headings are Helvetica-Bold, ~16pt, blue colour.
    """
    heading_chars: list[str] = []
    for c in page.chars:
        fontname = c.get("fontname", "")
        size = c.get("size", 0)
        color = c.get("non_stroking_color")

        # Check for bold heading font at large size with blue colour
        is_bold = any(bf in fontname for bf in _HEADING_BOLD_FONTS)
        is_large = size >= _HEADING_MIN_SIZE
        is_blue = _is_heading_color(color)

        if is_bold and is_large and is_blue:
            heading_chars.append(c["text"])
        elif heading_chars:
            # Stop collecting once we leave the heading font
            break

    if heading_chars:
        return "".join(heading_chars).strip()
    return None


def _match_known_heading(text: str) -> str | None:
    """Check if the first line of text matches a known dataset heading."""
    first_line = text.split("\n")[0].strip()
    first_lower = first_line.lower()

    # Exact match
    if first_lower in _KNOWN_HEADINGS:
        return first_line

    # Prefix match (e.g. "Aerial Imagery 2023" matches "aerial imagery")
    for known in _KNOWN_HEADINGS:
        if first_lower.startswith(known):
            return first_line

    return None


def split_sections(
    pdf_content: PDFContent,
    pdf_path: str | Path | None = None,
) -> list[SectionContent]:
    """Split PDF content into dataset sections.

    Uses two strategies to detect section boundaries:
    1. Char-level font properties (bold, large, blue) from pdfplumber.
    2. Known heading name matching from extracted text.

    Args:
        pdf_content: Pre-extracted PDFContent from pdf_extractor.
        pdf_path: Path to PDF for char-level analysis. If None, falls back to
                  text-only heading detection.

    Returns:
        List of SectionContent objects, one per detected section.
    """
    # Build heading map: page_number -> heading text
    heading_map: dict[int, str] = {}

    # Strategy 1: char-level detection (requires re-opening the PDF)
    if pdf_path is not None:
        pdf_path = Path(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                heading = _extract_heading_from_chars(page)
                if heading:
                    heading_map[page_num] = heading

    # Strategy 2: text-based known heading matching (fills gaps)
    for page in pdf_content.pages:
        if page.page_number not in heading_map and page.text.strip():
            heading = _match_known_heading(page.text)
            if heading:
                heading_map[page.page_number] = heading

    # Always mark page 1 as cover page if not already detected
    if 1 not in heading_map:
        heading_map[1] = "Cover Page"

    # Sort pages with headings
    heading_pages = sorted(heading_map.keys())

    # Build sections
    sections: list[SectionContent] = []
    page_lookup = {p.page_number: p for p in pdf_content.pages}
    total_pages = len(pdf_content.pages)

    for idx, start_page in enumerate(heading_pages):
        # Section ends at the page before the next heading, or at the last page
        if idx + 1 < len(heading_pages):
            end_page = heading_pages[idx + 1] - 1
        else:
            end_page = total_pages

        heading = heading_map[start_page]

        # Collect text and tables for all pages in this section
        section_texts: list[str] = []
        section_tables: list[list[list[str]]] = []
        is_map = False

        for pn in range(start_page, end_page + 1):
            page_data = page_lookup.get(pn)
            if page_data:
                section_texts.append(page_data.text)
                section_tables.extend(page_data.tables)
                if page_data.has_map:
                    is_map = True

        sections.append(
            SectionContent(
                heading=heading,
                page_range=(start_page, end_page),
                text="\n\n".join(section_texts),
                tables=section_tables,
                is_map_section=is_map,
            )
        )

    return sections
