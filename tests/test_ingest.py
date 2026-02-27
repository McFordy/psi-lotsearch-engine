"""Tests for the ingest layer — runs against real PDFs in training_data/vic/."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingest.pdf_extractor import PDFContent, extract_pdf
from src.ingest.section_splitter import SectionContent, split_sections
from src.ingest.state_detector import StateIdentification, detect_state

TRAINING_DIR = Path(__file__).parent.parent / "training_data" / "vic"


def _find_vic_pdf() -> Path:
    """Find the first PDF in the VIC training directory."""
    pdfs = sorted(TRAINING_DIR.glob("*.pdf"))
    if not pdfs:
        pytest.skip("No VIC training PDFs found in training_data/vic/")
    return pdfs[0]


@pytest.fixture(scope="module")
def vic_pdf_path() -> Path:
    return _find_vic_pdf()


@pytest.fixture(scope="module")
def pdf_content(vic_pdf_path: Path) -> PDFContent:
    return extract_pdf(vic_pdf_path)


# ---------------------------------------------------------------------------
# PDF Extractor tests
# ---------------------------------------------------------------------------


class TestPDFExtractor:
    def test_returns_pdf_content(self, pdf_content: PDFContent):
        assert isinstance(pdf_content, PDFContent)

    def test_has_pages(self, pdf_content: PDFContent):
        assert len(pdf_content.pages) > 10, "Expected a multi-page Lotsearch report"

    def test_full_text_not_empty(self, pdf_content: PDFContent):
        assert len(pdf_content.full_text) > 1000

    def test_page_numbers_sequential(self, pdf_content: PDFContent):
        numbers = [p.page_number for p in pdf_content.pages]
        assert numbers == list(range(1, len(pdf_content.pages) + 1))

    def test_page1_has_text(self, pdf_content: PDFContent):
        page1 = pdf_content.pages[0]
        assert "Lotsearch" in page1.text or "LS" in page1.text

    def test_tables_extracted(self, pdf_content: PDFContent):
        """At least some pages should have tables (dataset listing, data tables)."""
        pages_with_tables = [p for p in pdf_content.pages if p.tables]
        assert len(pages_with_tables) >= 3, "Expected at least 3 pages with tables"

    def test_map_pages_detected(self, pdf_content: PDFContent):
        """Map/diagram pages should have has_map=True."""
        map_pages = [p for p in pdf_content.pages if p.has_map]
        assert len(map_pages) >= 1, "Expected at least 1 map page detected"

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            extract_pdf("/nonexistent/file.pdf")


# ---------------------------------------------------------------------------
# State Detector tests
# ---------------------------------------------------------------------------


class TestStateDetector:
    def test_returns_state_identification(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert isinstance(result, StateIdentification)

    def test_detects_vic(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert result.state == "VIC"

    def test_extracts_address(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert len(result.address) > 5, "Expected a non-trivial address"

    def test_extracts_postcode(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert result.postcode.isdigit()
        assert len(result.postcode) == 4

    def test_extracts_suburb(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert len(result.suburb) > 1

    def test_extracts_reference(self, pdf_content: PDFContent):
        result = detect_state(pdf_content.pages[0].text)
        assert result.lotsearch_reference.startswith("LS")
        assert "EP" in result.lotsearch_reference

    def test_invalid_text_raises(self):
        with pytest.raises(ValueError):
            detect_state("This is just random text with no state info.")


# ---------------------------------------------------------------------------
# Section Splitter tests
# ---------------------------------------------------------------------------


class TestSectionSplitter:
    @pytest.fixture(scope="class")
    def sections(self, pdf_content: PDFContent, vic_pdf_path: Path) -> list[SectionContent]:
        return split_sections(pdf_content, pdf_path=vic_pdf_path)

    def test_returns_sections(self, sections: list[SectionContent]):
        assert isinstance(sections, list)
        assert all(isinstance(s, SectionContent) for s in sections)

    def test_finds_many_sections(self, sections: list[SectionContent]):
        assert len(sections) >= 20, (
            f"Expected 20+ sections, got {len(sections)}: "
            f"{[s.heading for s in sections]}"
        )

    def test_dataset_listing_found(self, sections: list[SectionContent]):
        headings_lower = [s.heading.lower() for s in sections]
        assert any(
            "dataset listing" in h for h in headings_lower
        ), f"Dataset Listing not found in: {headings_lower}"

    def test_dataset_listing_has_table(self, sections: list[SectionContent]):
        for s in sections:
            if "dataset listing" in s.heading.lower():
                assert len(s.tables) >= 1, "Dataset Listing section should have a table"
                break

    def test_sections_cover_all_pages(self, sections: list[SectionContent], pdf_content: PDFContent):
        """All pages should be covered by some section."""
        covered = set()
        for s in sections:
            for pn in range(s.page_range[0], s.page_range[1] + 1):
                covered.add(pn)
        total = len(pdf_content.pages)
        assert covered == set(range(1, total + 1)), (
            f"Pages not covered: {set(range(1, total + 1)) - covered}"
        )

    def test_map_sections_detected(self, sections: list[SectionContent]):
        map_sections = [s for s in sections if s.is_map_section]
        assert len(map_sections) >= 1, "Expected at least 1 map section"

    def test_section_headings_not_empty(self, sections: list[SectionContent]):
        for s in sections:
            assert s.heading.strip(), f"Empty heading for section at pages {s.page_range}"

    def test_page_ranges_valid(self, sections: list[SectionContent]):
        for s in sections:
            assert s.page_range[0] <= s.page_range[1], (
                f"Invalid page range {s.page_range} for {s.heading}"
            )
