"""
Streamlit web app for the Lotsearch PSI Extraction Engine.

Launch with: streamlit run app.py
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Lotsearch PSI Extraction Engine",
    page_icon="🔍",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Helper functions (must be defined before top-level Streamlit code calls them)
# ---------------------------------------------------------------------------


def _run_pipeline(pdf_path: Path, file_key: str) -> None:
    """Run the full extraction pipeline with progress updates."""
    from src.compose.docx_export import DocxExporter
    from src.compose.renderer import ReportRenderer
    from src.extract.dataset_listing import parse_dataset_listing
    from src.extract.table_extractor import extract_section
    from src.ingest.pdf_extractor import extract_pdf
    from src.ingest.section_splitter import split_sections
    from src.ingest.state_detector import detect_state
    from src.interpret.ai_interpreter import AIInterpreter
    from src.interpret.prompt_builder import PromptBuilder

    with st.status("Processing Lotsearch PDF...", expanded=True) as status:
        # Stage 1
        st.write("Extracting PDF content...")
        pdf_content = extract_pdf(pdf_path)

        # Stage 2
        st.write("Detecting state and site details...")
        state_id = detect_state(pdf_content.pages[0].text)

        # Stage 3
        st.write("Splitting into dataset sections...")
        sections = split_sections(pdf_content, pdf_path=pdf_path)

        # Stage 4
        st.write("Parsing dataset listing...")
        listing = parse_dataset_listing(pdf_content)

        # Stage 5
        st.write("Extracting section data...")
        listing_lookup = {e.dataset_name: e for e in listing}
        extracted_sections = []
        for sec in sections:
            entry = listing_lookup.get(sec.heading)
            extracted = extract_section(sec, listing_entry=entry)
            extracted_sections.append(extracted)

        # Stage 6
        st.write("Interpreting data (this may take 30-60 seconds)...")
        builder = PromptBuilder()
        listing_summary = PromptBuilder.summarise_listing(listing)
        interpreter = AIInterpreter(prompt_builder=builder)

        from src.cli import _map_sections_to_templates
        sections_by_template = _map_sections_to_templates(
            extracted_sections, state_id.state
        )

        interpreted = interpreter.interpret_all(
            sections_by_template=sections_by_template,
            state=state_id.state,
            site_address=state_id.address,
            lotsearch_reference=state_id.lotsearch_reference,
            dataset_listing_summary=listing_summary,
        )

        # Stage 7
        st.write("Composing report...")
        renderer = ReportRenderer()
        markdown = renderer.render(
            state=state_id.state,
            sections=interpreted,
            state_id=state_id,
        )

        # Stage 8
        st.write("Generating Word document...")
        docx_buffer = BytesIO()
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_docx:
            exporter = DocxExporter()
            exporter.export(markdown, tmp_docx.name)
            docx_buffer.write(Path(tmp_docx.name).read_bytes())
            Path(tmp_docx.name).unlink(missing_ok=True)
        docx_buffer.seek(0)

        status.update(label="Processing complete!", state="complete")

    # Store results in session state
    hits = [e for e in listing if e.has_hits]
    conf_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    review_flags = []
    for s in interpreted:
        c = s.confidence.upper()
        if c in conf_counts:
            conf_counts[c] += 1
        review_flags.extend(s.review_flags)

    date_str = datetime.now().strftime("%Y%m%d")
    suburb_clean = state_id.suburb.replace(" ", "_")
    base_name = f"PSI_Sections_{state_id.state}_{suburb_clean}_{date_str}"

    st.session_state["processed_file"] = file_key
    st.session_state["state_id"] = state_id
    st.session_state["listing"] = listing
    st.session_state["hits_count"] = len(hits)
    st.session_state["interpreted"] = interpreted
    st.session_state["markdown"] = markdown
    st.session_state["docx_bytes"] = docx_buffer.getvalue()
    st.session_state["conf_counts"] = conf_counts
    st.session_state["review_flags"] = review_flags
    st.session_state["base_name"] = base_name
    st.session_state["prompt_log"] = [p.model_dump() for p in interpreter.prompt_log]


def _display_results() -> None:
    """Display pipeline results from session state."""
    state_id = st.session_state["state_id"]
    listing = st.session_state["listing"]
    hits_count = st.session_state["hits_count"]
    interpreted = st.session_state["interpreted"]
    markdown = st.session_state["markdown"]
    docx_bytes = st.session_state["docx_bytes"]
    conf_counts = st.session_state["conf_counts"]
    review_flags = st.session_state["review_flags"]
    base_name = st.session_state["base_name"]

    st.divider()

    # Info box
    st.info(
        f"**{state_id.state}** — {state_id.address}  \n"
        f"Lotsearch Reference: {state_id.lotsearch_reference}"
    )

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datasets Found", len(listing))
    col2.metric("Datasets with Hits", hits_count)
    col3.metric("Sections Generated", len(interpreted))
    col4.metric("Review Flags", len(review_flags))

    # Confidence summary
    st.subheader("Confidence Summary")
    cc1, cc2, cc3 = st.columns(3)
    cc1.markdown(
        f'<span class="badge-high">HIGH</span> {conf_counts["HIGH"]} sections',
        unsafe_allow_html=True,
    )
    cc2.markdown(
        f'<span class="badge-medium">MEDIUM</span> {conf_counts["MEDIUM"]} sections',
        unsafe_allow_html=True,
    )
    cc3.markdown(
        f'<span class="badge-low">LOW</span> {conf_counts["LOW"]} sections',
        unsafe_allow_html=True,
    )

    if review_flags:
        with st.expander("Review Flags", expanded=False):
            for flag in review_flags:
                st.warning(flag)

    st.divider()

    # Report preview
    st.subheader("Report Preview")

    # Split markdown by section headings for expandable sections
    lines = markdown.split("\n")
    current_section = ""
    current_content: list[str] = []
    section_map: list[tuple[str, str]] = []

    for line in lines:
        if line.startswith("## "):
            if current_section and current_content:
                section_map.append((current_section, "\n".join(current_content)))
            current_section = line.lstrip("# ").strip()
            current_content = []
        else:
            current_content.append(line)

    if current_section and current_content:
        section_map.append((current_section, "\n".join(current_content)))

    for title, content in section_map:
        with st.expander(title, expanded=False):
            st.markdown(content)

    st.divider()

    # Download buttons
    st.subheader("Download")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="Download Markdown",
            data=markdown.encode("utf-8"),
            file_name=f"{base_name}.md",
            mime="text/markdown",
        )
    with dl2:
        st.download_button(
            label="Download Word Document",
            data=docx_bytes,
            file_name=f"{base_name}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    # Debug section
    with st.expander("Debug: Extraction Log", expanded=False):
        prompt_log = st.session_state.get("prompt_log", [])
        st.json(prompt_log)


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

# Custom CSS for confidence badges
st.markdown("""
<style>
.badge-high { background-color: #28a745; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
.badge-medium { background-color: #fd7e14; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
.badge-low { background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
</style>
""", unsafe_allow_html=True)

st.title("Lotsearch PSI Extraction Engine")
st.markdown("Upload a Lotsearch Enviro Professional PDF to generate draft PSI report sections.")

# Check for API key
api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key:
    st.error(
        "**ANTHROPIC_API_KEY not set.** "
        "Create a `.env` file in the project root with:\n\n"
        "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n\n"
        "Then restart the app."
    )
    st.stop()

# File uploader
uploaded_file = st.file_uploader(
    "Drop Lotsearch PDF here or click to browse",
    type=["pdf"],
    help="Accepts Lotsearch Enviro Professional PDF reports (VIC or NSW).",
)

if uploaded_file is not None:
    # Use session state to avoid re-processing
    file_key = f"{uploaded_file.name}_{uploaded_file.size}"

    if st.session_state.get("processed_file") != file_key:
        # Save uploaded PDF to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = Path(tmp.name)

        try:
            _run_pipeline(tmp_path, file_key)
        except Exception as e:
            st.error(
                f"**Processing failed:** {e}\n\n"
                "This may not be a valid Lotsearch Enviro Professional report, "
                "or the PDF format may not be supported."
            )
            st.stop()
        finally:
            tmp_path.unlink(missing_ok=True)

    # Display results from session state
    _display_results()
