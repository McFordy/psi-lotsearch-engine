"""Build interpretation prompts from Jinja2 templates and extracted data."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, Undefined

from src.extract.dataset_listing import DatasetListingEntry
from src.extract.table_extractor import ExtractedSection

# Default prompts directory (relative to this file)
_DEFAULT_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class PromptBuilder:
    """Build interpretation prompts from templates + extracted data.

    Each prompt template (in src/prompts/{state}/*.txt) contains Jinja2
    placeholders that are filled with extracted section data, site address,
    state, and optional cross-section context.
    """

    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = prompts_dir or _DEFAULT_PROMPTS_DIR
        # Set up Jinja2 with the prompts dir as root, searching subdirs
        self._env = Environment(
            loader=FileSystemLoader([str(self.prompts_dir)]),
            undefined=_PermissiveUndefined,
        )

    def build(
        self,
        template_name: str,
        state: str,
        site_address: str,
        section_data: ExtractedSection | list[ExtractedSection],
        lotsearch_reference: str = "",
        context: dict | None = None,
        dataset_listing_summary: str = "",
    ) -> tuple[str, str]:
        """Build a (system_prompt, user_prompt) pair.

        Args:
            template_name: Template filename, e.g. "epa_registers.txt".
                           Loaded from {prompts_dir}/{state}/{template_name}.
            state: "VIC" or "NSW".
            site_address: Full site address string.
            section_data: One or more ExtractedSection objects with the data to interpret.
            lotsearch_reference: Lotsearch reference number (e.g. "LS089658 EP").
            context: Optional dict with cross-section context
                     (e.g. groundwater_direction, groundwater_depth).
            dataset_listing_summary: Summary of dataset listing for context.

        Returns:
            Tuple of (system_prompt, user_prompt).

        Raises:
            FileNotFoundError: If the template file does not exist.
        """
        # Build system prompt from base template
        system_prompt = self._render_system_prompt(
            state=state,
            site_address=site_address,
            lotsearch_reference=lotsearch_reference,
        )

        # Build user prompt from state-specific template
        user_prompt = self._render_user_prompt(
            template_name=template_name,
            state=state,
            site_address=site_address,
            section_data=section_data,
            context=context,
            dataset_listing_summary=dataset_listing_summary,
        )

        return system_prompt, user_prompt

    def _render_system_prompt(
        self,
        state: str,
        site_address: str,
        lotsearch_reference: str,
    ) -> str:
        """Render the base system prompt."""
        try:
            template = self._env.get_template("system_base.txt")
        except TemplateNotFound:
            raise FileNotFoundError(
                f"System base template not found at {self.prompts_dir}/system_base.txt"
            )

        return template.render(
            site_address=site_address,
            state=state,
            lotsearch_reference=lotsearch_reference,
        )

    def _render_user_prompt(
        self,
        template_name: str,
        state: str,
        site_address: str,
        section_data: ExtractedSection | list[ExtractedSection],
        context: dict | None,
        dataset_listing_summary: str,
    ) -> str:
        """Render a state-specific user prompt template."""
        state_lower = state.lower()
        template_path = f"{state_lower}/{template_name}"

        try:
            template = self._env.get_template(template_path)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template not found: {self.prompts_dir}/{template_path}"
            )

        # Serialise section data to JSON for the template
        if isinstance(section_data, list):
            data_json = json.dumps(
                [s.model_dump() for s in section_data], indent=2, default=str
            )
        else:
            data_json = json.dumps(
                section_data.model_dump(), indent=2, default=str
            )

        render_vars = {
            "site_address": site_address,
            "state": state,
            "section_data": data_json,
            "dataset_listing_summary": dataset_listing_summary,
        }

        # Add any cross-section context
        if context:
            render_vars.update(context)

        return template.render(**render_vars)

    def list_templates(self, state: str) -> list[str]:
        """List available templates for a given state."""
        state_dir = self.prompts_dir / state.lower()
        if not state_dir.is_dir():
            return []
        return sorted(f.name for f in state_dir.glob("*.txt"))

    @staticmethod
    def summarise_listing(entries: list[DatasetListingEntry]) -> str:
        """Generate a concise summary of the dataset listing for prompt context."""
        lines = []
        for e in entries:
            counts = []
            if e.count_onsite is not None:
                counts.append(f"on-site={e.count_onsite}")
            if e.count_within_100m is not None:
                counts.append(f"100m={e.count_within_100m}")
            if e.count_within_buffer is not None:
                counts.append(f"buffer={e.count_within_buffer}")
            count_str = ", ".join(counts) if counts else "N/A"
            hit_marker = " *" if e.has_hits else ""
            lines.append(f"- {e.dataset_name} [{count_str}]{hit_marker}")
        return "\n".join(lines)


class _PermissiveUndefined(Undefined):
    """Jinja2 undefined that returns empty string for missing variables.

    This avoids template errors for optional variables like groundwater_context.
    """

    def __str__(self) -> str:
        return ""

    def __iter__(self):
        return iter([])

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name):
        return self
