# Job-Finding Agent — Design (v1)

## Context

A personal tool that finds startups worth applying to (newly funded, or actively
hiring) for a target role, scores them against the user's resume, finds a likely
contact at the company, and drafts a personalized outreach message — for the user
to review and act on manually.

This is the first vertical slice of a larger eventual system (sourcing → matching
→ outreach → auto-apply → tracking dashboard). This spec covers **sourcing,
matching, and outreach drafting** only; auto-apply and a web dashboard are
explicitly deferred.

Reference: [tinyfish-io/bigset](https://github.com/tinyfish-io/bigset) — a
TypeScript tool that builds refreshed structured datasets from natural-language
descriptions via autonomous research agents (search → verify → extract →
refresh). Not used directly in v1, but its "agentic research, plain extraction"
pattern is the inspiration for the sourcing/people-finding design below, and it
remains a candidate to swap in later as a sourcing connector if it proves more
effective than the in-house implementation.

## Goals (v1 scope)

- Source candidate companies/roles from two parallel pipelines:
  1. Recent funding news (signal: "company X just raised, might be hiring soon")
  2. Live job postings
  Both filtered for relevance to one or more configured target-role profiles.
- Score/match each candidate against the resume role-variant it's most relevant to.
- For matches above a score threshold, find a likely contact (founder /
  hiring manager / eng manager) — best-effort.
- Draft a personalized outreach message and/or tailored application blurb for
  each above-threshold match.
- Persist all of the above in SQLite so reruns don't reprocess or duplicate
  work.
- Output a markdown report (full detail) + CSV (sortable summary) per run for
  manual review.
- Run manually via CLI (`uv run job-agent run`, or per-stage subcommands).

## Explicit non-goals (v1)

- Auto-submitting applications to ATS/job boards.
- Auto-sending outreach messages — the user reviews and sends manually.
- Scheduled/automatic runs (cron/Task Scheduler) — manual invocation only.
- A web dashboard — output is files only; the data layer (SQLite) is shaped
  so a dashboard can be added later without re-architecting storage.
- Resume re-parsing/versioning pipeline — resumes are static input files read
  once per role-variant config, not a dynamic pipeline.

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              CLI (Typer/argparse)         │
                         │   job-agent source | match | outreach |   │
                         │   job-agent run  (runs all stages)        │
                         └───────────────┬───────────────────────────┘
                                          │
        ┌─────────────────────────────────────────────────────────┐
        │                      STORE (SQLite)                      │
        │  companies | jobs | role_variants | matches | contacts |  │
        │  outreach_drafts                                          │
        └───────┬───────────────┬───────────────┬───────────────┬──┘
                │               │               │               │
   ┌────────────▼──────┐ ┌──────▼───────┐ ┌─────▼──────┐ ┌──────▼───────┐
   │  SOURCING (agent)  │ │  MATCHING    │ │ PEOPLE-FIND │ │  OUTREACH    │
   │  - funding connector│ │  (function)  │ │  (agent)    │ │  (function)  │
   │  - jobs connector   │ │  score(role, │ │  search →   │ │  draft_msg() │
   │  loop: search→      │ │   job)->Score│ │  verify →   │ │              │
   │  verify→dedupe→     │ │              │ │  enrich     │ │              │
   │  normalize          │ │              │ │  (paid API) │ │              │
   └────────────────────┘ └──────────────┘ └─────────────┘ └──────────────┘
                │
        ┌───────▼────────┐
        │ REPORT (md+csv) │
        └─────────────────┘
```

Each stage reads/writes the store directly and does not call other stages —
this keeps stages independently testable and lets any stage be re-run alone
(e.g. re-run outreach drafting after editing a prompt, without re-sourcing).

### Agentic vs. deterministic split

- **Agentic (LLM-driven iterative loop, bounded iterations):**
  - **Sourcing** — open-ended research: generate a search query, search,
    fetch/read results, verify relevance & recency, extract structured
    fields, decide whether to issue another query or stop.
  - **People-finding** — open-ended research: search for a plausible
    contact, verify it's a real/current employee, decide whether to enrich
    via a paid API, decide whether to retry with a different query.
- **Deterministic (single LLM call, fixed input → output):**
  - **Matching** — `score_match(role_variant, item) -> {score, reasoning}`.
  - **Outreach drafting** — `draft_message(match, contact|None) -> text`.
- **Plain Python (no LLM):** CLI, store/dedup, config loading, report
  rendering.

### Stage details

1. **Sourcing.** For each configured role variant, runs a bounded agentic loop
   over pluggable `SourceConnector`s (funding-news, job-board). Loop body:
   generate query → `connector.search(query)` → fetch/read top results →
   LLM verifies relevance & recency → LLM extracts structured fields
   (company name, funding stage/amount/date if applicable, role hints,
   posting URL if applicable) → write to `companies`/`jobs`, deduped by
   normalized company name (companies) / URL (jobs). Capped at
   `max_queries_per_role_per_run` queries per role per run.

2. **Matching.** For each `companies`/`jobs` row without an existing
   `matches` row for a given role variant, one LLM call scores fit
   (0–10) with reasoning, written to `matches`. Pure function — no loop,
   no retries beyond the standard error-handling retry-once policy.

3. **People-finding.** Only runs for `matches` rows with
   `score >= score_threshold_for_outreach`. Bounded agentic loop: LLM
   web-search for a plausible founder/hiring-manager/eng-manager name +
   title at the company → verify it's plausible/current → if a configured
   paid people-search API is available, enrich with email/profile URL.
   Writes to `contacts` (nullable fields if nothing found — outreach
   drafting falls back to a generic "careers" angle in that case). Capped
   at the same per-role query budget as sourcing.

4. **Outreach drafting.** For each above-threshold `matches` row, one LLM
   call drafts a personalized message (using the `contacts` row if present)
   and/or a tailored application blurb, written to `outreach_drafts`. Pure
   function, no loop.

5. **Report.** Reads the store for the current run's new/updated rows and
   renders:
   - A markdown file (full detail: company, score, reasoning, contact,
     drafted message) for reading.
   - A CSV (company, role, score, contact, status) for sorting/filtering.
   Both written to `reports/<run-timestamp>/`.

### Connector interface

```python
class SourceConnector(Protocol):
    def search(self, query: str) -> list[RawResult]: ...
```

Funding-news and job-board connectors both implement this. v1 ships
free/scrapable implementations (web search + page fetch/extract). The
interface is the seam for upgrading to paid APIs (Crunchbase, job-board
APIs) later, or swapping in a different sourcing engine (e.g. BigSet)
without touching the sourcing loop's control logic.

## Data Model

SQLite, single file (e.g. `job_agent.db`).

| Table | Key columns |
|---|---|
| `companies` | id, name (normalized, unique), source_url, funding_stage, funding_amount, funding_date, raw_signal_text, first_seen_at |
| `jobs` | id, company_id (FK, nullable), title, url (unique), location, posted_at, raw_text, first_seen_at |
| `role_variants` | id, name, resume_path, target_keywords, seniority |
| `matches` | id, role_variant_id (FK), company_id (FK), job_id (FK, nullable), score, reasoning, status (new/reviewed/dismissed), scored_at — unique on (role_variant_id, company_id, job_id) |
| `contacts` | id, company_id (FK), name, title, profile_url, email (nullable), confidence, found_via |
| `outreach_drafts` | id, match_id (FK), contact_id (FK, nullable), message_text, draft_type (cold_outreach \| application_blurb), generated_at |

Dedup keys (`companies.name`, `jobs.url`, `matches.(role_variant_id,
company_id, job_id)`) ensure reruns skip already-processed items rather than
reprocessing or duplicating rows.

## Config

```yaml
role_variants:
  - name: backend-eng
    resume: resumes/backend.pdf
    keywords: [backend, distributed systems, python, go]
    seniority: mid-senior
  - name: ml-eng
    resume: resumes/ml.pdf
    keywords: [ml infra, llm, pytorch]
    seniority: mid-senior

sourcing:
  max_queries_per_role_per_run: 8
  funding_lookback_days: 30

matching:
  score_threshold_for_outreach: 7   # out of 10

llm:
  provider: openrouter
  model: <configurable, e.g. anthropic/claude-sonnet>

people_search:
  paid_api: null   # e.g. "apollo" — optional, falls back to LLM-search-only if unset
```

Resume files are read once and parsed (text extraction) into the role
variant's profile used in matching prompts — treated as a static input, not
a pipeline that re-parses every run.

## Error Handling

- Connector/search failures (timeouts, rate limits, blocked requests):
  caught per-query, logged, loop continues to the next query rather than
  aborting the run.
- LLM call failures (API errors, malformed JSON output): retried once with
  a stricter prompt; if still failing, the item is skipped and flagged in
  the report under a "couldn't process" section rather than silently
  dropped.
- Paid people-search API failures/quota exhaustion: treated as "not found,"
  falls back to a generic contact — never blocks the pipeline.

## Cost / Runaway Control

Sourcing and people-finding are agentic loops, so they need explicit caps:

- `max_queries_per_role_per_run` (config) bounds iterations per role per
  stage.
- A running total-LLM-call counter per run, checked before each new
  search/verify step, enforces a hard ceiling regardless of per-role caps.
- `--dry-run` flag runs the pipeline against fixture/mocked connectors and
  a mocked LLM client, for testing without burning API calls or quota.

## Testing Strategy

- **Connectors & store layer:** unit tests against fixture data, no live
  network or LLM calls.
- **Matching / outreach-drafting functions:** unit tests with mocked LLM
  responses (assert prompt construction and response parsing), plus a
  handful of golden-file tests against real sample resumes/jobs, reviewed
  by hand.
- **Agentic loops (sourcing, people-finding):** tested via an injected fake
  `SourceConnector`/search tool returning scripted result sequences;
  assertions cover loop termination, dedup behavior, and respecting
  iteration caps. Not run against live external search in CI.
- **End-to-end smoke test:** full `run` command against all-fixture
  connectors and a mocked LLM, asserting a report file is produced with
  the expected rows.

## Open Questions / Future Work (not blocking v1)

- Whether to integrate BigSet directly as a sourcing connector vs. keeping
  the in-house connector implementation.
- Which paid people-search API (if any) to integrate first.
- Web dashboard, scheduled runs, and auto-apply are deferred to future specs.
