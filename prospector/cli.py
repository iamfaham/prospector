# prospector/cli.py
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from prospector.config import load_config
from prospector.llm.client import LLMClient
from prospector.models import RoleVariant
from prospector.resume import parse_resume, make_resume_summary
from prospector.store import Store
from prospector.connectors.bigset import BigSetConnector
from prospector.connectors.web_search import WebSearchConnector
from prospector.stages.matching import run_matching
from prospector.stages.outreach import run_outreach
from prospector.stages.people_finding import run_people_finding
from prospector.stages.report import run_report
from prospector.stages.review import run_review
from prospector.stages.sourcing import run_sourcing

app = typer.Typer(help="Job-Finding Agent: source → review → report")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)


def _build(config_path: str):
    cfg = load_config(config_path)

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        typer.echo("Error: OPENROUTER_API_KEY not set", err=True)
        raise typer.Exit(1)

    store = Store()
    llm = LLMClient(api_key=api_key, model=cfg.llm.model, max_total_calls=cfg.llm.max_calls)

    connectors = []
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        connectors.append(WebSearchConnector(api_key=tavily_key, connector_type="funding_news"))
        connectors.append(WebSearchConnector(api_key=tavily_key, connector_type="job_board"))
    else:
        typer.echo("Warning: TAVILY_API_KEY not set — web search disabled", err=True)

    bigset_path = os.environ.get("BIGSET_EXPORT_PATH", "")
    if bigset_path and Path(bigset_path).exists():
        connectors.append(BigSetConnector(csv_path=bigset_path))

    if not connectors:
        typer.echo("Warning: no connectors active", err=True)

    return cfg, store, llm, connectors


@app.command()
def source(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
) -> None:
    """Source startups, score matches, then review interactively."""
    cfg, store, llm, connectors = _build(config)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rv_map: dict[int, object] = {}
    latex_sources: dict[int, Optional[str]] = {}
    resume_texts: dict[str, str] = {}

    for rv_cfg in cfg.role_variants:
        rv = RoleVariant(
            name=rv_cfg.name,
            resume_path=rv_cfg.resume,
            keywords=rv_cfg.keywords,
            seniority=rv_cfg.seniority,
        )
        rv_id = store.upsert_role_variant(rv)
        resume_text = parse_resume(rv_cfg.resume)
        resume_texts[rv_cfg.name] = resume_text
        rv_map[rv_id] = rv_cfg

        latex_src: Optional[str] = None
        if rv_cfg.resume_latex:
            try:
                latex_src = Path(rv_cfg.resume_latex).read_text(encoding="utf-8")
            except OSError as exc:
                typer.echo(f"Warning: cannot read {rv_cfg.resume_latex}: {exc}", err=True)
        latex_sources[rv_id] = latex_src

        typer.echo(f"[source] {rv_cfg.name} …")
        c = run_sourcing(
            role_variant=rv_cfg, role_variant_id=rv_id,
            connectors=connectors, llm=llm, store=store, config=cfg.sourcing,
            today=today,
        )
        typer.echo(f"  → {c['companies']} companies, {c['jobs']} jobs, {c['errors']} errors")

        typer.echo(f"[match]  {rv_cfg.name} …")
        c = run_matching(
            role_variant=rv_cfg, role_variant_id=rv_id,
            resume_text=resume_text, llm=llm, store=store, config=cfg.matching,
        )
        typer.echo(f"  → {c['scored']} scored, {c['errors']} errors")

    typer.echo("\n[review] Starting interactive review…")
    run_review(
        store=store,
        rv_map=rv_map,
        latex_sources=latex_sources,
        resume_texts=resume_texts,
        matching_config=cfg.matching,
        llm=llm,
        candidate_name=cfg.candidate_name,
        output_dir="reports",
    )


@app.command()
def review(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
) -> None:
    """Resume interactive review of any still-pending matches."""
    cfg, store, llm, _ = _build(config)

    rv_map: dict[int, object] = {}
    latex_sources: dict[int, Optional[str]] = {}
    resume_texts: dict[str, str] = {}

    for rv_cfg in cfg.role_variants:
        rv = RoleVariant(
            name=rv_cfg.name, resume_path=rv_cfg.resume,
            keywords=rv_cfg.keywords, seniority=rv_cfg.seniority,
        )
        rv_id = store.upsert_role_variant(rv)
        resume_texts[rv_cfg.name] = parse_resume(rv_cfg.resume)
        rv_map[rv_id] = rv_cfg

        latex_src: Optional[str] = None
        if rv_cfg.resume_latex:
            try:
                latex_src = Path(rv_cfg.resume_latex).read_text(encoding="utf-8")
            except OSError:
                pass
        latex_sources[rv_id] = latex_src

    run_review(
        store=store,
        rv_map=rv_map,
        latex_sources=latex_sources,
        resume_texts=resume_texts,
        matching_config=cfg.matching,
        llm=llm,
        candidate_name=cfg.candidate_name,
        output_dir="reports",
    )


@app.command()
def compile(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
) -> None:
    """Compile any .tex files in reports/resumes/ that are missing their PDF."""
    from prospector.output.compiler import try_compile_pdf, compile_docx

    resumes_dir = Path("reports/resumes")
    if not resumes_dir.exists():
        typer.echo("[compile] reports/resumes/ not found — nothing to compile.")
        raise typer.Exit(0)

    tex_files = sorted(resumes_dir.glob("*.tex"))
    pending = [t for t in tex_files if not t.with_suffix(".pdf").exists()]
    if not pending:
        typer.echo("[compile] All .tex files already have a PDF.")
        raise typer.Exit(0)

    typer.echo(f"[compile] {len(pending)} .tex file(s) to compile …")
    for tex in pending:
        pdf_out = tex.with_suffix(".pdf")
        typer.echo(f"  → {tex.name} …")
        ok, pages, err = try_compile_pdf(tex.read_text(encoding="utf-8"), pdf_out)
        if ok:
            docx_out = tex.with_suffix(".docx")
            compile_docx(pdf_out, docx_out)
            typer.echo(f"  ✓ {pdf_out.name} ({pages}p)" + (f", {docx_out.name}" if docx_out.exists() else ""))
        else:
            short_err = err.strip().splitlines()[-1] if err.strip() else "unknown error"
            typer.echo(f"  ✗ {tex.name}: {short_err}")


@app.command()
def tailor(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
) -> None:
    """Retry tailoring + compile for accepted matches missing resumes, then find contacts and draft outreach."""
    from prospector.stages.review import _tailor_and_compile, _write_live_report

    cfg, store, llm, _ = _build(config)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    threshold = cfg.matching.score_threshold_for_outreach

    rv_map: dict[int, object] = {}
    latex_sources: dict[int, Optional[str]] = {}
    resume_texts: dict[str, str] = {}
    for rv_cfg in cfg.role_variants:
        rv = RoleVariant(
            name=rv_cfg.name, resume_path=rv_cfg.resume,
            keywords=rv_cfg.keywords, seniority=rv_cfg.seniority,
        )
        rv_id = store.upsert_role_variant(rv)
        resume_texts[rv_cfg.name] = parse_resume(rv_cfg.resume)
        rv_map[rv_id] = rv_cfg
        latex_src: Optional[str] = None
        if rv_cfg.resume_latex:
            try:
                latex_src = Path(rv_cfg.resume_latex).read_text(encoding="utf-8")
            except OSError as exc:
                typer.echo(f"Warning: cannot read {rv_cfg.resume_latex}: {exc}", err=True)
        latex_sources[rv_id] = latex_src

    resumes_dir = Path("reports/resumes")
    resumes_dir.mkdir(parents=True, exist_ok=True)

    pending = store.get_accepted_matches_needing_draft(threshold)
    if pending:
        typer.echo(f"[tailor] {len(pending)} accepted match(es) need resumes …")
        tailor_results: list[dict] = []
        for match in pending:
            rv_cfg = rv_map.get(match["role_variant_id"])
            if rv_cfg is None:
                typer.echo(f"  ! No role variant config for match {match['id']}, skipping")
                continue
            typer.echo(f"  → {match['company_name']} ({match['role_variant_name']}) …")
            result = _tailor_and_compile(
                match, rv_cfg, latex_sources.get(match["role_variant_id"]),
                resume_texts.get(rv_cfg.name, ""),
                store.db_path, llm, resumes_dir, cfg.candidate_name, today,
            )
            tailor_results.append(result)
            icon = "✓" if result.get("ok") else "✗"
            files = result.get("files", [])
            detail = ", ".join(Path(f).name for f in files) if files else result.get("error", "no output")
            typer.echo(f"  {icon} {result['company']}: {detail}")
        _write_live_report(store, "reports", tailor_results)
    else:
        typer.echo("[tailor] All accepted matches already have resumes.")

    typer.echo("[people-find] …")
    apollo_key: Optional[str] = os.environ.get("APOLLO_API_KEY")
    c = run_people_finding(
        llm=llm, store=store, config=cfg.people_search,
        threshold=threshold, apollo_api_key=apollo_key,
    )
    typer.echo(f"  → {c['found']} found, {c['not_found']} not found, {c['errors']} errors")

    typer.echo("[outreach] …")
    first_resume = next(iter(resume_texts.values()), "")
    c = run_outreach(
        llm=llm, store=store, threshold=threshold,
        resume_summary=make_resume_summary(first_resume),
    )
    typer.echo(f"  → {c['drafted']} drafted, {c['errors']} errors")

    typer.echo("\n[tailor] Done. Run 'uv run prospector report' to generate the final report.")


@app.command()
def report(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
) -> None:
    """Find contacts, draft outreach, and generate final report for accepted matches."""
    cfg, store, llm, _ = _build(config)

    resume_texts = {rv.name: parse_resume(rv.resume) for rv in cfg.role_variants}
    first_resume = next(iter(resume_texts.values()), "")

    typer.echo("[people-find] …")
    apollo_key: Optional[str] = os.environ.get("APOLLO_API_KEY")
    c = run_people_finding(
        llm=llm, store=store, config=cfg.people_search,
        threshold=cfg.matching.score_threshold_for_outreach,
        apollo_api_key=apollo_key,
    )
    typer.echo(f"  → {c['found']} found, {c['not_found']} not found, {c['errors']} errors")

    typer.echo("[outreach] …")
    c = run_outreach(
        llm=llm, store=store,
        threshold=cfg.matching.score_threshold_for_outreach,
        resume_summary=make_resume_summary(first_resume),
    )
    typer.echo(f"  → {c['drafted']} drafted, {c['errors']} errors")

    typer.echo("[report] …")
    paths = run_report(store, candidate_name=cfg.candidate_name, llm=llm)
    typer.echo(f"  → {paths['markdown']}")
    typer.echo(f"  → {paths['csv']}")
