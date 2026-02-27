"""Assemble interpreted sections into a complete Markdown report using Jinja2 templates."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from src.ingest.state_detector import StateIdentification
from src.interpret.ai_interpreter import InterpretedSection

_DEFAULT_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_GENERATION_FAILED = "<!-- GENERATION_FAILED: This section requires manual completion -->"

# Patterns that indicate raw prompt text or JSON data leaked into prose
_LEAKED_PATTERNS = [
    "{{ section_data }}",
    "### Interpretation Rules",
    "### Output Format",
    "Generate the ",
    "You are an expert contaminated land consultant",
]


def _sanitize_prose(prose: str) -> str:
    """Replace prose with placeholder if it contains raw prompt text or JSON data."""
    stripped = prose.strip()

    # Check for JSON start (raw data dump)
    if stripped and stripped[0] in ('{', '['):
        return _GENERATION_FAILED

    # Check for known prompt/template markers
    for pattern in _LEAKED_PATTERNS:
        if pattern in prose:
            return _GENERATION_FAILED

    # Check for raw ExtractedSection JSON fields (strong signal of data leak)
    if '"dataset_name":' in prose and '"raw_text":' in prose:
        return _GENERATION_FAILED
    if '"table_headers":' in prose and '"hit_counts":' in prose:
        return _GENERATION_FAILED

    return prose


class ReportRenderer:
    """Assemble interpreted sections into a complete Markdown report.

    Uses Jinja2 master templates that define the overall report structure,
    section ordering, placeholder insertion, and confidence summary.
    """

    def __init__(self, templates_dir: Path | None = None):
        self.templates_dir = templates_dir or _DEFAULT_TEMPLATES_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            keep_trailing_newline=True,
        )

    def render(
        self,
        state: str,
        sections: list[InterpretedSection],
        state_id: StateIdentification,
    ) -> str:
        """Render the full report Markdown.

        Args:
            state: "VIC" or "NSW".
            sections: List of InterpretedSection objects from the AI interpreter.
            state_id: StateIdentification from the ingest layer.

        Returns:
            Complete Markdown report string.
        """
        template_path = f"{state.lower()}/report.md.j2"
        try:
            template = self._env.get_template(template_path)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Report template not found: {self.templates_dir}/{template_path}"
            )

        # Build sections dict keyed by section_id, sanitizing prose
        sections_dict: dict[str, InterpretedSection] = {}
        for s in sections:
            sanitized = _sanitize_prose(s.prose)
            if sanitized != s.prose:
                s = s.model_copy(update={"prose": sanitized})
            sections_dict[s.section_id] = s

        # Build confidence summary
        confidence_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        review_flags: list[str] = []
        for s in sections:
            conf = s.confidence.upper()
            if conf in confidence_counts:
                confidence_counts[conf] += 1
            review_flags.extend(s.review_flags)

        return template.render(
            state_id=state_id,
            sections=sections_dict,
            confidence_counts=confidence_counts,
            review_flags=review_flags,
            generation_date=datetime.now().strftime("%d %B %Y %H:%M"),
        )
