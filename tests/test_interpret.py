"""Tests for the interpret layer — prompt builder, AI interpreter, and validator.

No real API calls are made; the anthropic client is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extract.table_extractor import ExtractedSection
from src.interpret.ai_interpreter import (
    AIInterpreter,
    InterpretedSection,
    _extract_markdown_tables,
    _extract_review_flags,
    _extract_worst_confidence,
)
from src.interpret.prompt_builder import PromptBuilder
from src.interpret.validator import OutputValidator, ValidationResult

PROMPTS_DIR = Path(__file__).parent.parent / "src" / "prompts"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder(prompts_dir=PROMPTS_DIR)


@pytest.fixture
def validator() -> OutputValidator:
    return OutputValidator()


@pytest.fixture
def sample_extracted() -> ExtractedSection:
    return ExtractedSection(
        dataset_name="EPA Environmental Audit Reports",
        heading="EPA Records",
        raw_text="Map ID 1 CARMS 48497-1 137-139 Melville Rd Brunswick West",
        tables=[
            {
                "Map ID": "1",
                "Transaction No": "0008001507",
                "CARMS No": "48497-1",
                "Site": "137-139 MELVILLE RD",
                "Address": "137-139 MELVILLE RD",
                "Suburb": "BRUNSWICK WEST",
            }
        ],
        table_headers=[
            ["Map ID", "Transaction No", "CARMS No", "Site", "Address", "Suburb"]
        ],
        hit_counts={"onsite": 0, "within_100m": 1, "within_buffer": 23},
        custodian="Environment Protection Authority Victoria",
    )


@pytest.fixture
def nil_extracted() -> ExtractedSection:
    return ExtractedSection(
        dataset_name="PFAS Investigation Sites",
        heading="PFAS Investigation & Management Programs",
        raw_text="No records in buffer",
        tables=[{"Map ID": "N/A", "Site Name": "No records in buffer", "_no_records": True}],
        table_headers=[["Map ID", "Site Name", "Address"]],
        hit_counts={"onsite": 0, "within_100m": 0, "within_buffer": 0},
        custodian="Defence",
        has_no_records=True,
    )


# ---------------------------------------------------------------------------
# PromptBuilder tests
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_loads_system_base_template(self, builder: PromptBuilder):
        system, user = builder.build(
            template_name="epa_registers.txt",
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
            section_data=ExtractedSection(
                dataset_name="test", heading="test", raw_text="test"
            ),
            lotsearch_reference="LS089658 EP",
        )
        assert "expert contaminated land consultant" in system
        assert "151 Melville Road" in system
        assert "VIC" in system
        assert "LS089658 EP" in system

    def test_loads_vic_template(self, builder: PromptBuilder):
        section = ExtractedSection(
            dataset_name="EPA registers", heading="EPA", raw_text="test data"
        )
        system, user = builder.build(
            template_name="epa_registers.txt",
            state="VIC",
            site_address="123 Test St, Melbourne, VIC 3000",
            section_data=section,
        )
        assert "EPA Victoria Regulatory Registers" in user
        assert "test data" in user  # section data is serialised into the prompt

    def test_loads_nsw_template(self, builder: PromptBuilder):
        section = ExtractedSection(
            dataset_name="POEO", heading="POEO", raw_text="licence data"
        )
        system, user = builder.build(
            template_name="poeo_licences.txt",
            state="NSW",
            site_address="42 George St, Sydney, NSW 2000",
            section_data=section,
        )
        assert "POEO Act" in user

    def test_section_data_serialised_as_json(self, builder: PromptBuilder):
        section = ExtractedSection(
            dataset_name="Test Dataset",
            heading="Test Heading",
            raw_text="Some text",
            tables=[{"col1": "val1"}],
        )
        _, user = builder.build(
            template_name="pfas.txt",
            state="VIC",
            site_address="test",
            section_data=section,
        )
        # Should contain JSON-serialised section data
        assert '"dataset_name": "Test Dataset"' in user
        assert '"col1": "val1"' in user

    def test_list_of_sections(self, builder: PromptBuilder):
        sections = [
            ExtractedSection(dataset_name="A", heading="A", raw_text="a"),
            ExtractedSection(dataset_name="B", heading="B", raw_text="b"),
        ]
        _, user = builder.build(
            template_name="pfas.txt",
            state="VIC",
            site_address="test",
            section_data=sections,
        )
        assert '"dataset_name": "A"' in user
        assert '"dataset_name": "B"' in user

    def test_missing_template_raises(self, builder: PromptBuilder):
        with pytest.raises(FileNotFoundError):
            builder.build(
                template_name="nonexistent_template.txt",
                state="VIC",
                site_address="test",
                section_data=ExtractedSection(
                    dataset_name="x", heading="x", raw_text="x"
                ),
            )

    def test_missing_system_base_raises(self, tmp_path):
        # Create a dir with a vic subdir but no system_base.txt
        vic_dir = tmp_path / "vic"
        vic_dir.mkdir()
        (vic_dir / "test.txt").write_text("{{ section_data }}")
        builder = PromptBuilder(prompts_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match="system_base"):
            builder.build(
                template_name="test.txt",
                state="VIC",
                site_address="test",
                section_data=ExtractedSection(
                    dataset_name="x", heading="x", raw_text="x"
                ),
            )

    def test_list_templates(self, builder: PromptBuilder):
        vic_templates = builder.list_templates("VIC")
        assert len(vic_templates) >= 9
        assert "epa_registers.txt" in vic_templates
        assert "env_setting.txt" in vic_templates

        nsw_templates = builder.list_templates("NSW")
        assert len(nsw_templates) >= 9
        assert "poeo_licences.txt" in nsw_templates

    def test_summarise_listing(self):
        from src.extract.dataset_listing import DatasetListingEntry

        entries = [
            DatasetListingEntry(
                dataset_name="EPA Audit Reports",
                custodian="EPA VIC",
                count_onsite=0,
                count_within_100m=1,
                count_within_buffer=23,
                has_hits=True,
            ),
            DatasetListingEntry(
                dataset_name="PFAS Sites",
                custodian="Defence",
                count_onsite=0,
                count_within_100m=0,
                count_within_buffer=0,
                has_hits=False,
            ),
        ]
        summary = PromptBuilder.summarise_listing(entries)
        assert "EPA Audit Reports" in summary
        assert "buffer=23" in summary
        assert "PFAS Sites" in summary
        # Entries with hits are marked with *
        assert "*" in summary

    def test_optional_context_variables(self, builder: PromptBuilder):
        """Templates with undefined optional vars should render without error."""
        section = ExtractedSection(
            dataset_name="test", heading="test", raw_text="data"
        )
        # env_setting.txt doesn't require groundwater_context but should handle it
        _, user = builder.build(
            template_name="env_setting.txt",
            state="VIC",
            site_address="test",
            section_data=section,
            context={"groundwater_direction": "south-east"},
        )
        assert "data" in user


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


class TestValidator:
    def test_valid_output_passes(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="4.3_epa_registers",
            prose=(
                "A review of the EPA Environmental Audit Reports identified "
                "23 audit records within 1,000m of the Site at 151 Melville Road, "
                "Brunswick West.\n\n"
                "The closest audit (CARMS 48497-1) is located at 137-139 Melville Road, "
                "Brunswick West, approximately 12m south of the Site.\n\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert result.valid, f"Expected valid but got issues: {result.issues}"

    def test_catches_wrong_address(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "The Site at 42 George Street, Sydney is not contaminated.\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert not result.valid
        assert any("address" in issue.lower() for issue in result.issues)

    def test_catches_vic_terms_in_nsw(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "A review of the GQRUZ identified no restrictions near the Site "
                "at 42 George Street.\n"
                "The ERS Segment classification is A1.\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="NSW",
            site_address="42 George Street, Sydney, NSW 2000",
        )
        assert not result.valid
        vic_issues = [i for i in result.issues if "VIC term" in i]
        assert len(vic_issues) >= 1

    def test_catches_nsw_terms_in_vic(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "Under the CLM Act, the Site at 151 Melville Road is listed.\n"
                "A POEO Act licence was identified.\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert not result.valid
        nsw_issues = [i for i in result.issues if "NSW term" in i]
        assert len(nsw_issues) >= 1

    def test_catches_missing_confidence_tags(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose="The Site at 151 Melville Road has no issues.",
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert not result.valid
        assert any("confidence" in issue.lower() for issue in result.issues)

    def test_catches_nil_inconsistency(
        self, validator: OutputValidator, nil_extracted: ExtractedSection
    ):
        """If all counts are 0, prose should not describe specific records."""
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "A PFAS investigation site was identified 350m south of the Site.\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, nil_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert not result.valid
        assert any("nil-result" in issue.lower() or "nil" in issue.lower() for issue in result.issues)

    def test_passes_valid_nil_output(
        self, validator: OutputValidator, nil_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "A search of the PFAS Investigation Sites database identified "
                "no PFAS investigation or management sites at or within 2,000m "
                "of the Site at 151 Melville Road.\n\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, nil_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert result.valid, f"Expected valid but got issues: {result.issues}"

    def test_catches_fabricated_carms(
        self, validator: OutputValidator, sample_extracted: ExtractedSection
    ):
        interpreted = InterpretedSection(
            section_id="test",
            prose=(
                "The audit CARMS 99999-9 is located near the Site at Melville Road.\n"
                "<!-- CONFIDENCE: HIGH -->"
            ),
        )
        result = validator.validate(
            interpreted, sample_extracted,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
        )
        assert not result.valid
        assert any("CARMS" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# AI Interpreter tests (mocked)
# ---------------------------------------------------------------------------


class TestAIInterpreter:
    def _make_mock_response(self, text: str) -> MagicMock:
        """Create a mock anthropic API response."""
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = text
        mock_response.content = [mock_content]
        return mock_response

    @patch("src.interpret.ai_interpreter.anthropic.Anthropic")
    def test_interpret_section_builds_prompts(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_mock_response(
            "### 4.3 EPA Registers\n\nNo issues found.\n\n<!-- CONFIDENCE: HIGH -->"
        )

        interpreter = AIInterpreter(api_key="test-key")
        interpreter.client = mock_client

        section = ExtractedSection(
            dataset_name="EPA Registers",
            heading="EPA Records",
            raw_text="test data",
        )

        result = interpreter.interpret_section(
            template_name="epa_registers.txt",
            section_data=section,
            state="VIC",
            site_address="151 Melville Road, Brunswick West, VIC 3055",
            lotsearch_reference="LS089658 EP",
        )

        assert isinstance(result, InterpretedSection)
        assert result.section_id == "4.3_epa_registers"
        assert "EPA Registers" in result.prose or "No issues" in result.prose

        # Verify the API was called with system and user prompts
        call_args = mock_client.messages.create.call_args
        assert "claude-sonnet" in call_args.kwargs["model"]
        assert "expert contaminated land consultant" in call_args.kwargs["system"]
        assert "EPA Victoria" in call_args.kwargs["messages"][0]["content"]

    @patch("src.interpret.ai_interpreter.anthropic.Anthropic")
    def test_interpret_section_handles_api_failure(self, mock_anthropic_cls):
        import anthropic as anthropic_mod

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_mod.APIConnectionError(
            request=MagicMock()
        )

        interpreter = AIInterpreter(api_key="test-key")
        interpreter.client = mock_client

        section = ExtractedSection(
            dataset_name="test", heading="test", raw_text="data"
        )

        # Patch sleep to avoid waiting during test
        with patch("src.interpret.ai_interpreter.time.sleep"):
            result = interpreter.interpret_section(
                template_name="pfas.txt",
                section_data=section,
                state="VIC",
                site_address="test address",
            )

        assert "EXTRACTION_ONLY" in result.prose
        assert mock_client.messages.create.call_count == 3  # 3 retries

    def test_no_api_key_returns_extraction_only(self):
        interpreter = AIInterpreter(api_key="")
        interpreter.client = None

        section = ExtractedSection(
            dataset_name="test", heading="test", raw_text="data"
        )

        result = interpreter.interpret_section(
            template_name="pfas.txt",
            section_data=section,
            state="VIC",
            site_address="test",
        )

        assert "EXTRACTION_ONLY" in result.prose

    @patch("src.interpret.ai_interpreter.anthropic.Anthropic")
    def test_interpret_all(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_mock_response(
            "Section output.\n<!-- CONFIDENCE: MEDIUM -->"
        )

        interpreter = AIInterpreter(api_key="test-key")
        interpreter.client = mock_client

        sections = {
            "pfas.txt": ExtractedSection(
                dataset_name="PFAS", heading="PFAS", raw_text="nil"
            ),
            "defence.txt": ExtractedSection(
                dataset_name="Defence", heading="Defence", raw_text="nil"
            ),
        }

        results = interpreter.interpret_all(
            sections_by_template=sections,
            state="VIC",
            site_address="test address",
        )

        assert len(results) == 2
        assert mock_client.messages.create.call_count == 2

    @patch("src.interpret.ai_interpreter.anthropic.Anthropic")
    def test_prompt_log_recorded(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_mock_response(
            "Output.\n<!-- CONFIDENCE: HIGH -->"
        )

        interpreter = AIInterpreter(api_key="test-key")
        interpreter.client = mock_client

        section = ExtractedSection(
            dataset_name="test", heading="test", raw_text="data"
        )

        interpreter.interpret_section(
            template_name="pfas.txt",
            section_data=section,
            state="VIC",
            site_address="test",
        )

        assert len(interpreter.prompt_log) == 1
        log = interpreter.prompt_log[0]
        assert log.system_prompt != ""
        assert log.user_prompt != ""
        assert log.response != ""


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_extract_worst_confidence_high(self):
        prose = "Text <!-- CONFIDENCE: HIGH --> more text <!-- CONFIDENCE: HIGH -->"
        assert _extract_worst_confidence(prose) == "HIGH"

    def test_extract_worst_confidence_mixed(self):
        prose = "<!-- CONFIDENCE: HIGH --> text <!-- CONFIDENCE: LOW — REVIEW REQUIRED -->"
        assert _extract_worst_confidence(prose) == "LOW"

    def test_extract_worst_confidence_none(self):
        prose = "No tags here."
        assert _extract_worst_confidence(prose) == "MEDIUM"

    def test_extract_review_flags(self):
        prose = (
            "<!-- CONFIDENCE: LOW — Site requires further investigation -->"
            " and <!-- CONFIDENCE: LOW — Check audit conditions -->"
        )
        flags = _extract_review_flags(prose)
        assert len(flags) == 2
        assert "Site requires further investigation" in flags[0]

    def test_extract_markdown_tables(self):
        prose = (
            "Some text.\n\n"
            "| Bore ID | Distance | Direction |\n"
            "|---------|----------|----------|\n"
            "| WRK123  | 500m     | North    |\n"
            "| WRK456  | 800m     | South    |\n\n"
            "More text."
        )
        tables = _extract_markdown_tables(prose)
        assert len(tables) == 1
        assert "WRK123" in tables[0]

    def test_extract_no_tables(self):
        prose = "Just text, no tables."
        tables = _extract_markdown_tables(prose)
        assert len(tables) == 0
