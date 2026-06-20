# Job-Finding Agent

A personal autonomous agent that sources recently-funded startups, scores them against your resume, finds the right contact, drafts outreach, and produces tailored PDF/DOCX resumes — all from a single command.

```
uv run job-agent run
```

---

## Pipeline

```
sourcing → matching → resume tailoring → people-finding → outreach → report
```

| Stage | What it does |
|---|---|
| **Sourcing** | Queries Tavily web search (+ optional BigSet CSV) for funded startups matching your keywords |
| **Matching** | LLM scores each company 1–10 against your resume; skips anything below threshold |
| **Resume tailoring** | LLM rewrites your LaTeX resume to highlight relevant experience for that specific JD; agentic compile loop fixes errors and enforces one-page constraint |
| **People-finding** | Finds the right contact (founder/CTO/hiring manager) via web search or Apollo |
| **Outreach** | Drafts a personalised cold message per company |
| **Report** | Writes `reports/<timestamp>/report.md` + `matches.csv`; saves tailored PDF/DOCX per company |

---

## Prerequisites

| Tool | Required | Install |
|---|---|---|
| Python 3.13+ | ✅ | python.org |
| uv | ✅ | `pip install uv` |
| MiKTeX (or TeX Live) | For PDF output | [miktex.org](https://miktex.org) — one-click Windows installer |

All Python dependencies (including `pdf2docx` for DOCX conversion) install automatically via `uv`.

---

## Setup

```bash
# 1. Clone and install
git clone <repo-url>
cd everything-job
uv sync

# 2. Copy env template and fill in keys
cp .env.example .env
# edit .env

# 3. Add your resume
#    Place your PDF at:  resumes/resume.pdf
#    Place your .tex at: resumes/resume.tex   (enables PDF/DOCX tailoring)

# 4. Run
uv run job-agent run
```

---

## Environment variables

| Variable | Required | Where to get it |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | [openrouter.ai/keys](https://openrouter.ai/keys) — free credits on signup |
| `TAVILY_API_KEY` | ✅ | [app.tavily.com](https://app.tavily.com) — 1,000 searches/month free, no credit card |
| `APOLLO_API_KEY` | Optional | [developer.apollo.io](https://developer.apollo.io) — free tier for people-finding |
| `BIGSET_EXPORT_PATH` | Optional | Local CSV export from BigSet UI |
| `NO_COLOR=1` | Recommended on Windows | Prevents Unicode rendering issues in terminals |

---

## Configuration

Edit `config.yaml`:

```yaml
candidate_name: Faham   # used in output filenames

role_variants:
  - name: backend-eng
    resume: resumes/resume.pdf        # extracted for scoring
    resume_latex: resumes/resume.tex  # source for tailored PDF/DOCX output
    keywords: [backend, distributed systems, python, go]
    seniority: mid-senior

sourcing:
  max_queries_per_role_per_run: 8
  funding_lookback_days: 30

matching:
  score_threshold_for_outreach: 7   # 1–10; only companies above this get outreach

llm:
  provider: openrouter
  model: anthropic/claude-sonnet-4-5

people_search:
  paid_api: null   # set to "apollo" to enable Apollo.io enrichment
```

You can define multiple `role_variants` (e.g. `backend-eng`, `ml-eng`) each with a separate resume.

---

## Output

Each run produces a timestamped folder:

```
reports/
  20260619_143022/
    report.md          # full markdown report with scores, contacts, messages
    matches.csv        # spreadsheet-friendly summary
    resumes/
      Faham_AcmeCorp_SeniorBackendEngineer_2026-06-19.tex
      Faham_AcmeCorp_SeniorBackendEngineer_2026-06-19.pdf
      Faham_AcmeCorp_SeniorBackendEngineer_2026-06-19.docx
```

The pipeline is **idempotent** — re-running skips companies already scored/tailored/messaged.

---

## Development

```bash
uv run pytest          # run all tests (103 tests)
uv run job-agent --help
```

---

## Tech stack

- **Python 3.13**, [uv](https://github.com/astral-sh/uv), Typer CLI
- **OpenRouter** (LLM provider — access Claude, GPT-4, etc. via one key)
- **Tavily** (web search — free tier)
- **pdflatex / MiKTeX** (LaTeX → PDF)
- **pdf2docx** (PDF → DOCX, pure Python)
- **SQLite** (local state — companies, matches, drafts)
- **Pydantic v2** (config validation)
