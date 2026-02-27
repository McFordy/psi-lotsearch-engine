"""Orchestrate Claude API calls for interpretation of extracted data into report prose."""

from __future__ import annotations

import logging
import os
import re
import time

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.extract.table_extractor import ExtractedSection
from src.interpret.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

# Section grouping: maps template names to the section IDs they produce
_SECTION_TEMPLATES: dict[str, str] = {
    "env_setting.txt": "3_env_setting",
    "groundwater_bores.txt": "3.3.1_groundwater_bores",
    "epa_registers.txt": "4.3_epa_registers",
    "env_audits.txt": "4.3_env_audits",
    "business_dirs.txt": "4.1_business_dirs",
    "pfas.txt": "4.4_pfas",
    "waste_liquid_fuel.txt": "4.5_waste_liquid_fuel",
    "mining_fire.txt": "4.6_mining_fire",
    "mining.txt": "4.6_mining",
    "defence.txt": "4.8_defence",
    "site_history_table.txt": "4.9_site_history",
    "poeo_licences.txt": "4.3_poeo_licences",
}

# Default retry configuration
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


class InterpretedSection(BaseModel):
    """AI-interpreted report section."""

    section_id: str
    prose: str  # Generated report prose (Markdown)
    confidence: str = "MEDIUM"  # HIGH, MEDIUM, or LOW (worst in section)
    review_flags: list[str] = Field(default_factory=list)
    tables_markdown: list[str] = Field(default_factory=list)


class PromptLog(BaseModel):
    """Log entry for a single API call."""

    section_id: str
    system_prompt: str
    user_prompt: str
    response: str = ""
    error: str = ""


class AIInterpreter:
    """Orchestrate Claude API calls for data interpretation.

    Each interpretation call sends a system prompt (base role + state-specific
    rules) and a user prompt (extracted section data + instructions) to Claude,
    then collects and structures the response.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        prompt_builder: PromptBuilder | None = None,
    ):
        load_dotenv()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.prompt_log: list[PromptLog] = []

        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def interpret_section(
        self,
        template_name: str,
        section_data: ExtractedSection | list[ExtractedSection],
        state: str,
        site_address: str,
        lotsearch_reference: str = "",
        context: dict | None = None,
        dataset_listing_summary: str = "",
    ) -> InterpretedSection:
        """Interpret a single section or group of sections.

        Args:
            template_name: Template filename (e.g. "epa_registers.txt").
            section_data: Extracted data for one or more sections.
            state: "VIC" or "NSW".
            site_address: Full site address.
            lotsearch_reference: Lotsearch reference number.
            context: Optional cross-section context dict.
            dataset_listing_summary: Summary of all datasets.

        Returns:
            InterpretedSection with generated prose and metadata.
        """
        section_id = _SECTION_TEMPLATES.get(template_name, template_name)

        # Build prompts
        system_prompt, user_prompt = self.prompt_builder.build(
            template_name=template_name,
            state=state,
            site_address=site_address,
            section_data=section_data,
            lotsearch_reference=lotsearch_reference,
            context=context,
            dataset_listing_summary=dataset_listing_summary,
        )

        log_entry = PromptLog(
            section_id=section_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # Call the API with retries
        prose = self._call_api(system_prompt, user_prompt, log_entry)

        self.prompt_log.append(log_entry)

        # Extract confidence and review flags from the prose
        confidence = _extract_worst_confidence(prose)
        review_flags = _extract_review_flags(prose)
        tables_md = _extract_markdown_tables(prose)

        return InterpretedSection(
            section_id=section_id,
            prose=prose,
            confidence=confidence,
            review_flags=review_flags,
            tables_markdown=tables_md,
        )

    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        log_entry: PromptLog,
    ) -> str:
        """Call the Claude API with retry logic."""
        if not self.client:
            logger.warning("No API client available — returning extraction-only output")
            log_entry.error = "API unavailable: no API key configured"
            return (
                "<!-- EXTRACTION_ONLY: API unavailable -->\n\n"
                "<!-- GENERATION_FAILED: This section requires manual completion -->"
            )

        last_error = ""
        for attempt in range(_MAX_RETRIES):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                prose = response.content[0].text
                log_entry.response = prose
                return prose

            except (anthropic.APIError, anthropic.APIConnectionError) as e:
                last_error = str(e)
                logger.warning(
                    "API call failed (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    last_error,
                )
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2**attempt)
                    time.sleep(delay)

        # All retries exhausted
        log_entry.error = f"API unavailable after {_MAX_RETRIES} retries: {last_error}"
        logger.error(log_entry.error)
        return (
            f"<!-- EXTRACTION_ONLY: API unavailable after {_MAX_RETRIES} retries -->\n\n"
            "<!-- GENERATION_FAILED: This section requires manual completion -->"
        )

    def interpret_all(
        self,
        sections_by_template: dict[str, ExtractedSection | list[ExtractedSection]],
        state: str,
        site_address: str,
        lotsearch_reference: str = "",
        context: dict | None = None,
        dataset_listing_summary: str = "",
    ) -> list[InterpretedSection]:
        """Interpret all sections using their mapped templates.

        Args:
            sections_by_template: Dict mapping template names to extracted section data.
            state: "VIC" or "NSW".
            site_address: Full site address.
            lotsearch_reference: Lotsearch reference number.
            context: Optional cross-section context.
            dataset_listing_summary: Summary of all datasets.

        Returns:
            List of InterpretedSection objects.
        """
        results: list[InterpretedSection] = []

        for template_name, section_data in sections_by_template.items():
            result = self.interpret_section(
                template_name=template_name,
                section_data=section_data,
                state=state,
                site_address=site_address,
                lotsearch_reference=lotsearch_reference,
                context=context,
                dataset_listing_summary=dataset_listing_summary,
            )
            results.append(result)

        return results


def _extract_worst_confidence(prose: str) -> str:
    """Extract the worst (lowest) confidence level from confidence tags in prose."""
    tags = re.findall(r"<!--\s*CONFIDENCE:\s*(\w+)", prose)
    if not tags:
        return "MEDIUM"

    # Rank: LOW < MEDIUM < HIGH
    ranking = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    worst = min(tags, key=lambda t: ranking.get(t.upper(), 1))
    return worst.upper()


def _extract_review_flags(prose: str) -> list[str]:
    """Extract review flag comments from the prose."""
    flags = re.findall(
        r"<!--\s*CONFIDENCE:\s*LOW\s*[—-]\s*(.+?)\s*-->", prose
    )
    # Also catch VALIDATION_FAILED tags
    flags.extend(
        re.findall(r"<!--\s*VALIDATION_FAILED:\s*(.+?)\s*-->", prose)
    )
    return flags


def _extract_markdown_tables(prose: str) -> list[str]:
    """Extract Markdown tables from the prose."""
    tables: list[str] = []
    lines = prose.split("\n")
    current_table: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            current_table.append(line)
        else:
            if in_table and current_table:
                tables.append("\n".join(current_table))
                current_table = []
            in_table = False

    # Catch table at end of prose
    if current_table:
        tables.append("\n".join(current_table))

    return tables
