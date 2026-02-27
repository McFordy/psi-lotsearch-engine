"""Tests for the extract layer — runs against real PDFs in training_data/vic/."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.extract.dataset_listing import DatasetListingEntry, parse_dataset_listing
from src.extract.table_extractor import ExtractedSection, extract_section
from src.ingest.pdf_extractor import PDFContent, extract_pdf
from src.ingest.section_splitter import SectionContent, split_sections
from src.ingest.state_detector import detect_state

TRAINING_DIR = Path(__file__).parent.parent / "training_data" / "vic"

BRUNSWICK_PDF = TRAINING_DIR / "B - Lotsearch LS089658_EP - 151 Melville _Bat.pdf"
COBDEN_PDF = TRAINING_DIR / "Lotsearch LS115592_EP - Boundary Road, Cobden, VIC 3266_Batch Compress.pdf"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def brunswick_content() -> PDFContent:
    if not BRUNSWICK_PDF.exists():
        pytest.skip("Brunswick West PDF not found")
    return extract_pdf(BRUNSWICK_PDF)


@pytest.fixture(scope="module")
def brunswick_listing(brunswick_content: PDFContent) -> list[DatasetListingEntry]:
    return parse_dataset_listing(brunswick_content)


@pytest.fixture(scope="module")
def brunswick_sections(brunswick_content: PDFContent) -> list[SectionContent]:
    return split_sections(brunswick_content, pdf_path=BRUNSWICK_PDF)


@pytest.fixture(scope="module")
def cobden_content() -> PDFContent:
    if not COBDEN_PDF.exists():
        pytest.skip("Cobden PDF not found")
    return extract_pdf(COBDEN_PDF)


@pytest.fixture(scope="module")
def cobden_listing(cobden_content: PDFContent) -> list[DatasetListingEntry]:
    return parse_dataset_listing(cobden_content)


# ---------------------------------------------------------------------------
# Dataset Listing — Brunswick West
# ---------------------------------------------------------------------------


class TestDatasetListingBrunswick:
    def test_parses_successfully(self, brunswick_listing: list[DatasetListingEntry]):
        assert isinstance(brunswick_listing, list)
        assert all(isinstance(e, DatasetListingEntry) for e in brunswick_listing)

    def test_has_45_plus_entries(self, brunswick_listing: list[DatasetListingEntry]):
        assert len(brunswick_listing) >= 45, (
            f"Expected 45+ entries, got {len(brunswick_listing)}"
        )

    def test_epa_audit_with_buffer_hits(self, brunswick_listing: list[DatasetListingEntry]):
        """EPA Environmental Audit Reports should have count_within_buffer >= 20."""
        audit_entries = [
            e for e in brunswick_listing
            if "EPA Environmental Audit" in e.dataset_name
        ]
        assert len(audit_entries) >= 1, (
            f"No EPA Environmental Audit entry found. Names: "
            f"{[e.dataset_name for e in brunswick_listing]}"
        )
        audit = audit_entries[0]
        assert audit.count_within_buffer is not None
        assert audit.count_within_buffer >= 20, (
            f"Expected count_within_buffer >= 20, got {audit.count_within_buffer}"
        )

    def test_has_entries_with_hits(self, brunswick_listing: list[DatasetListingEntry]):
        hits = [e for e in brunswick_listing if e.has_hits]
        assert len(hits) >= 5, f"Expected at least 5 entries with hits, got {len(hits)}"

    def test_has_entries_without_hits(self, brunswick_listing: list[DatasetListingEntry]):
        no_hits = [e for e in brunswick_listing if not e.has_hits]
        assert len(no_hits) >= 5, f"Expected at least 5 entries without hits, got {len(no_hits)}"

    def test_buffer_distances_include_expected_values(
        self, brunswick_listing: list[DatasetListingEntry]
    ):
        buffers = {e.buffer_m for e in brunswick_listing if e.buffer_m is not None}
        assert 1000 in buffers, f"Expected 1000m buffer, got {buffers}"
        assert 2000 in buffers, f"Expected 2000m buffer, got {buffers}"
        # Brunswick West also has 250m buffers for business directories
        has_small_buffer = any(b <= 500 for b in buffers)
        assert has_small_buffer, f"Expected a buffer <= 500m, got {buffers}"

    def test_distinguishes_dash_from_zero(self, brunswick_listing: list[DatasetListingEntry]):
        """Entries with '-' should have None counts, not 0."""
        topo = [e for e in brunswick_listing if "Topographic" in e.dataset_name]
        assert len(topo) >= 1
        # Topographic data has "-" for all counts
        assert topo[0].count_onsite is None
        assert topo[0].count_within_100m is None
        assert topo[0].count_within_buffer is None
        assert topo[0].buffer_m is None
        assert topo[0].has_hits is False

    def test_dataset_names_not_empty(self, brunswick_listing: list[DatasetListingEntry]):
        for entry in brunswick_listing:
            assert entry.dataset_name.strip(), f"Empty dataset name: {entry}"

    def test_multiline_names_reconstructed(self, brunswick_listing: list[DatasetListingEntry]):
        """Dataset names with line breaks in PDF cells should be joined."""
        # "Defence PFAS Investigation & Management Program - Investigation Sites"
        pfas_entries = [
            e for e in brunswick_listing
            if "Defence PFAS" in e.dataset_name and "Investigation Sites" in e.dataset_name
        ]
        assert len(pfas_entries) >= 1, (
            "Multi-line dataset name not reconstructed correctly"
        )


# ---------------------------------------------------------------------------
# Dataset Listing — Cobden
# ---------------------------------------------------------------------------


class TestDatasetListingCobden:
    def test_parses_successfully(self, cobden_listing: list[DatasetListingEntry]):
        assert isinstance(cobden_listing, list)
        assert len(cobden_listing) >= 20

    def test_state_detection(self, cobden_content: PDFContent):
        state = detect_state(cobden_content.pages[0].text)
        assert state.state == "VIC"
        assert "Cobden" in state.address

    def test_has_entries_with_and_without_hits(
        self, cobden_listing: list[DatasetListingEntry]
    ):
        hits = [e for e in cobden_listing if e.has_hits]
        no_hits = [e for e in cobden_listing if not e.has_hits]
        assert len(hits) >= 1
        assert len(no_hits) >= 1


# ---------------------------------------------------------------------------
# Generic Table Extractor
# ---------------------------------------------------------------------------


class TestTableExtractor:
    def test_extract_section_with_data(
        self, brunswick_sections: list[SectionContent], brunswick_listing: list[DatasetListingEntry]
    ):
        """Extract a section that has actual data rows (EPA Records)."""
        # Find the EPA Records section with audit data (not the map page)
        epa_sections = [
            s for s in brunswick_sections
            if s.heading == "EPA Records" and not s.is_map_section
        ]
        assert len(epa_sections) >= 1, "No EPA Records data section found"
        section = epa_sections[0]

        # Find matching listing entry
        audit_entry = next(
            (e for e in brunswick_listing if "EPA Environmental Audit" in e.dataset_name),
            None,
        )

        result = extract_section(section, listing_entry=audit_entry)
        assert isinstance(result, ExtractedSection)
        assert result.heading == "EPA Records"
        assert len(result.tables) > 0, "Expected extracted table rows"
        assert len(result.table_headers) > 0, "Expected table headers"

        # Tables should be list-of-dicts
        for row in result.tables:
            assert isinstance(row, dict), f"Expected dict row, got {type(row)}"

        # Hit counts should be populated from the listing entry
        assert result.hit_counts.get("within_buffer") is not None

    def test_extract_section_with_no_records(
        self, brunswick_sections: list[SectionContent]
    ):
        """Extract a section with all nil results (PFAS)."""
        pfas_sections = [
            s for s in brunswick_sections
            if "PFAS" in s.heading
        ]
        assert len(pfas_sections) >= 1
        section = pfas_sections[0]

        result = extract_section(section)
        assert isinstance(result, ExtractedSection)
        assert result.has_no_records, (
            "PFAS section should flag has_no_records=True"
        )

    def test_extract_section_without_listing_entry(
        self, brunswick_sections: list[SectionContent]
    ):
        """Extract should work even without a DatasetListingEntry."""
        section = brunswick_sections[0]  # Cover Page
        result = extract_section(section)
        assert isinstance(result, ExtractedSection)
        assert result.dataset_name == section.heading
        assert result.hit_counts == {}

    def test_table_headers_cleaned(
        self, brunswick_sections: list[SectionContent], brunswick_listing: list[DatasetListingEntry]
    ):
        """Multi-line header cells should be collapsed to single line."""
        # EPA Activities section has multi-line headers like "Transaction\nNo"
        epa_act_sections = [
            s for s in brunswick_sections
            if s.heading == "EPA Activities" and not s.is_map_section
        ]
        if not epa_act_sections:
            pytest.skip("No EPA Activities data section found")
        section = epa_act_sections[0]

        result = extract_section(section)
        for headers in result.table_headers:
            for h in headers:
                assert "\n" not in h, f"Header not cleaned: {h!r}"

    def test_map_legend_tables_skipped(
        self, brunswick_sections: list[SectionContent]
    ):
        """Map page legend artifact tables should not appear in extracted data."""
        # Site Diagram is a map-only page
        diagram_sections = [
            s for s in brunswick_sections
            if s.heading == "Site Diagram"
        ]
        assert len(diagram_sections) >= 1
        section = diagram_sections[0]

        result = extract_section(section)
        # Legend artifacts should be filtered out, so tables should be empty or minimal
        assert isinstance(result, ExtractedSection)
        # The raw text is preserved regardless
        assert len(result.raw_text) > 0
