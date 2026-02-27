# Lotsearch PSI Extraction Engine — Build Specification v2.0

## Document Status

| Field | Detail |
|-------|--------|
| Version | 2.1 |
| Date | 27 February 2026 |
| Status | Confirmed — ready for Claude Code implementation |
| Supersedes | `Lotsearch_Engine_Technical_Build_Specification.md` v1.0 |
| Companion | `Lotsearch_PSI_Extraction_Engine_Methodology.md` (interpretation rules, dataset mappings) |

### Key Changes from v1.0

- Architecture shifted from deterministic-rule-heavy to AI-interpretation-heavy
- Node.js/docx-js replaced with python-docx (all-Python stack)
- 40+ bespoke dataset parsers replaced with generic table extraction + Claude API interpretation
- All seven open assumptions (Methodology Section 9) resolved
- Two new VIC training pairs incorporated (Drysdale, Cobden)
- Discussion/Conclusions sections removed from engine scope
- Previous Environmental Investigations section removed from engine scope
- **Primary interface: Streamlit web app** (drag-and-drop PDF upload, visual progress, section-by-section output, download buttons). CLI retained as secondary interface for automation/batch processing.
- Designed for local use now, with clean separation for future web deployment (Streamlit Cloud or FastAPI migration)

---

## 1. Architecture Overview

### 1.1 Design Philosophy

The engine uses a **generic extraction + AI interpretation** pattern. Rather than writing bespoke parsers for every Lotsearch dataset format, we extract tables generically using pdfplumber and pass structured data to Claude API with carefully crafted prompts containing interpretation rules and training examples.

This design choice is driven by three factors:

1. **Lotsearch reports contain 45+ dataset types** with varying table structures. Bespoke parsers for each would require weeks of development and break when Lotsearch changes column headers or layouts.
2. **The interpretation rules are easier to express in natural language** (prompt templates) than in Python conditional logic, especially for nuanced assessments like Environmental Audit summaries and hydraulic gradient inferences.
3. **Claude Code can build and test the AI-interpretation approach faster** than a deterministic parser army, and the resulting codebase is smaller and more maintainable.

The deterministic layer is thin and focused on three tasks: state detection, dataset listing table parsing (this table has a highly consistent format), and output validation.

### 1.2 Pipeline Architecture

```
PDF Input
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  INGEST LAYER                                            │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ PDF Reader   │→ │ State Detect │→ │ Section Splitter│ │
│  │ (pdfplumber) │  │ (VIC/NSW)    │  │ (by heading)    │ │
│  └─────────────┘  └──────────────┘  └─────────────────┘ │
└──────────────────────┬───────────────────────────────────┘
                       │ Raw text + tables, tagged by section
                       ▼
┌──────────────────────────────────────────────────────────┐
│  EXTRACT LAYER                                           │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │ Dataset Listing   │  │ Generic Table Extractor      │  │
│  │ Table Parser      │  │ (all other sections)         │  │
│  │ (bespoke)         │  │                              │  │
│  └──────────────────┘  └──────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────┘
                       │ Structured section data (dicts/Pydantic)
                       ▼
┌──────────────────────────────────────────────────────────┐
│  INTERPRET LAYER (Claude API — primary interpreter)      │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │ AI Interpreter    │  │ Output Validator             │  │
│  │ (prompt per       │  │ (address check, tag check,   │  │
│  │  section type)    │  │  confidence flags)           │  │
│  └──────────────────┘  └──────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────┘
                       │ Draft prose sections + confidence tags
                       ▼
┌──────────────────────────────────────────────────────────┐
│  COMPOSE LAYER                                           │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │ Template Engine   │  │ Placeholder Generator        │  │
│  │ (Jinja2 assembly) │  │ (manual input markers)       │  │
│  └──────────────────┘  └──────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────┘
                       │ Complete Markdown report
                       ▼
┌──────────────────────────────────────────────────────────┐
│  EXPORT LAYER                                            │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │ Markdown Output   │  │ DOCX Generator               │  │
│  │ (.md file)        │  │ (python-docx)                │  │
│  └──────────────────┘  └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 1.3 API Call Budget

Each report run makes approximately 15–30 Claude API calls (Sonnet):

| Section Group | Estimated Calls | Notes |
|---------------|----------------|-------|
| Environmental Setting (topography, geology, hydrogeology, surface water) | 3–4 | One call per subsection |
| Groundwater bore data processing | 1–2 | Table extraction + prose |
| Regulatory databases (EPA registers, PFAS, waste, mining, defence) | 6–12 | One call per register group; nil results can be batched |
| Historical business directories | 1–2 | On-site + nearby assessment |
| Environmental Audit review (VIC only, if hits present) | 1–3 | One per reviewed audit |
| Summary of Site History table | 1 | Lotsearch-derived rows only |
| References list | 1 | State-appropriate references |

Estimated cost per report: $0.10–$0.30 AUD at current Sonnet pricing.

---

## 2. Resolved Design Decisions

All open assumptions from Methodology Section 9 have been confirmed:

| # | Decision | Resolution |
|---|----------|------------|
| 1 | Aerial photo interpretation | **Future module.** Engine generates a placeholder table structure designed to accept AI-generated observations from a future Module 4. Template includes column headers (Year, Image placeholder, Onsite observations, Offsite observations) with `<!-- MODULE_4_INPUT -->` markers. |
| 2 | Environmental Audit review (VIC) | **AI-generated draft summary, flagged REVIEW.** For each audit within 500m (closest 3), Claude API generates a summary from extracted CARMS data (audit category, address, date, conditions). All audit summaries carry `<!-- CONFIDENCE: LOW — REVIEW REQUIRED -->` tags. Area-match audits (e.g. Wannon Water sewerage) are identified and dismissed with standard language. |
| 3 | Section numbering | **Fixed default scheme.** Section 3 = Environmental Setting, Section 4 = Desktop Site History Review. Subsections numbered sequentially within each. User adjusts manually during final formatting if needed. |
| 4 | Summary of Site History table | **Lotsearch-derived rows generated; placeholders for non-Lotsearch rows.** Table includes rows for: business directories, regulatory registers, mining, waste. Placeholder rows for: aerial photographs, certificates of title, site inspection, previous investigations. |
| 5 | Discussion and Conclusions | **Not generated by engine.** These sections require synthesis across Lotsearch data, fieldwork results, and professional judgement. Engine scope ends at Section 4 + Environmental Setting. |
| 6 | Bore summary table format | **State-specific.** VIC: total bore count within 2km + closest bore narrative paragraph. NSW: 5-bore summary table (bore ID, distance/direction, purpose, depth, SWL, TDS, yield) + closest bore narrative. |
| 7 | State expansion | **VIC and NSW only.** No extensibility overhead for other states. State routing is a simple if/else, not a plugin architecture. |

### Additional Decisions

| Decision | Resolution |
|----------|------------|
| Previous Environmental Investigations section | **Skipped entirely.** This data comes from consultant knowledge, not Lotsearch. No placeholder generated. |
| Claude API model | **Claude Sonnet** (claude-sonnet-4-20250514) for all interpretation calls. |
| Docx export | **python-docx** (all-Python stack). No Node.js dependency. |
| Interactive review step | **Removed.** Engine runs fully automated: PDF in → Markdown + optional docx out. Confidence tags embedded in output for offline review. |
| Primary interface | **Streamlit web app.** Drag-and-drop PDF upload, visual progress, section-by-section preview with confidence highlighting, download buttons. CLI retained as secondary interface for batch/automation use. |
| Deployment | **Local machine for now.** Architecture designed for future web deployment via Streamlit Cloud or migration to FastAPI + hosted frontend. |

---

## 3. Technology Stack

### 3.1 Dependencies

```toml
[project]
name = "lotsearch-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pdfplumber>=0.11.0",
    "pydantic>=2.5.0",
    "jinja2>=3.1.0",
    "click>=8.1.0",
    "anthropic>=0.40.0",
    "python-docx>=1.1.0",
    "rich>=13.0.0",
    "python-dateutil>=2.8.0",
    "streamlit>=1.39.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "ruff>=0.1.0",
]

[project.scripts]
lotsearch = "src.cli:main"
```

### 3.2 System Requirements

- Python 3.11+
- No other system dependencies (pdfplumber bundles its own PDF parser; no poppler required)

### 3.3 Environment Variable

```
ANTHROPIC_API_KEY=sk-ant-...
```

Required for AI interpretation layer. Engine exits with a clear error message if not set.

---

## 4. File Structure

```
lotsearch-engine/
├── README.md
├── pyproject.toml
├── .env.example                   # ANTHROPIC_API_KEY placeholder
├── app.py                         # Streamlit web app (primary interface)
├── src/
│   ├── __init__.py
│   ├── cli.py                     # Click CLI entry point
│   │
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── pdf_extractor.py       # pdfplumber: full PDF → pages, text, tables
│   │   ├── state_detector.py      # Parse page 1 for state, address, LS reference
│   │   └── section_splitter.py    # Split PDF content into dataset sections by heading
│   │
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── dataset_listing.py     # Bespoke parser for master dataset listing table
│   │   └── table_extractor.py     # Generic: extract any dataset section's tables + text
│   │
│   ├── interpret/
│   │   ├── __init__.py
│   │   ├── ai_interpreter.py      # Claude API orchestrator (batching, retries, caching)
│   │   ├── prompt_builder.py      # Build prompts from templates + extracted data
│   │   └── validator.py           # Validate AI output (address, tags, structure)
│   │
│   ├── compose/
│   │   ├── __init__.py
│   │   ├── renderer.py            # Jinja2: assemble interpreted sections into full Markdown
│   │   └── docx_export.py         # python-docx: Markdown → formatted .docx
│   │
│   ├── prompts/
│   │   ├── system_base.txt        # Base system prompt (role, tone, constraints)
│   │   ├── vic/
│   │   │   ├── env_setting.txt    # Topography, geology, hydrogeology, surface water
│   │   │   ├── groundwater_bores.txt
│   │   │   ├── epa_registers.txt  # Priority Sites, Remedial Notices, Permissions, Licences
│   │   │   ├── env_audits.txt     # CARMS review with training examples
│   │   │   ├── gqruz.txt
│   │   │   ├── business_dirs.txt
│   │   │   ├── waste_liquid_fuel.txt
│   │   │   ├── pfas.txt
│   │   │   ├── mining_fire.txt
│   │   │   ├── defence.txt
│   │   │   └── site_history_table.txt
│   │   └── nsw/
│   │       ├── env_setting.txt
│   │       ├── groundwater_bores.txt
│   │       ├── epa_registers.txt  # CLM Act sites, Records of Notice
│   │       ├── poeo_licences.txt  # Current, delicensed, former — with area/network assessment
│   │       ├── business_dirs.txt
│   │       ├── waste_liquid_fuel.txt
│   │       ├── pfas.txt
│   │       ├── mining.txt
│   │       ├── defence.txt
│   │       └── site_history_table.txt
│   │
│   ├── templates/
│   │   ├── vic/
│   │   │   ├── section_3_env_setting.md.j2
│   │   │   ├── section_4_desktop_review.md.j2
│   │   │   └── references.md.j2
│   │   └── nsw/
│   │       ├── section_3_env_setting.md.j2
│   │       ├── section_4_desktop_review.md.j2
│   │       └── references.md.j2
│   │
│   └── schemas/
│       ├── __init__.py
│       ├── common.py              # StateIdentification, DatasetListingEntry, SectionData
│       └── dataset_listing.py     # Master table schema
│
├── training_data/
│   ├── vic/
│   │   ├── LS089658_EP_brunswick_west.pdf
│   │   ├── AE25045_brunswick_west_psi.md
│   │   ├── Lotsearch_drysdale.pdf
│   │   ├── AE25048_drysdale_psi.md
│   │   ├── LS115592_EP_cobden.pdf
│   │   └── AE26058_cobden_psi.md
│   └── nsw/
│       ├── LS121125_EP_barooga.pdf
│       └── AE26059_barooga_psi.md
│
├── tests/
│   ├── test_ingest.py
│   ├── test_extract.py
│   ├── test_interpret.py
│   ├── test_compose.py
│   └── test_integration.py
│
└── output/                        # Default output directory (gitignored)
```

---

## 5. Module Specifications

### 5.1 Module: `src/ingest/pdf_extractor.py`

**Purpose:** Accept a Lotsearch PDF and extract all content using pdfplumber.

```python
from pydantic import BaseModel

class PageContent(BaseModel):
    page_number: int
    text: str                           # Full text of the page
    tables: list[list[list[str]]]       # List of tables, each table is list of rows, each row is list of cells
    has_map: bool                       # True if page appears to be primarily a map (low text density)

class PDFContent(BaseModel):
    pages: list[PageContent]
    full_text: str                      # Concatenated text of all pages
    metadata: dict                      # PDF metadata if available

class PDFExtractor:
    """Extract all text and table content from a Lotsearch PDF.

    Uses pdfplumber for table detection. For pages where table detection
    fails (common on map pages), falls back to raw text extraction.

    Key implementation notes:
    - pdfplumber.open(pdf_path) → iterate pages
    - page.extract_tables() for structured tables
    - page.extract_text() for raw text
    - Map pages identified by: low character count relative to page area,
      or presence of "Legend" / "Scale:" / "Coordinate System" text patterns
    - Table extraction settings: vertical_strategy="lines", horizontal_strategy="lines"
      with fallback to "text" strategy if lines-based extraction returns empty
    """

    def extract(self, pdf_path: Path) -> PDFContent:
        ...
```

### 5.2 Module: `src/ingest/state_detector.py`

**Purpose:** Parse page 1 to identify state, site address, and Lotsearch reference number.

```python
class StateIdentification(BaseModel):
    state: str                          # "VIC" or "NSW"
    address: str                        # Full site address as printed on page 1
    suburb: str                         # Extracted suburb name
    postcode: str                       # Extracted postcode
    lotsearch_reference: str            # LS###### EP format
    report_date: str | None             # Date if parseable from page 1

class StateDetector:
    """Detect state from page 1 address line.

    Detection method (priority order):
    1. Regex for state abbreviation in address: r'(VIC|NSW)\s+\d{4}'
    2. Postcode range: 3000-3999 = VIC, 2000-2999 = NSW
    3. Custodian names in dataset listing table (fallback)

    Also extracts:
    - Full address via regex: everything before the state abbreviation on the address line
    - LS reference via regex: r'LS\d{6}\s*EP'
    - Report date if present on page 1
    """

    def detect(self, pdf_content: PDFContent) -> StateIdentification:
        ...
```

### 5.3 Module: `src/ingest/section_splitter.py`

**Purpose:** Split the PDF content into individual dataset sections, identified by section headings.

```python
class SectionContent(BaseModel):
    heading: str                        # Section heading text (e.g. "EPA Environmental Audit Reports")
    page_range: tuple[int, int]         # Start and end page numbers
    text: str                           # Raw text content of the section
    tables: list[list[list[str]]]       # All tables within this section
    is_map_section: bool                # True if section is primarily a map page

class SectionSplitter:
    """Split PDF content into sections by detecting heading patterns.

    Lotsearch reports use a consistent heading style:
    - Blue bold text (detectable via pdfplumber char-level extraction)
    - OR identifiable by matching known dataset names from the dataset listing table

    The splitter uses the dataset listing table as an index:
    1. Parse dataset names from the listing table
    2. Search for each dataset name in the full text to find its section start
    3. Each section runs from its heading to the next section's heading

    Special handling:
    - Map pages (one per dataset with hits) precede data tables
    - Some sections span multiple pages (bore data, business directories)
    - Dataset listing table itself is treated as its own section (pages 1-3 typically)
    """

    def split(self, pdf_content: PDFContent, dataset_names: list[str]) -> list[SectionContent]:
        ...
```

### 5.4 Module: `src/extract/dataset_listing.py`

**Purpose:** Bespoke parser for the master dataset listing table. This table has a consistent format across all Lotsearch reports and is the index for the entire PDF.

```python
class DatasetListingEntry(BaseModel):
    dataset_name: str                   # Full dataset name (may wrap across lines)
    custodian: str                      # Data custodian organisation
    supply_date: str | None             # Date data was supplied to Lotsearch
    currency_date: str | None           # Date of data currency
    update_frequency: str | None        # How often the dataset is updated
    buffer_m: int | None                # Search buffer in metres (500, 1000, 2000, 10000)
    count_onsite: int | None            # Count of features on-site (None if "-")
    count_within_100m: int | None       # Count within 100m (None if "-")
    count_within_buffer: int | None     # Count within buffer (None if "-")
    has_hits: bool                      # True if any count > 0

class DatasetListingParser:
    """Parse the master dataset listing table from pages 1-3.

    This is the ONE bespoke parser in the system. The dataset listing table
    has a highly consistent format across all Lotsearch reports:
    - Column headers: Dataset Name | Custodian | Supply Date | Currency Date |
      Update Frequency | Dataset Buffer (m) | No. Features On-site |
      No. Features within 100m | No. Features within Buffer
    - Located on pages 1-3 (sometimes extending to page 4)
    - Dataset names often wrap across multiple lines within a cell

    Critical extraction rules:
    - Distinguish "-" (not applicable) from "0" (searched, nil result)
    - Reconstruct dataset names that wrap across cell lines
    - Handle merged cells for custodian column
    - Buffer distances vary: 500m, 1000m, 2000m, 10000m
    """

    def parse(self, pages: list[PageContent]) -> list[DatasetListingEntry]:
        ...
```

### 5.5 Module: `src/extract/table_extractor.py`

**Purpose:** Generic extraction of any dataset section's content into a structured dict suitable for AI interpretation.

```python
class ExtractedSection(BaseModel):
    dataset_name: str                   # From dataset listing
    heading: str                        # Section heading as found in PDF
    raw_text: str                       # All text in the section
    tables: list[dict]                  # Tables converted to list-of-dicts with headers as keys
    table_headers: list[list[str]]      # Raw header rows for each table
    hit_counts: dict                    # From dataset listing: onsite, within_100m, within_buffer
    custodian: str                      # Data source attribution

class GenericTableExtractor:
    """Extract structured data from any dataset section.

    Unlike the bespoke dataset listing parser, this extractor does NOT
    need to understand the specific schema of each dataset. It extracts:

    1. Raw text content of the section
    2. Any tables present, with the first row treated as headers
    3. Hit counts from the dataset listing (passed in)
    4. Custodian information

    The AI interpretation layer receives this structured-but-generic data
    and applies dataset-specific interpretation rules via prompts.

    Table-to-dict conversion:
    - First row of each table → keys
    - Subsequent rows → values
    - Handle tables with merged header cells
    - Handle "No records in buffer" rows (single cell spanning all columns)
    - Preserve all cell text including multi-line content
    """

    def extract(self, section: SectionContent, listing_entry: DatasetListingEntry) -> ExtractedSection:
        ...
```

### 5.6 Module: `src/interpret/ai_interpreter.py`

**Purpose:** Orchestrate Claude API calls for interpretation of extracted data into report prose.

```python
class InterpretedSection(BaseModel):
    section_id: str                     # e.g. "3.1_topography", "4.3_epa_registers"
    prose: str                          # Generated report prose (Markdown)
    confidence: str                     # "HIGH", "MEDIUM", or "LOW"
    review_flags: list[str]             # Specific items requiring professional review
    tables_markdown: list[str]          # Any tables to embed (as Markdown table syntax)

class AIInterpreter:
    """Orchestrate Claude API calls for data interpretation.

    Each interpretation call sends:
    1. System prompt: base role + state-specific interpretation rules
    2. User prompt: extracted section data + specific instructions

    Prompt templates are loaded from src/prompts/{state}/*.txt

    Key design principles:
    - ONE API call per logical section (not per dataset)
    - Related datasets batched into single calls where sensible
      (e.g. all PFAS programs in one call, all waste databases in one call)
    - Each call returns structured Markdown prose matching the report tone
    - Confidence tags embedded by the AI based on prompt instructions
    - Review flags returned as a separate list for summary reporting

    Batching strategy:
    - Environmental Setting: 3-4 calls (topography+geology, hydrogeology, bores, surface water)
    - EPA registers: 1-2 calls (nil registers batched, hits processed individually)
    - Environmental Audits (VIC): 1 call per reviewed audit (closest 3 within 500m)
    - PFAS programs: 1 call (all programs batched)
    - Waste + liquid fuel: 1 call
    - Business directories: 1-2 calls
    - Mining + fire + defence: 1 call (usually all nil)
    - Summary table: 1 call

    Error handling:
    - Retry on API errors (3 attempts with exponential backoff)
    - If API unavailable, write raw extracted data with EXTRACTION_ONLY tag
    - Log all prompts and responses for debugging
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        ...

    def interpret_section(self, section_data: ExtractedSection, state: str,
                          site_address: str, prompt_template: str) -> InterpretedSection:
        ...

    def interpret_all(self, sections: list[ExtractedSection], state: str,
                      site_address: str) -> list[InterpretedSection]:
        ...
```

### 5.7 Module: `src/interpret/prompt_builder.py`

**Purpose:** Construct prompts from templates and extracted data.

```python
class PromptBuilder:
    """Build interpretation prompts from templates + data.

    Each prompt template (in src/prompts/{state}/*.txt) contains:
    - Role and context instructions
    - State-specific interpretation rules (from the methodology)
    - Output format requirements (Markdown, confidence tags, tone)
    - One or more training examples showing input data → expected output prose

    The builder inserts:
    - The extracted section data (tables, text, hit counts)
    - The site address
    - The state
    - Any cross-section context needed (e.g. groundwater flow direction
      is needed for off-site risk assessments in regulatory sections)

    Template variables:
    - {{ site_address }} — full site address
    - {{ state }} — "VIC" or "NSW"
    - {{ section_data }} — JSON-serialised extracted section data
    - {{ dataset_listing_summary }} — summary of all datasets with hit counts
    - {{ groundwater_context }} — flow direction, depth, TDS (from env setting extraction)
    - {{ training_example_input }} — example input data
    - {{ training_example_output }} — example output prose
    """

    def __init__(self, prompts_dir: Path):
        ...

    def build(self, template_name: str, state: str, site_address: str,
              section_data: ExtractedSection, context: dict | None = None) -> tuple[str, str]:
        """Returns (system_prompt, user_prompt)."""
        ...
```

### 5.8 Module: `src/interpret/validator.py`

**Purpose:** Validate AI-generated output before inclusion in the report.

```python
class ValidationResult(BaseModel):
    valid: bool
    issues: list[str]                   # Description of any issues found

class OutputValidator:
    """Validate AI-generated prose for correctness.

    Checks performed:
    1. Site address consistency — the generated prose must reference the correct
       site address (not a training example address)
    2. State consistency — VIC prose must not contain NSW regulatory references
       and vice versa (e.g. "CLM Act" in a VIC report, "PPN30" in an NSW report)
    3. Confidence tag presence — every output must contain at least one
       <!-- CONFIDENCE: ... --> tag
    4. Nil result consistency — if the dataset listing shows zero hits,
       the prose must not describe specific records
    5. Distance consistency — distances mentioned in prose should be plausible
       given the buffer distance for that dataset
    6. No hallucinated data — check that specific identifiers mentioned in prose
       (CARMS numbers, bore IDs, licence numbers) appear in the extracted data

    If validation fails, the section is re-prompted with the specific issues
    noted, up to 2 retries. After that, the raw extracted data is output with
    a VALIDATION_FAILED tag.
    """

    def validate(self, interpreted: InterpretedSection, extracted: ExtractedSection,
                 state: str, site_address: str) -> ValidationResult:
        ...
```

### 5.9 Module: `src/compose/renderer.py`

**Purpose:** Assemble interpreted sections into a complete report Markdown file using Jinja2 templates.

```python
class ReportRenderer:
    """Assemble interpreted sections into complete Markdown report.

    Uses Jinja2 templates that define the overall report structure:
    - Section ordering and numbering (fixed default scheme)
    - Placeholder insertion for non-Lotsearch sections
    - Confidence summary at the top of the output

    The renderer does NOT generate Discussion, Conclusions, or
    Previous Environmental Investigations sections.

    Output structure:
    1. Report header (site address, LS reference, generation date)
    2. Confidence summary (count of HIGH/MEDIUM/LOW items, list of REVIEW flags)
    3. Section 3: Environmental Setting
       3.1 Topography
       3.2 Regional Geology
       3.3 Regional Hydrogeology
       3.3.1 Groundwater Utilisation
       3.4 Surface Water Hydrology
    4. Section 4: Desktop Site History Review
       4.1 Historical Business Directory Records
       4.2 Historical Aerial Photographs <!-- placeholder for Module 4 -->
       4.3 EPA Registers (state-specific subsections)
       4.4 PFAS Investigations
       4.5 Waste Management and Liquid Fuel Facilities
       4.6 Historical Mining Activities
       4.7 Natural Hazards (VIC only)
       4.8 Defence Sites
       4.9 Summary of Site History (table with placeholders)
    5. References

    Placeholder markers:
    <!-- MANUAL_INPUT: [description] -->
    <!-- MODULE_4_INPUT: [description] -->
    <!-- SHAREPOINT_INPUT: [description] -->
    """

    def __init__(self, templates_dir: Path):
        ...

    def render(self, state: str, sections: list[InterpretedSection],
               state_id: StateIdentification) -> str:
        ...
```

### 5.10 Module: `src/compose/docx_export.py`

**Purpose:** Convert Markdown report to formatted Word document using python-docx.

```python
class DocxExporter:
    """Convert Markdown report to formatted .docx using python-docx.

    Formatting specification (matches existing PSI report style):
    - Font: Arial throughout
    - Body text: 11pt, single spacing, 6pt after paragraph
    - Heading 1: 14pt bold (Section 3, Section 4)
    - Heading 2: 12pt bold (3.1 Topography, 4.1 Business Directories, etc.)
    - Heading 3: 11pt bold (3.3.1 Groundwater Utilisation, etc.)
    - Tables: bordered (thin grey), header row shaded light blue, 10pt text
    - Page size: A4
    - Margins: 2.54cm all sides (standard)
    - Bullet lists: 0.63cm indent, hanging 0.32cm

    Markdown parsing:
    - # → Heading 1, ## → Heading 2, ### → Heading 3
    - **bold** → bold run
    - *italic* → italic run
    - | table | → Table with borders
    - - item → Bullet list
    - <!-- comments --> → Stripped from docx output (confidence tags, placeholders
      are for Markdown review only; they do not appear in the Word document)

    The docx is a DRAFT output — it will need manual formatting adjustments
    (page breaks, table widths, appendix references) before client delivery.
    """

    def export(self, markdown_text: str, output_path: Path) -> None:
        ...
```

### 5.11 Module: `app.py` (Streamlit Web App — Primary Interface)

**Purpose:** Drag-and-drop browser interface for processing Lotsearch PDFs.

```python
"""
Streamlit web app for the Lotsearch PSI Extraction Engine.

Launch with: streamlit run app.py

User workflow:
1. Open browser (auto-launches to localhost:8501)
2. Drag and drop a Lotsearch PDF onto the upload area
3. Watch the progress bar as each pipeline stage completes
4. Review generated sections in the browser, with confidence flags
   highlighted visually (green = HIGH, amber = MEDIUM, red = REVIEW)
5. Click download buttons for Markdown and/or docx output

UI Layout:
┌──────────────────────────────────────────────────┐
│  LOTSEARCH PSI EXTRACTION ENGINE                 │
│  ─────────────────────────────────────────────── │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  Drop Lotsearch PDF here or click to     │    │
│  │  browse                                  │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░  Stage 3/6: Interpret  │
│                                                  │
│  ┌─ Report Preview ──────────────────────────┐   │
│  │  📋 Detected: VIC — 151 Melville Rd       │   │
│  │  📊 Datasets: 47 found, 12 with hits      │   │
│  │                                           │   │
│  │  ▸ Section 3: Environmental Setting  ✅   │   │
│  │  ▸ Section 4: Desktop Review         ⚠️   │   │
│  │    (3 items flagged for review)           │   │
│  │  ▸ References                        ✅   │   │
│  └───────────────────────────────────────────┘   │
│                                                  │
│  [📥 Download Markdown]  [📥 Download Word]      │
└──────────────────────────────────────────────────┘

Key features:
- st.file_uploader for PDF drag-and-drop
- st.progress + st.status for pipeline stages
- st.expander for section-by-section review
- st.markdown for rendered report preview
- st.download_button for output files
- Confidence flags rendered as coloured badges
- Extraction log available as expandable debug section

Streamlit session state stores:
- Uploaded PDF bytes
- Pipeline progress
- Generated sections (for re-rendering without re-processing)
- Download-ready file bytes (md and docx)

Future web deployment:
- Runs on Streamlit Cloud with minimal config changes
- Or migrate core engine to FastAPI + React for full custom UI
"""
```

### 5.12 Module: `src/cli.py` (CLI — Secondary Interface for Automation)

**Purpose:** CLI entry point for batch processing and automation. Secondary to the Streamlit app.

```python
@click.group()
def main():
    """Lotsearch PSI Extraction Engine"""
    pass

@main.command()
@click.argument('pdf_path', type=click.Path(exists=True, path_type=Path))
@click.option('--output-dir', '-o', type=click.Path(path_type=Path), default='./output')
@click.option('--format', '-f', type=click.Choice(['markdown', 'docx', 'both']), default='both')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed progress and extracted data')
def process(pdf_path: Path, output_dir: Path, format: str, verbose: bool):
    """Process a Lotsearch PDF and generate PSI report sections."""
    ...
```

CLI usage:

```bash
# Standard usage — process PDF, output both formats
lotsearch process path/to/LS121125_EP.pdf

# Specify output directory
lotsearch process path/to/LS121125_EP.pdf -o ./output/barooga/

# Markdown only (skip docx)
lotsearch process path/to/LS121125_EP.pdf -f markdown

# Verbose mode (shows extraction detail)
lotsearch process path/to/LS121125_EP.pdf -v
```

---

## 6. Prompt Design Specification

### 6.1 Base System Prompt

Every API call includes this system prompt:

```
You are an expert contaminated land consultant in Australia, producing
sections of a Preliminary Site Investigation (PSI) report. You are
processing data extracted from a Lotsearch Enviro Professional report
for the following site:

Site address: {{ site_address }}
State: {{ state }}
Lotsearch reference: {{ lotsearch_reference }}

Your output must:
1. Match the professional tone and register of a contaminated land
   consultant's report. Use qualifiers appropriately: "is considered",
   "is not expected to", "is unlikely to", "is not considered to
   represent a material contamination risk".
2. Always capitalise "Site" when referring to the subject site.
3. Include confidence tags as HTML comments:
   <!-- CONFIDENCE: HIGH --> for direct factual data
   <!-- CONFIDENCE: MEDIUM --> for standard interpretive statements
   <!-- CONFIDENCE: LOW — REVIEW REQUIRED --> for complex judgements
4. Output clean Markdown with proper heading levels.
5. Never fabricate data not present in the extracted content.
6. For nil results, use the standard statement format:
   "No [description] were identified at or within [buffer] of the Site."
```

### 6.2 Section-Specific Prompt Structure

Each section prompt follows this structure:

```
[BASE SYSTEM PROMPT]

## Interpretation Rules for This Section

[State-specific rules from the methodology — e.g. ERS classification
table for VIC hydrogeology, POEO area/network assessment for NSW]

## Training Example

Here is an example of extracted data and the expected output for a
similar site:

### Example Input:
[Extracted data from a training Lotsearch PDF]

### Example Output:
[Corresponding prose from the training PSI report]

## Your Task

Process the following extracted data and generate the report section.

### Extracted Data:
{{ section_data }}

### Additional Context:
{{ context }}
```

### 6.3 Prompt Templates to Build

| Prompt File | Datasets Covered | Training Example Source |
|-------------|-----------------|----------------------|
| `vic/env_setting.txt` | Geological units, hydrogeology map, watertable salinity/depth, soils, ASS, NOA, elevation | Brunswick West + Drysdale + Cobden |
| `vic/groundwater_bores.txt` | All VIC bore datasets (DELWP WMIS, Earth Resources, Federation Uni) | Brunswick West (count + closest) |
| `vic/epa_registers.txt` | Priority Sites, Site Management Orders, Former Priority Sites & Remedial Notices, Contaminated Land Notifications, Permissions, Legacy Licensed Activities, Legacy Works Approvals | Brunswick West + Drysdale + Cobden |
| `vic/env_audits.txt` | EPA Environmental Audits, PRSAs, GQRUZ | Brunswick West (3 audits reviewed) + Cobden (area-match dismissed) |
| `vic/business_dirs.txt` | All 4 business directory sub-datasets | Drysdale (on-site garage) + Brunswick West (on-site activities) |
| `vic/waste_liquid_fuel.txt` | National Waste Mgmt, State Waste, EPA Prescribed Waste, Landfill Register, Former Waste Disposal, Liquid Fuel | All VIC training sets |
| `vic/pfas.txt` | EPA PFAS, Defence PFAS (investigation + management), Airservices PFAS | All VIC training sets (all nil) |
| `vic/mining_fire.txt` | Historical Mining Shafts, Fire History | All VIC training sets |
| `vic/defence.txt` | Defence Controlled Areas, 3-Year Regional, UXO | All VIC training sets (all nil) |
| `vic/site_history_table.txt` | Summary table rows | Brunswick West + Drysdale |
| `nsw/env_setting.txt` | NSW Seamless Geology, hydrogeology map, soils, ASS, dryland salinity, elevation | Barooga |
| `nsw/groundwater_bores.txt` | NGIS bore datasets | Barooga (5-bore table) |
| `nsw/epa_registers.txt` | CLM Act contaminated sites, Records of Notice, POEO Act notices, Other Contamination Sites | Barooga |
| `nsw/poeo_licences.txt` | Current POEO, Delicensed POEO, Former POEO | Barooga (Murray Irrigation, herbicide licences) |
| `nsw/business_dirs.txt` | All business directory sub-datasets | Barooga |
| `nsw/waste_liquid_fuel.txt` | National Waste Mgmt, Liquid Fuel | Barooga (BP Barooga) |
| `nsw/pfas.txt` | All PFAS programs | Barooga (all nil) |
| `nsw/mining.txt` | Mining subsidence, current/historic titles, applications | Barooga (5 historic PELs) |
| `nsw/defence.txt` | Defence + UXO | Barooga (all nil) |
| `nsw/site_history_table.txt` | Summary table rows | Barooga |

---

## 7. Output Specification

### 7.1 Markdown Output

The primary output is a single Markdown file containing all engine-generated sections with embedded confidence tags and placeholder markers.

Sections generated by the engine:

**Section 3: Environmental Setting**
- 3.1 Topography
- 3.2 Regional Geology (including soils, ASS, NOA where relevant)
- 3.3 Regional Hydrogeology (including beneficial use classification)
- 3.3.1 Groundwater Utilisation (VIC: count + closest bore; NSW: 5-bore table)
- 3.4 Surface Water Hydrology

**Section 4: Desktop Site History Review**
- 4.1 Historical Business Directory Records
- 4.2 Historical Aerial Photographs `<!-- MODULE_4_INPUT: placeholder table -->`
- 4.3+ State-specific regulatory register subsections
- 4.x PFAS Investigations
- 4.x Waste Management and Liquid Fuel Facilities
- 4.x Historical Mining Activities
- 4.x Natural Hazards — Fire History (VIC only)
- 4.x Defence Sites
- 4.x Summary of Site History (Lotsearch rows + placeholder rows)

**References** (state-appropriate legislation and guidelines)

### 7.2 Sections NOT Generated

The engine does NOT generate:

- Section 1: Introduction (SharePoint/client data)
- Section 2: Site Information (SharePoint/client data + site inspection)
- Historical Aerial Photographs content (placeholder only — future Module 4)
- Certificates of Title review (separate data source)
- Site Inspection Observations (fieldwork)
- Previous Environmental Investigations (consultant knowledge)
- Discussion section (requires synthesis across all data sources)
- Conclusions section (requires synthesis across all data sources)
- SAQP, CSM, QA/QC (fieldwork)
- Appendices

### 7.3 Docx Output

The docx file mirrors the Markdown content with professional formatting. HTML comment tags (confidence markers, placeholders) are stripped from the docx — they exist only in the Markdown for review purposes.

### 7.4 Extraction Log

A JSON file (`extraction_log.json`) is written alongside the report containing:
- Full dataset listing table (parsed)
- All extracted section data (pre-interpretation)
- All AI prompts sent and responses received
- Validation results
- Processing timestamps and API call metadata

This log enables debugging, prompt iteration, and comparison against training data.

---

## 8. Training Data Summary

### 8.1 Available Training Sets

| # | State | Site | Lotsearch Ref | PSI Reference | Key Features |
|---|-------|------|--------------|---------------|-------------|
| 1 | VIC | 151 Melville Rd, Brunswick West | LS089658 EP | AE25045 | Urban, EAO overlay, adjacent former service station, 22 Environmental Audits within 1km (3 reviewed in detail), GQRUZ (3 zones), historical manufacturing, ERS Segment C groundwater, 253 bores within 2km |
| 2 | NSW | 58-62 Nangunia St, Barooga | LS121125 EP | AE26059 | Rural township, UPSS (60kL UST), Murray River floodplain, alluvial aquifer, 85 bores within 2km, 5 historical PELs (assessed as regional), POEO licences (Murray Irrigation area-match, herbicide surrendered licences), BP petrol station at 911m |
| 3 | VIC | 110-112 High St, Drysdale | (Batch C) | AE25048 | On-site motor garage/service station history (1980-1991), adjacent Priority Site (97 High St service station, 150m, cross-gradient), EPA Permissions (A23, A13c registrations), prescribed waste transport sites nearby, Acid Sulfate Soil subsection, previous environmental investigation review |
| 4 | VIC | Boundary Road, Cobden | LS115592 EP | AE26058 | Rural VIC site, Wannon Water area-match Environmental Audit (dismissed as regional sewerage system), Former EPA Priority Sites with remedial notices within 100m, Legacy EPA Licensed Activity (milk processing D07, 880m), Meinhardt LCA previous investigation, basalt/volcanic geology |

### 8.2 New Patterns from Training Sets 3 and 4

The following patterns were identified in the Drysdale and Cobden training data that extend the methodology:

1. **Area-match Environmental Audits** — The Cobden report demonstrates how to dismiss an audit that covers an entire regional infrastructure system (Wannon Water sewerage). The engine must detect area-match audits (location confidence = "Area Match") and apply dismissal language rather than detailed review.

2. **EPA Permissions categories** — Drysdale shows A23 (temporary storage of waste) and A13c (waste and resource recovery) permission types. The engine needs to report these with their registration type and distance.

3. **On-site motor garage history** — Drysdale has premise-matched motor garage records at 0m. The engine must distinguish premise matches (high confidence, on-site) from road matches (lower confidence, general area) in business directory interpretation.

4. **Adjacent Priority Site with cross-gradient assessment** — Drysdale's adjacent service station on the PSR at 150m with a cross-gradient hydraulic assessment represents a new interpretation pattern for proximal contamination sources that are not upgradient.

5. **Former EPA Priority Sites & Remedial Notices** — Cobden has entries within 100m on this register, which is a separate dataset from Current EPA Priority Sites. The engine must handle both registers independently.

6. **Acid Sulfate Soil subsection** — Drysdale includes a dedicated ASS subsection under Regional Geology. This should be generated as a subsection when the ASS dataset returns a non-nil probability.

7. **Legacy EPA Licensed Activity with specific premises** — Cobden shows a D07 operating licence for milk processing at a specific address (129 Curdie St, 880m NE). The engine should report the licence type, activity description, address, and distance.

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Test File | Coverage |
|-----------|----------|
| `test_ingest.py` | State detection (VIC address, NSW address, ambiguous), PDF extraction (text, tables), section splitting |
| `test_extract.py` | Dataset listing parser (VIC format, NSW format, wrapped names, dash vs zero), generic table extractor |
| `test_interpret.py` | Prompt builder (template loading, variable insertion), output validator (address check, state check, nil consistency) |
| `test_compose.py` | Jinja2 template rendering, docx export (headings, tables, formatting) |

### 9.2 Integration Tests

End-to-end tests using training data:

```python
def test_brunswick_west_full_pipeline():
    """Process Brunswick West Lotsearch and compare key outputs."""
    output = process_pipeline("training_data/vic/LS089658_EP.pdf")
    # Check state detection
    assert output.state == "VIC"
    # Check key content presence
    assert "Melbourne Formation" in output.sections["env_setting"]
    assert "Sxm" in output.sections["env_setting"] or "siltstone and sandstone" in output.sections["env_setting"]
    assert "Segment C" in output.sections["env_setting"]
    assert "253" in output.sections["env_setting"]  # bore count
    assert "WRK988467" in output.sections["env_setting"]  # closest bore
    assert "Monee Ponds Creek" in output.sections["env_setting"] or "Moonee Ponds Creek" in output.sections["env_setting"]

def test_barooga_full_pipeline():
    """Process Barooga Lotsearch and compare key outputs."""
    output = process_pipeline("training_data/nsw/LS121125_EP.pdf")
    assert output.state == "NSW"
    assert "GW503700" in output.sections["env_setting"]  # closest bore
    assert "Murray River" in output.sections["env_setting"]
    assert "Murray Irrigation" in output.sections["desktop_review"]
    assert "BP Barooga" in output.sections["desktop_review"] or "petrol station" in output.sections["desktop_review"].lower()
```

### 9.3 Prompt Regression Tests

When prompts are edited, re-run all training data through the pipeline and compare outputs to previous baseline. Key metrics:
- All factual data points present (bore IDs, distances, CARMS numbers)
- No state contamination (VIC references in NSW output)
- Confidence tags present on every section
- Review flags present on audit summaries

---

## 10. Build Sequence for Claude Code

The recommended implementation order, designed for incremental testing:

### Phase 1: Ingest Layer (test with all 4 training PDFs)
1. `pdf_extractor.py` — extract text and tables from PDF
2. `state_detector.py` — identify state, address, reference
3. `section_splitter.py` — split into dataset sections
4. **Test:** Run against all 4 training PDFs, verify correct state detection and section identification

### Phase 2: Extract Layer (test with dataset listing tables)
5. `dataset_listing.py` — parse master table
6. `table_extractor.py` — generic table extraction
7. **Test:** Verify dataset listing counts match manual inspection; verify table extraction captures all data

### Phase 3: Interpret Layer (test with one VIC + one NSW site)
8. `prompt_builder.py` — template loading and variable insertion
9. Write initial prompt templates (start with `vic/env_setting.txt` and `nsw/env_setting.txt`)
10. `ai_interpreter.py` — single-section interpretation
11. `validator.py` — output validation
12. **Test:** Generate Environmental Setting section for Brunswick West and Barooga; compare to training PSI reports

### Phase 4: Full Interpretation (all prompt templates)
13. Write remaining VIC prompt templates
14. Write remaining NSW prompt templates
15. Wire up `interpret_all()` to process all sections
16. **Test:** Full pipeline for all 4 training sites; review all sections against training PSI reports

### Phase 5: Interface + Export Layer
17. `renderer.py` — Jinja2 assembly with placeholders
18. `docx_export.py` — python-docx conversion
19. `cli.py` — CLI entry point (secondary interface)
20. `app.py` — Streamlit web app (primary interface)
21. **Test:** End-to-end: upload PDF via Streamlit, review output in browser, download files

### Phase 6: Polish
22. Error handling and edge cases
23. Extraction log output
24. Visual polish on Streamlit app (confidence badges, progress animation)
25. README and documentation
26. Full test suite

---

## 11. Key Risk Areas and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| pdfplumber fails to extract tables from some Lotsearch pages | Medium | High | Fallback to raw text extraction; the AI interpreter can work with unstructured text (less accurate but functional). Log extraction failures for manual review. |
| Claude API generates hallucinated data (false bore IDs, invented distances) | Medium | High | Validator checks all specific identifiers against extracted data. Re-prompt on failure. Confidence tagging makes hallucinations visible during review. |
| Lotsearch changes their PDF format | Low | High | Generic extraction + AI interpretation is inherently resilient to format changes. The bespoke dataset listing parser is the main vulnerability — monitor this. |
| API costs escalate with high report volumes | Low | Low | At $0.10-0.30 per report, even 100 reports/month = $10-30. Negligible relative to consultant time saved. |
| python-docx output doesn't match existing report formatting closely enough | Medium | Medium | The docx is explicitly a DRAFT — user expects to do final formatting. Focus on structural correctness (headings, tables, content) rather than pixel-perfect layout. |

---

*Document version: 2.0*
*Prepared: 27 February 2026*
*Status: Confirmed — ready for Claude Code implementation*
*All assumptions from Methodology Section 9 resolved*
