"""CLI interface for the Lotsearch PSI Extraction Engine."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.compose.docx_export import DocxExporter
from src.compose.renderer import ReportRenderer
from src.extract.dataset_listing import parse_dataset_listing
from src.extract.table_extractor import extract_section
from src.ingest.pdf_extractor import extract_pdf
from src.ingest.section_splitter import split_sections
from src.ingest.state_detector import detect_state
from src.interpret.ai_interpreter import AIInterpreter
from src.interpret.prompt_builder import PromptBuilder

console = Console()


@click.group()
def main():
    """Lotsearch PSI Extraction Engine — extract data from Lotsearch PDFs and generate PSI report sections."""
    pass


@main.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir", "-o", type=click.Path(path_type=Path), default="./output",
    help="Output directory for generated files.",
)
@click.option(
    "--format", "-f", "output_format",
    type=click.Choice(["markdown", "docx", "both"]), default="both",
    help="Output format.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress.")
def process(pdf_path: Path, output_dir: Path, output_format: str, verbose: bool):
    """Process a Lotsearch PDF and generate PSI report sections."""
    load_dotenv()
    output_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Stage 1: Extract PDF
        task = progress.add_task("Extracting PDF content...", total=None)
        pdf_content = extract_pdf(pdf_path)
        progress.update(task, completed=True, description="[green]PDF extracted")

        # Stage 2: Detect state
        task = progress.add_task("Detecting state and site details...", total=None)
        state_id = detect_state(pdf_content.pages[0].text)
        progress.update(task, completed=True, description="[green]State detected")

        if verbose:
            console.print(Panel(
                f"State: {state_id.state}\n"
                f"Address: {state_id.address}\n"
                f"Suburb: {state_id.suburb}\n"
                f"Reference: {state_id.lotsearch_reference}",
                title="Site Details",
            ))

        # Stage 3: Split sections
        task = progress.add_task("Splitting into dataset sections...", total=None)
        sections = split_sections(pdf_content, pdf_path=pdf_path)
        progress.update(task, completed=True, description="[green]Sections split")

        # Stage 4: Parse dataset listing
        task = progress.add_task("Parsing dataset listing...", total=None)
        listing = parse_dataset_listing(pdf_content)
        progress.update(task, completed=True, description="[green]Dataset listing parsed")

        hits = [e for e in listing if e.has_hits]
        if verbose:
            console.print(f"  Datasets: {len(listing)} total, {len(hits)} with hits")

        # Stage 5: Extract section data
        task = progress.add_task("Extracting section data...", total=None)
        listing_lookup = {e.dataset_name: e for e in listing}
        extracted_sections = []
        for sec in sections:
            entry = listing_lookup.get(sec.heading)
            extracted = extract_section(sec, listing_entry=entry)
            extracted_sections.append(extracted)
        progress.update(task, completed=True, description="[green]Sections extracted")

        # Stage 6: Interpret (AI)
        task = progress.add_task(
            "Interpreting data (this may take 30-60 seconds)...", total=None
        )
        builder = PromptBuilder()
        listing_summary = PromptBuilder.summarise_listing(listing)
        interpreter = AIInterpreter(prompt_builder=builder)

        # Map sections to templates based on heading keywords
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
        progress.update(task, completed=True, description="[green]Interpretation complete")

        # Stage 7: Render report
        task = progress.add_task("Composing report...", total=None)
        renderer = ReportRenderer()
        markdown = renderer.render(
            state=state_id.state,
            sections=interpreted,
            state_id=state_id,
        )
        progress.update(task, completed=True, description="[green]Report composed")

    # Generate filenames
    date_str = datetime.now().strftime("%Y%m%d")
    suburb_clean = state_id.suburb.replace(" ", "_")
    base_name = f"PSI_Sections_{state_id.state}_{suburb_clean}_{date_str}"

    # Save outputs
    output_files: list[str] = []

    if output_format in ("markdown", "both"):
        md_path = output_dir / f"{base_name}.md"
        md_path.write_text(markdown, encoding="utf-8")
        output_files.append(str(md_path))

    if output_format in ("docx", "both"):
        docx_path = output_dir / f"{base_name}.docx"
        exporter = DocxExporter()
        exporter.export(markdown, docx_path)
        output_files.append(str(docx_path))

    # Save extraction log
    log_path = output_dir / f"{base_name}_extraction_log.json"
    log_data = {
        "state": state_id.model_dump(),
        "dataset_listing": [e.model_dump() for e in listing],
        "sections_count": len(sections),
        "interpreted_count": len(interpreted),
        "prompt_log": [p.model_dump() for p in interpreter.prompt_log],
    }
    log_path.write_text(json.dumps(log_data, indent=2, default=str), encoding="utf-8")
    output_files.append(str(log_path))

    # Summary
    conf_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in interpreted:
        c = s.confidence.upper()
        if c in conf_counts:
            conf_counts[c] += 1

    console.print()
    console.print(Panel(
        f"[bold]State:[/bold] {state_id.state}\n"
        f"[bold]Address:[/bold] {state_id.address}\n"
        f"[bold]Reference:[/bold] {state_id.lotsearch_reference}\n"
        f"[bold]Datasets:[/bold] {len(listing)} total, {len(hits)} with hits\n"
        f"[bold]Sections interpreted:[/bold] {len(interpreted)}\n"
        f"[bold]Confidence:[/bold] HIGH={conf_counts['HIGH']} "
        f"MEDIUM={conf_counts['MEDIUM']} LOW={conf_counts['LOW']}\n\n"
        + "\n".join(f"[bold]Output:[/bold] {f}" for f in output_files),
        title="Processing Complete",
        border_style="green",
    ))


def _map_sections_to_templates(
    extracted_sections: list, state: str
) -> dict:
    """Map extracted sections to prompt template names based on heading keywords."""
    from src.extract.table_extractor import ExtractedSection

    template_groups: dict[str, list[ExtractedSection]] = {}

    for sec in extracted_sections:
        heading_lower = sec.heading.lower()

        # Skip cover page and dataset listing
        if heading_lower in ("cover page", "dataset listing"):
            continue

        template = _heading_to_template(heading_lower, state)
        if template:
            template_groups.setdefault(template, []).append(sec)

    # Flatten: if a template has a single section, pass it directly;
    # if multiple, pass as list
    result = {}
    for template, secs in template_groups.items():
        if len(secs) == 1:
            result[template] = secs[0]
        else:
            result[template] = secs

    return result


def _heading_to_template(heading: str, state: str) -> str | None:
    """Map a section heading to its prompt template filename."""
    h = heading.lower()

    # Environmental setting group
    if any(kw in h for kw in (
        "topographic", "elevation", "geology", "geological", "soils",
        "soil", "acid sulfate", "watertable salinity", "depth to watertable",
        "hydrogeology", "features of interest", "surface elevation",
        "basement elevation",
    )):
        return "env_setting.txt"

    # Groundwater bores
    if "groundwater bore" in h or "boreholes" in h:
        return "groundwater_bores.txt"

    # EPA registers
    if "epa contamination" in h or "epa site management" in h:
        return "epa_registers.txt"
    if "epa records" in h and "audit" not in h and "preliminary" not in h:
        return "epa_registers.txt"
    if "epa activities" in h:
        return "epa_registers.txt"

    # EPA audits
    if "epa records" in h and ("audit" in h or "preliminary" in h or "gqruz" in h):
        return "env_audits.txt"

    # POEO (NSW only)
    if "poeo" in h:
        return "poeo_licences.txt"

    # Business directories
    if "business director" in h or "dry cleaners" in h:
        return "business_dirs.txt"

    # PFAS
    if "pfas" in h:
        return "pfas.txt"

    # Waste and liquid fuel
    if any(kw in h for kw in ("waste", "landfill", "gasworks", "liquid fuel")):
        return "waste_liquid_fuel.txt"

    # Mining / fire / natural hazards
    if any(kw in h for kw in ("mining", "fire", "natural hazard", "bushfire")):
        if state == "NSW":
            return "mining.txt"
        return "mining_fire.txt"

    # Defence
    if "defence" in h or "unexploded" in h:
        return "defence.txt"

    # Heritage, planning, ecological — skip (not in current templates)
    if any(kw in h for kw in (
        "heritage", "planning", "ecological", "inflow dependent",
        "native vegetation", "ramsar", "location confidence",
        "aerial imagery", "historical map", "site diagram",
    )):
        return None

    return None


if __name__ == "__main__":
    main()
