"""Validate AI-generated output before inclusion in the report."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.extract.table_extractor import ExtractedSection
from src.interpret.ai_interpreter import InterpretedSection

# Terms exclusive to VIC that should NOT appear in NSW output
_VIC_ONLY_TERMS = [
    "PPN30",
    "ERS Segment",
    "GQRUZ",
    "Groundwater Quality Restricted Use Zone",
    "Environment Reference Standard (Vic)",
    "EP Act",
]

# Terms exclusive to NSW that should NOT appear in VIC output
_NSW_ONLY_TERMS = [
    "CLM Act",
    "POEO Act",
    "SEPP",
    "State Environmental Planning Policy",
    "Contaminated Land Management Act",
    "Protection of the Environment Operations Act",
]


class ValidationResult(BaseModel):
    """Result of validating an interpreted section."""

    valid: bool = True
    issues: list[str] = Field(default_factory=list)


class OutputValidator:
    """Validate AI-generated prose for correctness.

    Checks performed:
    1. Site address consistency
    2. State consistency (no cross-state regulatory terms)
    3. Confidence tag presence
    4. Nil result consistency
    5. No fabricated identifiers
    """

    def validate(
        self,
        interpreted: InterpretedSection,
        extracted: ExtractedSection,
        state: str,
        site_address: str,
    ) -> ValidationResult:
        """Run all validation checks on an interpreted section.

        Args:
            interpreted: The AI-generated section.
            extracted: The source extracted data.
            state: Expected state ("VIC" or "NSW").
            site_address: Expected site address.

        Returns:
            ValidationResult with valid flag and list of issues.
        """
        issues: list[str] = []

        issues.extend(self._check_address(interpreted.prose, site_address))
        issues.extend(self._check_state_consistency(interpreted.prose, state))
        issues.extend(self._check_confidence_tags(interpreted.prose))
        issues.extend(self._check_nil_consistency(interpreted.prose, extracted))
        issues.extend(self._check_fabricated_ids(interpreted.prose, extracted))

        return ValidationResult(
            valid=len(issues) == 0,
            issues=issues,
        )

    def _check_address(self, prose: str, site_address: str) -> list[str]:
        """Check that the prose references the correct site address."""
        issues = []

        # Extract the key part of the address (street name + number)
        # e.g. from "151 Melville Road, Brunswick West, VIC 3055" get "Melville"
        # We check that at least the street name appears in the prose
        address_parts = site_address.split(",")
        if address_parts:
            street = address_parts[0].strip()
            # Extract significant words (skip common prefixes)
            significant_words = [
                w for w in street.split()
                if len(w) > 3 and not w.isdigit()
                and w.lower() not in {"road", "street", "avenue", "drive", "lane",
                                       "place", "court", "crescent", "terrace",
                                       "highway", "parade", "way", "close",
                                       "boulevard", "circuit"}
            ]
            if significant_words:
                found = any(word.lower() in prose.lower() for word in significant_words)
                if not found:
                    issues.append(
                        f"Site address not found in prose: expected words from "
                        f"'{street}' but none found"
                    )

        return issues

    def _check_state_consistency(self, prose: str, state: str) -> list[str]:
        """Check that prose doesn't contain terms from the wrong state."""
        issues = []

        if state == "VIC":
            # VIC output should NOT contain NSW-only terms
            for term in _NSW_ONLY_TERMS:
                if term in prose:
                    issues.append(
                        f"NSW term '{term}' found in VIC output"
                    )
        elif state == "NSW":
            # NSW output should NOT contain VIC-only terms
            for term in _VIC_ONLY_TERMS:
                if term in prose:
                    issues.append(
                        f"VIC term '{term}' found in NSW output"
                    )

        return issues

    def _check_confidence_tags(self, prose: str) -> list[str]:
        """Check that at least one confidence tag is present."""
        issues = []
        if "<!-- CONFIDENCE:" not in prose:
            issues.append("No confidence tags found in output")
        return issues

    def _check_nil_consistency(
        self, prose: str, extracted: ExtractedSection
    ) -> list[str]:
        """Check that nil-result datasets don't describe specific records."""
        issues = []

        hit_counts = extracted.hit_counts
        if not hit_counts:
            return issues

        onsite = hit_counts.get("onsite")
        within_100m = hit_counts.get("within_100m")
        within_buffer = hit_counts.get("within_buffer")

        # If all counts are 0 (searched but found nothing), prose should
        # not describe specific records with distances/directions
        all_zero = (
            onsite is not None and onsite == 0
            and within_100m is not None and within_100m == 0
            and within_buffer is not None and within_buffer == 0
        )

        if all_zero:
            # Check for patterns that indicate specific records being described
            # e.g. "located 350m south" or "at 123 Main Street, 500m north"
            record_patterns = [
                r"\d+m\s+(north|south|east|west)",
                r"Map ID\s+\d+",
                r"CARMS\s+\d+",
            ]
            for pattern in record_patterns:
                if re.search(pattern, prose, re.IGNORECASE):
                    issues.append(
                        f"Nil-result section describes specific records "
                        f"(matched pattern '{pattern}')"
                    )

        return issues

    def _check_fabricated_ids(
        self, prose: str, extracted: ExtractedSection
    ) -> list[str]:
        """Check that specific IDs mentioned in prose appear in extracted data."""
        issues = []

        # Build a set of all identifiers from extracted data
        known_ids: set[str] = set()
        raw = extracted.raw_text or ""
        for table_row in extracted.tables:
            for value in table_row.values():
                if isinstance(value, str):
                    raw += " " + value

        # Extract CARMS numbers from prose
        carms_in_prose = re.findall(r"CARMS\s+(?:No\.?\s*)?(\d{4,}[\-/]?\d*)", prose)
        for carms in carms_in_prose:
            if carms not in raw:
                issues.append(f"CARMS number '{carms}' not found in extracted data")

        # Extract bore IDs from prose (e.g. "bore 12345", "WRK12345")
        bore_ids_in_prose = re.findall(r"\b(WRK\d+|bore\s+(\d{4,}))\b", prose, re.IGNORECASE)
        for match in bore_ids_in_prose:
            bore_id = match[0] if not match[1] else match[1]
            if bore_id not in raw:
                issues.append(f"Bore ID '{bore_id}' not found in extracted data")

        # Extract licence numbers from prose
        licence_ids = re.findall(r"\b([A-Z]{2,3}\d{6,})\b", prose)
        for lic_id in licence_ids:
            # Skip common false positives
            if lic_id.startswith("VIC") or lic_id.startswith("NSW"):
                continue
            if lic_id not in raw:
                issues.append(f"Licence ID '{lic_id}' not found in extracted data")

        return issues
