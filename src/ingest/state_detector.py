"""Detect Australian state, address, and Lotsearch reference from page 1 of a report."""

from __future__ import annotations

import re

from pydantic import BaseModel


class StateIdentification(BaseModel):
    """Identification info extracted from the first page of a Lotsearch report."""

    state: str  # "VIC" or "NSW"
    address: str  # Full site address as printed on the report
    suburb: str
    postcode: str
    lotsearch_reference: str  # e.g. "LS115592 EP"


# Regex for state + postcode pattern, e.g. "VIC 3266" or "NSW 2000"
_STATE_POSTCODE_RE = re.compile(r"\b(VIC|NSW)\s+(\d{4})\b")

# Regex for Lotsearch reference, e.g. "LS115592 EP" or "LS089658_EP"
_REFERENCE_RE = re.compile(r"(LS\d+[\s_]?EP)")

# Regex for the Address line on page 1
_ADDRESS_RE = re.compile(r"Address:\s*(.+)")

# Regex for Reference line on page 1
_REF_LINE_RE = re.compile(r"Reference:\s*(.+)")


def _detect_state_from_postcode(postcode: str) -> str | None:
    """Fallback state detection based on postcode range."""
    try:
        pc = int(postcode)
    except (ValueError, TypeError):
        return None
    if 3000 <= pc <= 3999:
        return "VIC"
    if 2000 <= pc <= 2999:
        return "NSW"
    return None


def detect_state(page1_text: str) -> StateIdentification:
    """Parse page 1 of a Lotsearch report to extract state and address info.

    Detection strategy:
    1. Look for explicit (VIC|NSW) + postcode pattern.
    2. If no state found, use postcode range as fallback.

    Args:
        page1_text: Extracted text from page 1 of the PDF.

    Returns:
        StateIdentification with state, address, suburb, postcode, and reference.

    Raises:
        ValueError: If state cannot be determined.
    """
    # Extract Lotsearch reference
    ref_match = _REF_LINE_RE.search(page1_text)
    reference = ref_match.group(1).strip() if ref_match else ""
    if not reference:
        ref_match = _REFERENCE_RE.search(page1_text)
        reference = ref_match.group(1).strip() if ref_match else ""

    # Extract full address line
    addr_match = _ADDRESS_RE.search(page1_text)
    full_address = addr_match.group(1).strip() if addr_match else ""

    # Strategy 1: regex for STATE POSTCODE
    state_match = _STATE_POSTCODE_RE.search(page1_text)
    if state_match:
        state = state_match.group(1)
        postcode = state_match.group(2)
    else:
        # Strategy 2: find any 4-digit postcode and infer state
        postcode_match = re.search(r"\b(\d{4})\b", full_address)
        postcode = postcode_match.group(1) if postcode_match else ""
        state = _detect_state_from_postcode(postcode) or ""

    if not state:
        raise ValueError(f"Cannot determine state from page 1 text: {page1_text[:200]!r}")

    # Parse suburb from address: typically "Street, Suburb, STATE POSTCODE"
    suburb = _extract_suburb(full_address, state, postcode)

    return StateIdentification(
        state=state,
        address=full_address,
        suburb=suburb,
        postcode=postcode,
        lotsearch_reference=reference,
    )


def _extract_suburb(address: str, state: str, postcode: str) -> str:
    """Extract suburb from a Lotsearch address string.

    Address format is typically: "Street Address, Suburb, STATE POSTCODE"
    """
    # Remove the state + postcode suffix
    cleaned = re.sub(rf",?\s*{re.escape(state)}\s*{re.escape(postcode)}\s*$", "", address).strip()
    # The suburb is the last comma-separated component
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    return parts[-1] if parts else ""
