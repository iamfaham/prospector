# job_agent/cli.py
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

from job_agent.config import load_config
from job_agent.llm.client import LLMClient
from job_agent.models import RoleVariant
from job_agent.resume import parse_resume, make_resume_summary
from job_agent.store import Store
from job_agent.connectors.bigset import BigSetConnector
from job_agent.connectors.web_search import WebSearchConnector
from job_agent.stages.matching import run_matching
from job_agent.stages.outreach import run_outreach
from job_agent.stages.people_finding import run_people_finding
from job_agent.stages.report import run_report
from job_agent.stages.review import run_review
from job_agent.stages.sourcing import run_sourcing

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
