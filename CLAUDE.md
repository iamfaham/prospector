# CLAUDE.md

## Project

Personal job-finding agent pipeline. Sources funded startups → scores against resume → tailors LaTeX resume → finds contacts → drafts outreach → generates report.

## Commands

```bash
uv run job-agent run               # full pipeline
uv run job-agent run --config path/to/config.yaml
uv run pytest                      # 103 tests, all must pass
uv run pytest tests/test_X.py -v   # single file
```

## Architecture

```
job_agent/
  cli.py                 # Typer entrypoint; orchestrates all stages
  config.py              # Pydantic config models; loaded from config.yaml
  models.py              # Core dataclasses (Company, Match, ResumeDraft, ...)
  store.py               # SQLite persistence; all DB access goes here
  resume.py              # PDF/txt extraction; make_resume_summary()
  connectors/
    web_search.py        # Tavily POST API → list[RawResult]
    bigset.py            # CSV connector
  llm/
    client.py            # OpenRouter via openai SDK; call() / call_json() / is_over_budget()
    prompts.py           # All prompt-building functions (return (system, user) tuples)
  stages/
    sourcing.py          # run_sourcing() — query connectors, LLM extract, store companies
    matching.py          # run_matching() — LLM score each company vs resume
    resume_tailoring.py  # run_resume_tailoring() — LLM tailors LaTeX or markdown resume
    people_finding.py    # run_people_finding() — web search or Apollo for contacts
    outreach.py          # run_outreach() — draft cold messages
    report.py            # run_report() — markdown + CSV + agentic PDF compile loop
  output/
    compiler.py          # try_compile_pdf() / compile_pdf() / compile_docx()
```

## Key conventions

- **All DB writes are idempotent** — tables use `UNIQUE` constraints; re-running skips already-processed rows.
- **All stage functions return `dict[str, int]`** counters (`{"scored": N, "errors": N}`).
- **Prompt functions live in `prompts.py`** and return `(system_prompt, user_prompt)` tuples. Never build prompts inline in stage code.
- **LLM calls go through `LLMClient`** — never call `openai` directly in stage code.
- **`compiler.py` is a pure utility** — no LLM imports. The agentic retry loop lives in `report.py`.
- **`resume_latex` in config** enables LaTeX mode; if unset, tailoring falls back to markdown output.

## Environment variables

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Required — LLM provider |
| `TAVILY_API_KEY` | Required — web search (1,000/month free) |
| `APOLLO_API_KEY` | Optional — people enrichment |
| `BIGSET_EXPORT_PATH` | Optional — local CSV of funded companies |
| `NO_COLOR=1` | Recommended on Windows |

## System dependencies

- **MiKTeX** (or TeX Live) — required for PDF output from LaTeX. Not pip-installable; one-click Windows installer at miktex.org.
- Everything else installs via `uv sync`.

## Testing

- No live API or network calls in tests — all LLM and HTTP calls are mocked.
- `tests/conftest.py` provides `sample_resume_path` and `bigset_csv_path` fixtures.
- Compiler tests mock `subprocess.run` (for pdflatex) and `pdf2docx.Converter` (for DOCX).
- Add tests before adding features; keep the suite green.

## Output naming convention

`{CandidateName}_{Company}_{Role}_{YYYY-MM-DD}.{ext}`

Example: `Faham_AcmeCorp_SeniorBackendEngineer_2026-06-19.pdf`

- CamelCase slug, split on spaces/hyphens/underscores, max 40 chars per part.
- Date appended verbatim (with hyphens) — do not slugify the date.
