# Job-Finding Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that sources startups (funded + hiring), scores them against resume role variants, finds a contact, and drafts personalized outreach — output is a markdown + CSV report reviewed manually.

**Architecture:** Modular Python pipeline: sourcing (agentic loop) → matching (single LLM call) → people-finding (agentic loop) → outreach drafting (single LLM call) → report. Each stage reads/writes a shared SQLite store; stages don't call each other. Connectors (Serper web search, BigSet CSV) implement a shared `SourceConnector` protocol.

**Tech Stack:** Python 3.13, uv, typer, pydantic, sqlite3 (stdlib), openai SDK (OpenRouter via base_url), httpx, pdfplumber, pytest, pytest-mock

---

## File Map

```
job_agent/
├── __init__.py
├── cli.py                  # Typer CLI: source / match / people / outreach / run
├── config.py               # Pydantic Config + load_config()
├── models.py               # All dataclasses: Company, Job, Match, Contact, etc.
├── store.py                # SQLite store: schema, CRUD, dedup
├── resume.py               # PDF/text parser + make_resume_summary()
├── llm/
│   ├── __init__.py
│   ├── client.py           # LLMClient: OpenRouter wrapper, retry, call budget
│   └── prompts.py          # All prompt builders → (system, user) tuples
├── connectors/
│   ├── __init__.py
│   ├── base.py             # SourceConnector Protocol
│   ├── web_search.py       # Serper API connector
│   └── bigset.py           # BigSet CSV export connector
└── stages/
    ├── __init__.py
    ├── sourcing.py         # Agentic sourcing loop
    ├── matching.py         # Deterministic score_match
    ├── people_finding.py   # Agentic people-finding loop
    ├── outreach.py         # Deterministic draft_message
    └── report.py           # Markdown + CSV renderer
tests/
├── conftest.py
├── fixtures/
│   ├── sample_resume.txt
│   └── bigset_export.csv
├── test_models.py
├── test_config.py
├── test_store.py
├── test_resume.py
├── test_llm_client.py
├── test_prompts.py
├── test_connectors.py
├── test_sourcing.py
├── test_matching.py
├── test_people_finding.py
├── test_outreach.py
├── test_report.py
└── test_smoke.py
config.yaml
```

---

## Task 1: Project setup

**Files:**
- Modify: `pyproject.toml`
- Create: `job_agent/__init__.py`, `job_agent/llm/__init__.py`, `job_agent/connectors/__init__.py`, `job_agent/stages/__init__.py`
- Create: `tests/conftest.py`, `tests/fixtures/sample_resume.txt`, `tests/fixtures/bigset_export.csv`
- Create: `config.yaml`

- [ ] **Step 1: Add dependencies**

```toml
# pyproject.toml — replace the existing file content
[project]
name = "everything-job"
version = "0.1.0"
description = "Job-finding agent: source startups, match resume, draft outreach"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
    "httpx>=0.27",
    "openai>=1.30",
    "pdfplumber>=0.11",
    "pyyaml>=6.0",
]

[project.scripts]
job-agent = "job_agent.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-mock>=3.14",
]
```

- [ ] **Step 2: Install dependencies**

```bash
uv sync
uv add --dev pytest pytest-mock
```

Expected: lock file updated, no errors.

- [ ] **Step 3: Create package `__init__.py` files**

```python
# job_agent/__init__.py  (empty)
```
```python
# job_agent/llm/__init__.py  (empty)
```
```python
# job_agent/connectors/__init__.py  (empty)
```
```python
# job_agent/stages/__init__.py  (empty)
```

- [ ] **Step 4: Create test fixtures**

```
# tests/fixtures/sample_resume.txt
John Doe | john@example.com | github.com/johndoe

EXPERIENCE
Senior Backend Engineer — Acme Corp (2021–present)
  - Built distributed data pipeline in Python/Go processing 10M events/day
  - Designed REST APIs consumed by 50+ internal teams
  - Led migration from monolith to microservices (Kubernetes, Postgres)

Software Engineer — StartupXYZ (2019–2021)
  - Python/Django backend for SaaS product (10k users)
  - Integrated third-party APIs (Stripe, Twilio)

SKILLS
Python, Go, Postgres, Redis, Kubernetes, REST APIs, distributed systems

EDUCATION
B.S. Computer Science — State University, 2019
```

```csv
# tests/fixtures/bigset_export.csv
name,url,description
Acme AI,https://acmeai.com,AI startup that raised $5M Seed to build LLM tooling
DataFlow Inc,https://dataflow.io,Series A data pipeline company hiring engineers
```

- [ ] **Step 5: Create conftest.py**

```python
# tests/conftest.py
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_resume_path() -> str:
    return str(FIXTURES_DIR / "sample_resume.txt")

@pytest.fixture
def bigset_csv_path() -> str:
    return str(FIXTURES_DIR / "bigset_export.csv")
```

- [ ] **Step 6: Create config.yaml**

```yaml
# config.yaml
role_variants:
  - name: backend-eng
    resume: resumes/backend.txt
    keywords: [backend, distributed systems, python, go]
    seniority: mid-senior

sourcing:
  max_queries_per_role_per_run: 8
  funding_lookback_days: 30

matching:
  score_threshold_for_outreach: 7

llm:
  provider: openrouter
  model: anthropic/claude-sonnet-4-5

people_search:
  paid_api: null
```

- [ ] **Step 7: Run tests to establish baseline**

```bash
uv run pytest --collect-only
```

Expected: no collection errors (no tests yet, just confirms setup).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock job_agent/ tests/ config.yaml
git commit -m "feat: project setup — deps, package structure, fixtures"
```

---

## Task 2: Data models

**Files:**
- Create: `job_agent/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py
from job_agent.models import (
    Company, Job, RoleVariant, Match, Contact, OutreachDraft,
    RawResult, Score, MatchStatus, DraftType, Confidence,
)

def test_company_defaults():
    c = Company(name="Acme", source_url="https://acme.com")
    assert c.id is None
    assert c.funding_stage is None
    assert c.first_seen_at is not None  # auto-filled

def test_match_status_enum():
    assert MatchStatus.NEW.value == "new"
    assert MatchStatus.REVIEWED.value == "reviewed"
    assert MatchStatus.DISMISSED.value == "dismissed"

def test_draft_type_enum():
    assert DraftType.COLD_OUTREACH.value == "cold_outreach"
    assert DraftType.APPLICATION_BLURB.value == "application_blurb"

def test_raw_result():
    r = RawResult(url="https://tc.com/a", title="Acme raises $5M", snippet="Acme AI raised...")
    assert r.content is None

def test_role_variant():
    rv = RoleVariant(name="backend-eng", resume_path="resumes/backend.txt",
                     keywords=["python", "go"], seniority="mid-senior")
    assert rv.id is None
    assert rv.keywords == ["python", "go"]
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.models'`

- [ ] **Step 3: Implement models.py**

```python
# job_agent/models.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MatchStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class DraftType(str, Enum):
    COLD_OUTREACH = "cold_outreach"
    APPLICATION_BLURB = "application_blurb"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class RawResult:
    url: str
    title: str
    snippet: str
    content: Optional[str] = None


@dataclass
class Company:
    name: str
    source_url: str
    id: Optional[int] = None
    funding_stage: Optional[str] = None
    funding_amount: Optional[str] = None
    funding_date: Optional[str] = None
    raw_signal_text: Optional[str] = None
    first_seen_at: str = field(default_factory=_now)


@dataclass
class Job:
    title: str
    url: str
    id: Optional[int] = None
    company_id: Optional[int] = None
    location: Optional[str] = None
    posted_at: Optional[str] = None
    raw_text: Optional[str] = None
    first_seen_at: str = field(default_factory=_now)


@dataclass
class RoleVariant:
    name: str
    resume_path: str
    keywords: list[str]
    seniority: str
    id: Optional[int] = None


@dataclass
class Score:
    value: int   # 0-10
    reasoning: str


@dataclass
class Match:
    role_variant_id: int
    company_id: int
    score: int
    reasoning: str
    id: Optional[int] = None
    job_id: Optional[int] = None
    status: MatchStatus = MatchStatus.NEW
    scored_at: str = field(default_factory=_now)


@dataclass
class Contact:
    company_id: int
    name: str
    title: str
    id: Optional[int] = None
    profile_url: Optional[str] = None
    email: Optional[str] = None
    confidence: Confidence = Confidence.LOW
    found_via: str = "web_search"


@dataclass
class OutreachDraft:
    match_id: int
    message_text: str
    draft_type: DraftType
    id: Optional[int] = None
    contact_id: Optional[int] = None
    generated_at: str = field(default_factory=_now)
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/models.py tests/test_models.py
git commit -m "feat: data models — Company, Job, Match, Contact, OutreachDraft enums"
```

---

## Task 3: Config loading

**Files:**
- Create: `job_agent/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import pytest
from pathlib import Path
import tempfile, textwrap, yaml
from job_agent.config import load_config, Config

MINIMAL_YAML = textwrap.dedent("""\
    role_variants:
      - name: backend-eng
        resume: resumes/backend.txt
        keywords: [python, go]
        seniority: mid-senior
""")

@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(MINIMAL_YAML)
    return str(p)

def test_load_minimal_config(config_file):
    cfg = load_config(config_file)
    assert len(cfg.role_variants) == 1
    assert cfg.role_variants[0].name == "backend-eng"
    assert cfg.role_variants[0].keywords == ["python", "go"]

def test_defaults_applied(config_file):
    cfg = load_config(config_file)
    assert cfg.sourcing.max_queries_per_role_per_run == 8
    assert cfg.sourcing.funding_lookback_days == 30
    assert cfg.matching.score_threshold_for_outreach == 7
    assert cfg.llm.provider == "openrouter"
    assert cfg.people_search.paid_api is None

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")

def test_invalid_config_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("role_variants: not_a_list")
    with pytest.raises(Exception):
        load_config(str(p))
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.config'`

- [ ] **Step 3: Implement config.py**

```python
# job_agent/config.py
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, ValidationError


class RoleVariantConfig(BaseModel):
    name: str
    resume: str
    keywords: list[str]
    seniority: str


class SourcingConfig(BaseModel):
    max_queries_per_role_per_run: int = 8
    funding_lookback_days: int = 30


class MatchingConfig(BaseModel):
    score_threshold_for_outreach: int = 7


class LLMConfig(BaseModel):
    provider: str = "openrouter"
    model: str = "anthropic/claude-sonnet-4-5"


class PeopleSearchConfig(BaseModel):
    paid_api: Optional[str] = None  # "apollo" | None


class Config(BaseModel):
    role_variants: list[RoleVariantConfig]
    sourcing: SourcingConfig = SourcingConfig()
    matching: MatchingConfig = MatchingConfig()
    llm: LLMConfig = LLMConfig()
    people_search: PeopleSearchConfig = PeopleSearchConfig()


def load_config(path: str = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(p) as f:
        raw = yaml.safe_load(f)
    return Config.model_validate(raw)
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/config.py tests/test_config.py
git commit -m "feat: config — pydantic Config, load_config(), defaults"
```

---

## Task 4: SQLite store

**Files:**
- Create: `job_agent/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
import pytest
from job_agent.store import Store
from job_agent.models import (
    Company, Job, RoleVariant, Match, Contact, OutreachDraft,
    MatchStatus, DraftType, Confidence,
)

@pytest.fixture
def store(tmp_path):
    return Store(db_path=str(tmp_path / "test.db"))

def test_upsert_company_new(store):
    c = Company(name="Acme AI", source_url="https://acme.com")
    cid = store.upsert_company(c)
    assert isinstance(cid, int) and cid > 0

def test_upsert_company_dedup(store):
    c = Company(name="Acme AI", source_url="https://acme.com")
    id1 = store.upsert_company(c)
    id2 = store.upsert_company(c)
    assert id1 == id2

def test_upsert_job_dedup(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    j = Job(title="Backend Eng", url="https://a.com/jobs/1", company_id=cid)
    id1 = store.upsert_job(j)
    id2 = store.upsert_job(j)
    assert id1 == id2

def test_upsert_role_variant(store):
    rv = RoleVariant(name="backend-eng", resume_path="r.txt", keywords=["python"], seniority="mid")
    rv_id = store.upsert_role_variant(rv)
    assert rv_id > 0
    # upsert again is idempotent
    rv_id2 = store.upsert_role_variant(rv)
    assert rv_id == rv_id2

def test_insert_match_dedup(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    m = Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="good fit")
    mid1 = store.insert_match(m)
    mid2 = store.insert_match(m)
    assert mid1 is not None
    assert mid2 is None  # dedup: same (rv, company, job=None) → skip

def test_get_unscored_companies(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    unscored = store.get_unscored_companies(rv_id)
    assert any(c.id == cid for c in unscored)
    # After inserting a match, it disappears from unscored
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=5, reasoning="ok"))
    assert all(c.id != cid for c in store.get_unscored_companies(rv_id))

def test_get_matches_above_threshold(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="great"))
    cid2 = store.upsert_company(Company(name="Beta", source_url="https://b.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid2, score=3, reasoning="weak"))
    above = store.get_matches_above_threshold(7)
    assert len(above) == 1 and above[0].score == 8

def test_get_contact_for_company(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    assert store.get_contact_for_company(cid) is None
    store.insert_contact(Contact(company_id=cid, name="Alice", title="CEO"))
    c = store.get_contact_for_company(cid)
    assert c is not None and c.name == "Alice"
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.store'`

- [ ] **Step 3: Implement store.py**

```python
# job_agent/store.py
import json
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from job_agent.models import (
    Company, Confidence, Contact, DraftType, Job, Match, MatchStatus,
    OutreachDraft, RoleVariant,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    funding_stage TEXT,
    funding_amount TEXT,
    funding_date TEXT,
    raw_signal_text TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    location TEXT,
    posted_at TEXT,
    raw_text TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    resume_path TEXT NOT NULL,
    keywords TEXT NOT NULL,
    seniority TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_variant_id INTEGER NOT NULL REFERENCES role_variants(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    job_id INTEGER REFERENCES jobs(id),
    score INTEGER NOT NULL,
    reasoning TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    scored_at TEXT NOT NULL,
    UNIQUE (role_variant_id, company_id, job_id)
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    profile_url TEXT,
    email TEXT,
    confidence TEXT NOT NULL DEFAULT 'low',
    found_via TEXT NOT NULL DEFAULT 'web_search'
);
CREATE TABLE IF NOT EXISTS outreach_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    contact_id INTEGER REFERENCES contacts(id),
    message_text TEXT NOT NULL,
    draft_type TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str = "job_agent.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_company(self, company: Company) -> int:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO companies (name, source_url, funding_stage, funding_amount,
                   funding_date, raw_signal_text, first_seen_at)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO NOTHING""",
                (company.name, company.source_url, company.funding_stage,
                 company.funding_amount, company.funding_date,
                 company.raw_signal_text, company.first_seen_at),
            )
            row = conn.execute(
                "SELECT id FROM companies WHERE name = ?", (company.name,)
            ).fetchone()
            return row["id"]

    def upsert_job(self, job: Job) -> int:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (company_id, title, url, location, posted_at, raw_text, first_seen_at)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(url) DO NOTHING""",
                (job.company_id, job.title, job.url, job.location,
                 job.posted_at, job.raw_text, job.first_seen_at),
            )
            row = conn.execute(
                "SELECT id FROM jobs WHERE url = ?", (job.url,)
            ).fetchone()
            return row["id"]

    def upsert_role_variant(self, rv: RoleVariant) -> int:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO role_variants (name, resume_path, keywords, seniority)
                   VALUES (?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                     resume_path=excluded.resume_path,
                     keywords=excluded.keywords,
                     seniority=excluded.seniority""",
                (rv.name, rv.resume_path, json.dumps(rv.keywords), rv.seniority),
            )
            row = conn.execute(
                "SELECT id FROM role_variants WHERE name = ?", (rv.name,)
            ).fetchone()
            return row["id"]

    def insert_match(self, match: Match) -> Optional[int]:
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO matches
                       (role_variant_id, company_id, job_id, score, reasoning, status, scored_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (match.role_variant_id, match.company_id, match.job_id,
                     match.score, match.reasoning, match.status.value, match.scored_at),
                )
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                return None

    def insert_contact(self, contact: Contact) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO contacts
                   (company_id, name, title, profile_url, email, confidence, found_via)
                   VALUES (?,?,?,?,?,?,?)""",
                (contact.company_id, contact.name, contact.title,
                 contact.profile_url, contact.email,
                 contact.confidence.value, contact.found_via),
            )
            return cursor.lastrowid

    def insert_outreach_draft(self, draft: OutreachDraft) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO outreach_drafts
                   (match_id, contact_id, message_text, draft_type, generated_at)
                   VALUES (?,?,?,?,?)""",
                (draft.match_id, draft.contact_id, draft.message_text,
                 draft.draft_type.value, draft.generated_at),
            )
            return cursor.lastrowid

    def get_unscored_companies(self, role_variant_id: int) -> list[Company]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.* FROM companies c
                   WHERE NOT EXISTS (
                     SELECT 1 FROM matches m
                     WHERE m.company_id = c.id
                       AND m.role_variant_id = ?
                       AND m.job_id IS NULL
                   )""",
                (role_variant_id,),
            ).fetchall()
            return [_to_company(r) for r in rows]

    def get_unscored_jobs(self, role_variant_id: int) -> list[Job]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT j.* FROM jobs j
                   WHERE NOT EXISTS (
                     SELECT 1 FROM matches m
                     WHERE m.job_id = j.id
                       AND m.role_variant_id = ?
                   )""",
                (role_variant_id,),
            ).fetchall()
            return [_to_job(r) for r in rows]

    def get_matches_above_threshold(self, threshold: int) -> list[Match]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM matches WHERE score >= ? AND status = 'new'",
                (threshold,),
            ).fetchall()
            return [_to_match(r) for r in rows]

    def get_company(self, company_id: int) -> Optional[Company]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM companies WHERE id = ?", (company_id,)
            ).fetchone()
            return _to_company(row) if row else None

    def get_job(self, job_id: int) -> Optional[Job]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return _to_job(row) if row else None

    def get_contact_for_company(self, company_id: int) -> Optional[Contact]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE company_id = ? ORDER BY id DESC LIMIT 1",
                (company_id,),
            ).fetchone()
            return _to_contact(row) if row else None

    def get_all_for_report(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    m.id AS match_id, m.score, m.reasoning, m.status, m.scored_at,
                    c.name AS company_name, c.funding_stage, c.funding_date,
                    j.title AS job_title, j.url AS job_url,
                    rv.name AS role_variant_name,
                    ct.name AS contact_name, ct.title AS contact_title,
                    ct.email AS contact_email, ct.profile_url AS contact_profile_url,
                    od.message_text, od.draft_type
                FROM matches m
                JOIN companies c ON c.id = m.company_id
                JOIN role_variants rv ON rv.id = m.role_variant_id
                LEFT JOIN jobs j ON j.id = m.job_id
                LEFT JOIN contacts ct ON ct.company_id = m.company_id
                LEFT JOIN outreach_drafts od ON od.match_id = m.id
                ORDER BY m.score DESC
            """).fetchall()
            return [dict(r) for r in rows]


def _to_company(r: sqlite3.Row) -> Company:
    return Company(id=r["id"], name=r["name"], source_url=r["source_url"],
                   funding_stage=r["funding_stage"], funding_amount=r["funding_amount"],
                   funding_date=r["funding_date"], raw_signal_text=r["raw_signal_text"],
                   first_seen_at=r["first_seen_at"])


def _to_job(r: sqlite3.Row) -> Job:
    return Job(id=r["id"], company_id=r["company_id"], title=r["title"],
               url=r["url"], location=r["location"], posted_at=r["posted_at"],
               raw_text=r["raw_text"], first_seen_at=r["first_seen_at"])


def _to_match(r: sqlite3.Row) -> Match:
    return Match(id=r["id"], role_variant_id=r["role_variant_id"],
                 company_id=r["company_id"], job_id=r["job_id"],
                 score=r["score"], reasoning=r["reasoning"],
                 status=MatchStatus(r["status"]), scored_at=r["scored_at"])


def _to_contact(r: sqlite3.Row) -> Contact:
    return Contact(id=r["id"], company_id=r["company_id"], name=r["name"],
                   title=r["title"], profile_url=r["profile_url"], email=r["email"],
                   confidence=Confidence(r["confidence"]), found_via=r["found_via"])
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_store.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/store.py tests/test_store.py
git commit -m "feat: SQLite store — schema, CRUD, dedup for all tables"
```

---

## Task 5: Resume parsing

**Files:**
- Create: `job_agent/resume.py`
- Create: `tests/test_resume.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_resume.py
import pytest
from pathlib import Path
from job_agent.resume import parse_resume, make_resume_summary

def test_parse_txt_resume(sample_resume_path):
    text = parse_resume(sample_resume_path)
    assert "python" in text.lower()
    assert "backend" in text.lower()

def test_parse_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_resume("nonexistent.pdf")

def test_make_resume_summary(sample_resume_path):
    text = parse_resume(sample_resume_path)
    summary = make_resume_summary(text, max_chars=100)
    assert len(summary) <= 100
    assert len(summary) > 0

def test_make_resume_summary_default_length(sample_resume_path):
    text = parse_resume(sample_resume_path)
    summary = make_resume_summary(text)
    assert len(summary) <= 500
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_resume.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.resume'`

- [ ] **Step 3: Implement resume.py**

```python
# job_agent/resume.py
from pathlib import Path


def parse_resume(resume_path: str) -> str:
    """Extract text from a PDF or plaintext resume file."""
    path = Path(resume_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    return path.read_text(encoding="utf-8")


def _parse_pdf(path: Path) -> str:
    import pdfplumber
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def make_resume_summary(resume_text: str, max_chars: int = 500) -> str:
    """Return the first max_chars of the resume as a brief outreach summary."""
    return resume_text[:max_chars].strip()
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_resume.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/resume.py tests/test_resume.py
git commit -m "feat: resume parser — PDF (pdfplumber) + txt, make_resume_summary()"
```

---

## Task 6: LLM client

**Files:**
- Create: `job_agent/llm/client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import MagicMock, patch
from job_agent.llm.client import LLMClient, LLMError

@pytest.fixture
def client():
    return LLMClient(api_key="test-key", model="anthropic/claude-haiku-4-5", max_total_calls=5)

def test_call_returns_content(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = client.call("system", "user")
    assert result == "hello"

def test_call_increments_counter(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "x"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        client.call("s", "u")
        client.call("s", "u")
    assert client.call_count == 2

def test_call_budget_exceeded_raises(client):
    # exhaust the budget
    client._call_count = 5
    with pytest.raises(LLMError, match="budget exhausted"):
        client.call("s", "u")

def test_call_json_parses(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"score": 8, "reasoning": "good"}'
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = client.call_json("s", "u")
    assert result == {"score": 8, "reasoning": "good"}

def test_call_json_invalid_raises(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "not json"
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        with pytest.raises(LLMError, match="invalid JSON"):
            client.call_json("s", "u")

def test_retry_on_first_failure(client):
    mock_ok = MagicMock()
    mock_ok.choices[0].message.content = "ok"
    call_count = {"n": 0}
    def side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("transient error")
        return mock_ok
    with patch.object(client._client.chat.completions, "create", side_effect=side_effect):
        result = client.call("s", "u")
    assert result == "ok"
    assert client.call_count == 2
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_llm_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.llm.client'`

- [ ] **Step 3: Implement llm/client.py**

```python
# job_agent/llm/client.py
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, api_key: str, model: str, max_total_calls: int = 200):
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model
        self.max_total_calls = max_total_calls
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def is_over_budget(self) -> bool:
        return self._call_count >= self.max_total_calls

    def call(self, system: str, user: str, *, expect_json: bool = False) -> str:
        """Single LLM call with one automatic retry. Raises LLMError on failure."""
        if self.is_over_budget():
            raise LLMError(f"LLM call budget exhausted ({self.max_total_calls} calls)")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict = {"model": self.model, "messages": messages}
        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}

        self._call_count += 1
        try:
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(f"LLM call failed, retrying once: {exc}")
            if self.is_over_budget():
                raise LLMError("LLM budget exhausted during retry") from exc
            self._call_count += 1
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as exc2:
                raise LLMError(f"LLM call failed after retry: {exc2}") from exc2

    def call_json(self, system: str, user: str) -> dict:
        """Call LLM, parse JSON. Raises LLMError if response is not valid JSON."""
        raw = self.call(system, user, expect_json=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {raw[:200]}") from exc
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_llm_client.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/llm/client.py tests/test_llm_client.py
git commit -m "feat: LLM client — OpenRouter wrapper, budget, retry, call_json()"
```

---

## Task 7: Prompt builders

**Files:**
- Create: `job_agent/llm/prompts.py`
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_prompts.py
from job_agent.llm.prompts import (
    sourcing_query_prompt,
    sourcing_extract_prompt,
    score_match_prompt,
    people_search_query_prompt,
    people_verify_prompt,
    draft_message_prompt,
)
from job_agent.config import RoleVariantConfig
from job_agent.models import RawResult

RV = RoleVariantConfig(name="be", resume="r.txt", keywords=["python", "go"], seniority="mid-senior")
RESULT = RawResult(url="https://tc.com/a", title="Acme raises $5M", snippet="Acme AI raised $5M Seed")

def test_sourcing_query_prompt_returns_tuple():
    system, user = sourcing_query_prompt(RV, "funding_news", [], 30)
    assert isinstance(system, str) and len(system) > 10
    assert "python" in user or "go" in user

def test_sourcing_query_prompt_job_board():
    system, user = sourcing_query_prompt(RV, "job_board", ["Acme"], 30)
    assert "job_board" not in system  # internals hidden from prompt text
    assert isinstance(user, str)

def test_sourcing_extract_prompt_returns_tuple():
    system, user = sourcing_extract_prompt(RESULT, RV, "funding_news", 30)
    assert "JSON" in system or "json" in system.lower()
    assert RESULT.title in user

def test_score_match_prompt_contains_resume():
    system, user = score_match_prompt("My resume text", RV, "Company: Acme\nFunding: Seed")
    assert "My resume text" in user
    assert "0-10" in user or "score" in user.lower()

def test_people_search_query_prompt():
    system, user = people_search_query_prompt("Acme AI", 0, [])
    assert "Acme AI" in user
    assert isinstance(system, str)

def test_people_verify_prompt():
    results = [RESULT]
    system, user = people_verify_prompt(results, "Acme AI")
    assert "Acme AI" in user
    assert "JSON" in system or "json" in system.lower()

def test_draft_message_prompt_with_contact():
    system, user = draft_message_prompt(
        company_name="Acme AI",
        job_title="Backend Engineer",
        funding_signal="Raised $5M Seed",
        contact_name="Alice Smith",
        contact_title="CTO",
        score_reasoning="Strong Python background",
        resume_summary="5 years Python, Go, distributed systems",
    )
    assert "Alice" in user or "Alice" in system
    assert "Acme AI" in user

def test_draft_message_prompt_without_contact():
    system, user = draft_message_prompt(
        company_name="Acme AI",
        job_title=None,
        funding_signal="Raised $5M Seed",
        contact_name=None,
        contact_title=None,
        score_reasoning="Strong match",
        resume_summary="5 years Python",
    )
    assert "Acme AI" in user
    assert isinstance(system, str)
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_prompts.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.llm.prompts'`

- [ ] **Step 3: Implement llm/prompts.py**

```python
# job_agent/llm/prompts.py
from job_agent.config import RoleVariantConfig
from job_agent.models import RawResult


def sourcing_query_prompt(
    role_variant: RoleVariantConfig,
    connector_type: str,
    already_found: list[str],
    funding_lookback_days: int,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    already = ", ".join(already_found[-10:]) if already_found else "none yet"

    system = (
        "You generate precise Google search queries to find job opportunities for a "
        "specific candidate profile. Return ONLY the raw search query string — no "
        "explanation, no quotes around it."
    )

    if connector_type == "funding_news":
        user = (
            f"Generate a Google search query to find startups that raised funding in "
            f"the last {funding_lookback_days} days, likely to hire someone with: "
            f"{keywords} ({role_variant.seniority}).\n\n"
            f"Already found (avoid): {already}\n\n"
            f"Be specific. Use site: or date filters where useful. "
            f"Example style: 'site:techcrunch.com startup raises Series A 2026 {role_variant.keywords[0]}'"
        )
    else:  # job_board
        kw0 = role_variant.keywords[0] if role_variant.keywords else "software engineer"
        user = (
            f"Generate a search query to find {role_variant.seniority} {kw0} job "
            f"openings at startups. Skills: {keywords}.\n\n"
            f"Already found companies (try others): {already}\n\n"
            f"Example: 'site:wellfound.com \"{kw0}\" startup remote 2026'"
        )
    return system, user


def sourcing_extract_prompt(
    result: RawResult,
    role_variant: RoleVariantConfig,
    connector_type: str,
    funding_lookback_days: int,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    system = (
        "You analyze search results to extract structured startup and job data. "
        "Always return valid JSON. Be strict about recency."
    )
    user = (
        f"Analyze this search result and extract information.\n\n"
        f"Title: {result.title}\nURL: {result.url}\nSnippet: {result.snippet}\n\n"
        f"Target skills: {keywords} ({role_variant.seniority})\n"
        f"Source type: {'funding news' if connector_type == 'funding_news' else 'job board'}\n"
        f"Max age: {funding_lookback_days} days\n\n"
        f"Return JSON:\n"
        f'{{"relevant": true/false, '
        f'"company": {{"name": "...", "funding_stage": "...|null", "funding_amount": "...|null", "funding_date": "YYYY-MM|null"}} | null, '
        f'"job": {{"title": "...", "url": "{result.url}", "location": "...|null", "posted_at": "YYYY-MM-DD|null", "raw_text": "...|null"}} | null}}\n\n'
        f"Set relevant=false if: not a startup, funding older than {funding_lookback_days} days, "
        f"or skills don't match. company is null for job postings where company is unknown."
    )
    return system, user


def score_match_prompt(
    resume_text: str,
    role_variant: RoleVariantConfig,
    context: str,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    system = "You score job-candidate fit 0-10. Always return valid JSON."
    user = (
        f"Score this opportunity for the candidate (0=no fit, 10=perfect).\n\n"
        f"=== RESUME ===\n{resume_text[:3000]}\n\n"
        f"=== TARGET PROFILE ===\nKeywords: {keywords}\nSeniority: {role_variant.seniority}\n\n"
        f"=== OPPORTUNITY ===\n{context}\n\n"
        f'Return JSON: {{"score": <0-10 integer>, "reasoning": "<2-3 sentences>"}}'
    )
    return system, user


def people_search_query_prompt(
    company_name: str,
    attempt: int,
    previous_queries: list[str],
) -> tuple[str, str]:
    previous = "\n".join(f"- {q}" for q in previous_queries) if previous_queries else "none"
    system = (
        "You generate Google search queries to find the right person to contact "
        "at a startup for job opportunities. Return ONLY the raw search query string."
    )
    user = (
        f"Generate a query to find the founder, CTO, VP Engineering, or hiring manager "
        f"at '{company_name}'.\n\nPrevious queries:\n{previous}\n\n"
        f"Attempt {attempt + 1}. {'Use a different angle than previous queries.' if attempt > 0 else ''}\n\n"
        f"Example styles:\n"
        f"- '{company_name} founder CEO LinkedIn'\n"
        f"- '{company_name} CTO site:linkedin.com'\n"
        f"- '{company_name} \"head of engineering\" contact email'"
    )
    return system, user


def people_verify_prompt(
    results: list[RawResult],
    company_name: str,
) -> tuple[str, str]:
    snippets = "\n\n".join(
        f"[{i+1}] {r.title}\n{r.url}\n{r.snippet}"
        for i, r in enumerate(results[:5])
    )
    system = "You extract contact information from search results. Always return valid JSON."
    user = (
        f"Find the best person to reach out to at '{company_name}' about job "
        f"opportunities. Prefer founder > CTO > VP Eng > Eng Manager.\n\n"
        f"{snippets}\n\n"
        f'Return JSON: {{"found": true/false, "name": "...|null", "title": "...|null", "profile_url": "...|null"}}\n'
        f"Set found=false if no result clearly identifies a real person at this company."
    )
    return system, user


def draft_message_prompt(
    company_name: str,
    job_title: str | None,
    funding_signal: str | None,
    contact_name: str | None,
    contact_title: str | None,
    score_reasoning: str,
    resume_summary: str,
) -> tuple[str, str]:
    greeting = f"Hi {contact_name.split()[0]}," if contact_name else "Hi,"
    recipient = (
        f"to {contact_name} ({contact_title}) at" if contact_name and contact_title
        else "to the team at"
    )
    if job_title:
        angle = f"I'm reaching out about the {job_title} role"
        style = "application blurb"
    elif funding_signal:
        angle = "Congratulations on your recent funding! I wanted to reach out"
        style = "cold outreach referencing funding"
    else:
        angle = "I wanted to reach out"
        style = "general cold outreach"

    system = (
        f"You write concise, personalized {style} messages for job outreach. "
        "First person, professional but warm, max 150 words. No 'I hope this message "
        "finds you well' or other filler. Never invent facts beyond what you're given."
    )
    user = (
        f"Write a cold outreach message {recipient} {company_name}.\n\n"
        f"{greeting}\n\n"
        f"Angle: {angle}.\n"
        f"Why good fit: {score_reasoning}\n"
        f"Candidate summary: {resume_summary}\n"
        f"Context: {funding_signal or 'N/A'}\n\n"
        "Write the full message text only (no subject line). Start with the greeting above."
    )
    return system, user
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_prompts.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/llm/prompts.py tests/test_prompts.py
git commit -m "feat: prompt builders — all six prompts returning (system, user) tuples"
```

---

## Task 8: Connectors

**Files:**
- Create: `job_agent/connectors/base.py`
- Create: `job_agent/connectors/web_search.py`
- Create: `job_agent/connectors/bigset.py`
- Create: `tests/test_connectors.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_connectors.py
import pytest
from job_agent.connectors.base import SourceConnector
from job_agent.connectors.web_search import WebSearchConnector
from job_agent.connectors.bigset import BigSetConnector
from job_agent.models import RawResult

def test_web_search_connector_is_source_connector():
    c = WebSearchConnector(api_key="key", connector_type="funding_news")
    assert isinstance(c, SourceConnector)
    assert c.connector_type == "funding_news"

def test_bigset_connector_is_source_connector(bigset_csv_path):
    c = BigSetConnector(csv_path=bigset_csv_path)
    assert isinstance(c, SourceConnector)
    assert c.connector_type == "bigset"

def test_bigset_returns_raw_results(bigset_csv_path):
    c = BigSetConnector(csv_path=bigset_csv_path)
    results = c.search("any query")
    assert len(results) == 2
    assert all(isinstance(r, RawResult) for r in results)
    assert results[0].title == "Acme AI"
    assert results[1].title == "DataFlow Inc"

def test_bigset_missing_file_returns_empty():
    c = BigSetConnector(csv_path="/nonexistent/path.csv")
    assert c.search("q") == []

def test_web_search_connector_handles_http_error(monkeypatch):
    import httpx
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(httpx, "post", fake_post)
    c = WebSearchConnector(api_key="key", connector_type="job_board")
    results = c.search("python startup jobs")
    assert results == []  # errors return empty, not raise
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_connectors.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.connectors.base'`

- [ ] **Step 3: Implement connectors**

```python
# job_agent/connectors/base.py
from typing import Protocol, runtime_checkable
from job_agent.models import RawResult


@runtime_checkable
class SourceConnector(Protocol):
    connector_type: str

    def search(self, query: str) -> list[RawResult]: ...
```

```python
# job_agent/connectors/web_search.py
import logging
import httpx
from job_agent.models import RawResult

logger = logging.getLogger(__name__)


class WebSearchConnector:
    def __init__(self, api_key: str, connector_type: str = "generic"):
        self._api_key = api_key
        self.connector_type = connector_type

    def search(self, query: str, num: int = 10) -> list[RawResult]:
        try:
            resp = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15.0,
            )
            resp.raise_for_status()
            return [
                RawResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                )
                for item in resp.json().get("organic", [])
            ]
        except Exception as exc:
            logger.error(f"[web_search] search failed for '{query}': {exc}")
            return []
```

```python
# job_agent/connectors/bigset.py
import csv
import logging
from pathlib import Path
from job_agent.models import RawResult

logger = logging.getLogger(__name__)


class BigSetConnector:
    connector_type = "bigset"

    def __init__(self, csv_path: str):
        self._csv_path = Path(csv_path)

    def search(self, query: str) -> list[RawResult]:
        """Read all rows from BigSet CSV export. The query arg is unused — returns all rows."""
        if not self._csv_path.exists():
            logger.warning(f"[bigset] CSV not found: {self._csv_path}")
            return []
        results: list[RawResult] = []
        with open(self._csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("url") or row.get("website") or row.get("link") or ""
                title = row.get("name") or row.get("company") or row.get("title") or ""
                snippet = row.get("description") or row.get("snippet") or row.get("summary") or ""
                if title or url:
                    results.append(RawResult(url=url, title=title, snippet=snippet))
        return results
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_connectors.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/connectors/ tests/test_connectors.py
git commit -m "feat: connectors — SourceConnector protocol, WebSearchConnector (Serper), BigSetConnector (CSV)"
```

---

## Task 9: Sourcing stage

**Files:**
- Create: `job_agent/stages/sourcing.py`
- Create: `tests/test_sourcing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sourcing.py
import pytest
from unittest.mock import MagicMock, patch
from job_agent.stages.sourcing import run_sourcing
from job_agent.store import Store
from job_agent.llm.client import LLMClient
from job_agent.config import RoleVariantConfig, SourcingConfig
from job_agent.models import RawResult

RV = RoleVariantConfig(name="be", resume="r.txt", keywords=["python"], seniority="mid")
CFG = SourcingConfig(max_queries_per_role_per_run=2, funding_lookback_days=30)

def _make_llm(responses: list[str]):
    """LLMClient that returns responses from a fixed list in order."""
    client = MagicMock(spec=LLMClient)
    client.is_over_budget.return_value = False
    call_count = {"n": 0}
    def call_json(system, user):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        import json
        return json.loads(responses[idx])
    def call(system, user, **kwargs):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        return responses[idx]
    client.call_json.side_effect = call_json
    client.call.side_effect = call
    return client

class FixtureConnector:
    connector_type = "funding_news"
    def __init__(self, results):
        self._results = results
    def search(self, query):
        return self._results

def test_sourcing_writes_company_to_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        __import__('job_agent.models', fromlist=['RoleVariant']).RoleVariant(
            name="be", resume_path="r.txt", keywords=["python"], seniority="mid"
        )
    )
    connector = FixtureConnector([
        RawResult(url="https://tc.com/acme", title="Acme raises $5M", snippet="Acme AI raised Seed"),
    ])
    llm = _make_llm([
        # call() for query generation
        "site:techcrunch.com python startup funding 2026",
        # call_json() for extract
        '{"relevant": true, "company": {"name": "Acme AI", "funding_stage": "Seed", "funding_amount": "$5M", "funding_date": "2026-06"}, "job": null}',
    ])
    counts = run_sourcing(
        role_variant=RV, role_variant_id=rv_id,
        connectors=[connector], llm=llm, store=store, config=CFG,
    )
    assert counts["companies"] >= 1
    companies = store.get_unscored_companies(rv_id)
    # Acme AI should be in store now (and hence removed from unscored after matching — but we haven't matched yet)
    assert any("Acme" in c.name for c in companies)

def test_sourcing_deduplicates(tmp_path):
    from job_agent.models import RoleVariant
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    connector = FixtureConnector([
        RawResult(url="https://tc.com/acme", title="Acme raises", snippet="..."),
    ])
    extract_response = '{"relevant": true, "company": {"name": "Acme AI", "funding_stage": "Seed", "funding_amount": "$5M", "funding_date": "2026-06"}, "job": null}'
    llm = _make_llm(["query string", extract_response])
    run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[connector], llm=llm, store=store, config=CFG)
    run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[connector], llm=llm, store=store, config=CFG)
    # Only one Acme AI in DB regardless of how many runs
    with store._conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM companies WHERE name='Acme AI'").fetchone()[0]
    assert count == 1

def test_sourcing_respects_iteration_cap(tmp_path):
    from job_agent.models import RoleVariant
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    call_tracker = {"n": 0}
    class CountingConnector:
        connector_type = "funding_news"
        def search(self, query):
            call_tracker["n"] += 1
            return []
    llm = _make_llm(["query string"])
    cfg = SourcingConfig(max_queries_per_role_per_run=3, funding_lookback_days=30)
    run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[CountingConnector()], llm=llm, store=store, config=cfg)
    assert call_tracker["n"] == 3

def test_sourcing_skips_irrelevant_results(tmp_path):
    from job_agent.models import RoleVariant
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    connector = FixtureConnector([RawResult(url="https://x.com", title="Noise", snippet="unrelated")])
    llm = _make_llm(["query", '{"relevant": false, "company": null, "job": null}'])
    counts = run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[connector], llm=llm, store=store, config=CFG)
    assert counts["companies"] == 0
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_sourcing.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.stages.sourcing'`

- [ ] **Step 3: Implement stages/sourcing.py**

```python
# job_agent/stages/sourcing.py
import logging
from job_agent.config import RoleVariantConfig, SourcingConfig
from job_agent.connectors.base import SourceConnector
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import sourcing_query_prompt, sourcing_extract_prompt
from job_agent.models import Company, Job
from job_agent.store import Store

logger = logging.getLogger(__name__)


def run_sourcing(
    role_variant: RoleVariantConfig,
    role_variant_id: int,
    connectors: list[SourceConnector],
    llm: LLMClient,
    store: Store,
    config: SourcingConfig,
) -> dict[str, int]:
    """Agentic sourcing loop. Returns {"companies": N, "jobs": N, "errors": N}."""
    counts = {"companies": 0, "jobs": 0, "errors": 0}
    found_names: list[str] = []

    for connector in connectors:
        ctype = connector.connector_type

        for i in range(config.max_queries_per_role_per_run):
            if llm.is_over_budget():
                logger.warning("[sourcing] LLM budget exhausted")
                break

            try:
                sys_p, usr_p = sourcing_query_prompt(
                    role_variant, ctype, found_names, config.funding_lookback_days
                )
                query = llm.call(sys_p, usr_p).strip().strip("\"'")
                logger.info(f"[sourcing] {ctype} query {i+1}: {query}")

                results = connector.search(query)

                for result in results:
                    if llm.is_over_budget():
                        break
                    try:
                        sys_e, usr_e = sourcing_extract_prompt(
                            result, role_variant, ctype, config.funding_lookback_days
                        )
                        extracted = llm.call_json(sys_e, usr_e)

                        if not extracted.get("relevant"):
                            continue

                        co_data = extracted.get("company")
                        if co_data and co_data.get("name"):
                            company = Company(
                                name=co_data["name"],
                                source_url=result.url,
                                funding_stage=co_data.get("funding_stage"),
                                funding_amount=co_data.get("funding_amount"),
                                funding_date=co_data.get("funding_date"),
                                raw_signal_text=result.snippet,
                            )
                            company_id = store.upsert_company(company)
                            if company.name not in found_names:
                                found_names.append(company.name)
                                counts["companies"] += 1

                            job_data = extracted.get("job")
                            if job_data and job_data.get("title") and job_data.get("url"):
                                job = Job(
                                    company_id=company_id,
                                    title=job_data["title"],
                                    url=job_data["url"],
                                    location=job_data.get("location"),
                                    posted_at=job_data.get("posted_at"),
                                    raw_text=job_data.get("raw_text"),
                                )
                                store.upsert_job(job)
                                counts["jobs"] += 1

                    except LLMError as exc:
                        logger.error(f"[sourcing] LLM error for {result.url}: {exc}")
                        counts["errors"] += 1

            except Exception as exc:
                logger.error(f"[sourcing] connector error (query {i+1}): {exc}")
                counts["errors"] += 1

    return counts
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_sourcing.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/stages/sourcing.py tests/test_sourcing.py
git commit -m "feat: sourcing stage — agentic loop, two-phase LLM (query-gen + extract), dedup"
```

---

## Task 10: Matching stage

**Files:**
- Create: `job_agent/stages/matching.py`
- Create: `tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_matching.py
import pytest
from unittest.mock import MagicMock
from job_agent.stages.matching import run_matching, score_match
from job_agent.store import Store
from job_agent.llm.client import LLMClient, LLMError
from job_agent.config import RoleVariantConfig, MatchingConfig
from job_agent.models import Company, Job, RoleVariant

RV_CFG = RoleVariantConfig(name="be", resume="r.txt", keywords=["python"], seniority="mid")
RESUME = "5 years Python backend engineer"

def _store_with_company(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv = RoleVariant(name="be", resume_path="r.txt", keywords=["python"], seniority="mid")
    rv_id = store.upsert_role_variant(rv)
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       funding_stage="Seed", raw_signal_text="Raised $5M"))
    return store, rv_id, cid

def _mock_llm(score=8, reasoning="good fit"):
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call_json.return_value = {"score": score, "reasoning": reasoning}
    return llm

def test_run_matching_scores_company(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = _mock_llm(score=8)
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["scored"] == 1
    assert counts["errors"] == 0
    matches = store.get_matches_above_threshold(7)
    assert len(matches) == 1 and matches[0].score == 8

def test_run_matching_skips_already_scored(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = _mock_llm(score=8)
    run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    counts2 = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts2["scored"] == 0  # already scored, skipped

def test_run_matching_scores_job(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    store.upsert_job(Job(title="Backend Eng", url="https://a.com/jobs/1", company_id=cid))
    llm = _mock_llm(score=9)
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["scored"] == 2  # company + job

def test_score_match_invalid_score_raises():
    llm = MagicMock(spec=LLMClient)
    llm.call_json.return_value = {"score": 15, "reasoning": "too high"}
    with pytest.raises(LLMError, match="Invalid score"):
        score_match(llm, RESUME, RV_CFG, "context")

def test_run_matching_handles_llm_error(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call_json.side_effect = LLMError("API down")
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["errors"] == 1
    assert counts["scored"] == 0
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_matching.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.stages.matching'`

- [ ] **Step 3: Implement stages/matching.py**

```python
# job_agent/stages/matching.py
import logging
from job_agent.config import RoleVariantConfig, MatchingConfig
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import score_match_prompt
from job_agent.models import Match
from job_agent.store import Store

logger = logging.getLogger(__name__)


def score_match(
    llm: LLMClient,
    resume_text: str,
    role_variant: RoleVariantConfig,
    context: str,
) -> dict:
    system, user = score_match_prompt(resume_text, role_variant, context)
    result = llm.call_json(system, user)
    score = int(result.get("score", -1))
    if not 0 <= score <= 10:
        raise LLMError(f"Invalid score {score}, must be 0-10")
    return {"score": score, "reasoning": result.get("reasoning", "")}


def run_matching(
    role_variant: RoleVariantConfig,
    role_variant_id: int,
    resume_text: str,
    llm: LLMClient,
    store: Store,
    config: MatchingConfig,
) -> dict[str, int]:
    counts = {"scored": 0, "errors": 0}

    for company in store.get_unscored_companies(role_variant_id):
        if llm.is_over_budget():
            break
        ctx = (
            f"Company: {company.name}\n"
            f"Funding: {company.funding_stage or 'unknown'} {company.funding_amount or ''}\n"
            f"Signal: {company.raw_signal_text or '(none)'}"
        )
        try:
            result = score_match(llm, resume_text, role_variant, ctx)
            store.insert_match(Match(
                role_variant_id=role_variant_id,
                company_id=company.id,
                job_id=None,
                score=result["score"],
                reasoning=result["reasoning"],
            ))
            counts["scored"] += 1
        except LLMError as exc:
            logger.error(f"[matching] company {company.name}: {exc}")
            counts["errors"] += 1

    for job in store.get_unscored_jobs(role_variant_id):
        if llm.is_over_budget():
            break
        ctx = (
            f"Job: {job.title}\n"
            f"URL: {job.url}\n"
            f"Description: {job.raw_text or '(none)'}"
        )
        try:
            result = score_match(llm, resume_text, role_variant, ctx)
            store.insert_match(Match(
                role_variant_id=role_variant_id,
                company_id=job.company_id,
                job_id=job.id,
                score=result["score"],
                reasoning=result["reasoning"],
            ))
            counts["scored"] += 1
        except LLMError as exc:
            logger.error(f"[matching] job {job.url}: {exc}")
            counts["errors"] += 1

    return counts
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_matching.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/stages/matching.py tests/test_matching.py
git commit -m "feat: matching stage — score_match(), run_matching(), dedup/error handling"
```

---

## Task 11: People-finding stage

**Files:**
- Create: `job_agent/stages/people_finding.py`
- Create: `tests/test_people_finding.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_people_finding.py
import pytest
from unittest.mock import MagicMock, patch
from job_agent.stages.people_finding import run_people_finding, _find_person
from job_agent.store import Store
from job_agent.llm.client import LLMClient
from job_agent.config import PeopleSearchConfig
from job_agent.models import Company, RoleVariant, Match, Contact, Confidence
from job_agent.connectors.web_search import WebSearchConnector

CFG = PeopleSearchConfig(paid_api=None)

def _populated_store(tmp_path, score=8):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=score, reasoning="good"))
    return store, cid

def _mock_llm(found: bool, name="Alice Smith", title="CTO"):
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    call_responses = iter([
        "Acme AI founder CEO LinkedIn",  # query generation
        {"found": found, "name": name if found else None, "title": title if found else None, "profile_url": "https://li.com/alice" if found else None},
    ])
    llm.call.return_value = "Acme AI founder CEO LinkedIn"
    llm.call_json.return_value = {"found": found, "name": name if found else None, "title": title if found else None, "profile_url": None}
    return llm

def test_finds_contact_and_writes_to_store(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    llm = _mock_llm(found=True)
    fake_connector = MagicMock(spec=WebSearchConnector)
    from job_agent.models import RawResult
    fake_connector.search.return_value = [RawResult(url="https://li.com/alice", title="Alice Smith CTO Acme", snippet="...")]
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    with patch("job_agent.stages.people_finding.WebSearchConnector", return_value=fake_connector):
        counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 1
    contact = store.get_contact_for_company(cid)
    assert contact is not None
    assert contact.name == "Alice Smith"

def test_skips_below_threshold(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=5)
    llm = _mock_llm(found=True)
    counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 0
    assert store.get_contact_for_company(cid) is None

def test_not_found_records_zero(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    llm = _mock_llm(found=False)
    fake_connector = MagicMock(spec=WebSearchConnector)
    from job_agent.models import RawResult
    fake_connector.search.return_value = [RawResult(url="https://x.com", title="unrelated", snippet="...")]
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    with patch("job_agent.stages.people_finding.WebSearchConnector", return_value=fake_connector):
        counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["not_found"] == 1

def test_skips_company_already_has_contact(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    store.insert_contact(Contact(company_id=cid, name="Bob", title="CEO"))
    llm = _mock_llm(found=True)
    counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 0  # already had a contact, skipped
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_people_finding.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.stages.people_finding'`

- [ ] **Step 3: Implement stages/people_finding.py**

```python
# job_agent/stages/people_finding.py
import logging
import os
from typing import Optional
import httpx
from job_agent.config import PeopleSearchConfig
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import people_search_query_prompt, people_verify_prompt
from job_agent.models import Contact, Confidence
from job_agent.store import Store
from job_agent.connectors.web_search import WebSearchConnector

logger = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3


def run_people_finding(
    llm: LLMClient,
    store: Store,
    config: PeopleSearchConfig,
    threshold: int,
    apollo_api_key: Optional[str] = None,
) -> dict[str, int]:
    counts = {"found": 0, "not_found": 0, "errors": 0}

    for match in store.get_matches_above_threshold(threshold):
        if store.get_contact_for_company(match.company_id):
            continue  # already found for this company

        company = store.get_company(match.company_id)
        if not company:
            continue

        try:
            contact = _find_person(
                llm=llm,
                company_name=company.name,
                apollo_api_key=apollo_api_key if config.paid_api == "apollo" else None,
            )
            if contact:
                contact.company_id = match.company_id
                store.insert_contact(contact)
                counts["found"] += 1
            else:
                counts["not_found"] += 1
        except Exception as exc:
            logger.error(f"[people_finding] {company.name}: {exc}")
            counts["errors"] += 1

    return counts


def _find_person(
    llm: LLMClient,
    company_name: str,
    apollo_api_key: Optional[str],
) -> Optional[Contact]:
    serper_key = os.getenv("SERPER_API_KEY", "")
    if not serper_key:
        logger.warning("[people_finding] SERPER_API_KEY not set, skipping")
        return None

    searcher = WebSearchConnector(api_key=serper_key)
    previous_queries: list[str] = []

    for attempt in range(_MAX_ATTEMPTS):
        if llm.is_over_budget():
            break
        try:
            sys_p, usr_p = people_search_query_prompt(company_name, attempt, previous_queries)
            query = llm.call(sys_p, usr_p).strip().strip("\"'")
            previous_queries.append(query)

            results = searcher.search(query)
            if not results:
                continue

            sys_v, usr_v = people_verify_prompt(results, company_name)
            person = llm.call_json(sys_v, usr_v)

            if not person.get("found"):
                continue

            contact = Contact(
                company_id=0,  # set by caller
                name=person["name"],
                title=person.get("title") or "Unknown",
                profile_url=person.get("profile_url"),
                confidence=Confidence.MEDIUM,
                found_via="web_search",
            )

            if apollo_api_key:
                email = _enrich_apollo(apollo_api_key, company_name)
                if email:
                    contact.email = email
                    contact.confidence = Confidence.HIGH
                    contact.found_via = "web_search+apollo"

            return contact

        except LLMError as exc:
            logger.error(f"[people_finding] attempt {attempt+1} LLM error: {exc}")

    return None


def _enrich_apollo(api_key: str, company_name: str) -> Optional[str]:
    try:
        resp = httpx.post(
            "https://api.apollo.io/v1/people/search",
            json={
                "api_key": api_key,
                "q_organization_name": company_name,
                "person_titles": [
                    "founder", "co-founder", "ceo", "cto",
                    "vp engineering", "head of engineering", "engineering manager",
                ],
                "page_size": 5,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
        if people:
            return people[0].get("email")
    except Exception as exc:
        logger.warning(f"[apollo] enrichment failed for {company_name}: {exc}")
    return None
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_people_finding.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/stages/people_finding.py tests/test_people_finding.py
git commit -m "feat: people-finding stage — agentic loop, Serper search, Apollo enrichment"
```

---

## Task 12: Outreach drafting stage

**Files:**
- Create: `job_agent/stages/outreach.py`
- Create: `tests/test_outreach.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_outreach.py
import pytest
from unittest.mock import MagicMock
from job_agent.stages.outreach import run_outreach, draft_message
from job_agent.store import Store
from job_agent.llm.client import LLMClient, LLMError
from job_agent.models import Company, RoleVariant, Match, Contact, DraftType

def _populated_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       raw_signal_text="Raised $5M Seed"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="strong match"))
    return store, cid

def test_drafts_cold_outreach(tmp_path):
    store, cid = _populated_store(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.return_value = "Hi, I saw Acme raised $5M..."
    counts = run_outreach(llm, store, threshold=7, resume_summary="5 years Python")
    assert counts["drafted"] == 1
    rows = store.get_all_for_report()
    assert any(r.get("message_text") for r in rows)

def test_drafts_application_blurb_when_job_present(tmp_path):
    from job_agent.models import Job
    store, cid = _populated_store(tmp_path)
    jid = store.upsert_job(Job(title="Backend Eng", url="https://a.com/j/1", company_id=cid))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    # insert match linked to job
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, job_id=jid, score=9, reasoning="perfect"))
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.return_value = "I'm writing about the Backend Eng role..."
    counts = run_outreach(llm, store, threshold=7, resume_summary="5 years Python")
    assert counts["drafted"] >= 1

def test_handles_llm_error_gracefully(tmp_path):
    store, cid = _populated_store(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.side_effect = LLMError("API down")
    counts = run_outreach(llm, store, threshold=7, resume_summary="resume")
    assert counts["errors"] == 1
    assert counts["drafted"] == 0

def test_draft_message_returns_string():
    llm = MagicMock(spec=LLMClient)
    llm.call.return_value = "Hi Alice, I saw Acme raised..."
    result = draft_message(llm, "Acme", None, "Raised $5M", "Alice", "CTO", "strong Python", "5yr Python")
    assert isinstance(result, str) and "Alice" in result
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_outreach.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.stages.outreach'`

- [ ] **Step 3: Implement stages/outreach.py**

```python
# job_agent/stages/outreach.py
import logging
from typing import Optional
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import draft_message_prompt
from job_agent.models import DraftType, OutreachDraft
from job_agent.store import Store

logger = logging.getLogger(__name__)


def draft_message(
    llm: LLMClient,
    company_name: str,
    job_title: Optional[str],
    funding_signal: Optional[str],
    contact_name: Optional[str],
    contact_title: Optional[str],
    score_reasoning: str,
    resume_summary: str,
) -> str:
    system, user = draft_message_prompt(
        company_name=company_name,
        job_title=job_title,
        funding_signal=funding_signal,
        contact_name=contact_name,
        contact_title=contact_title,
        score_reasoning=score_reasoning,
        resume_summary=resume_summary,
    )
    return llm.call(system, user)


def run_outreach(
    llm: LLMClient,
    store: Store,
    threshold: int,
    resume_summary: str,
) -> dict[str, int]:
    counts = {"drafted": 0, "errors": 0}

    for match in store.get_matches_above_threshold(threshold):
        if llm.is_over_budget():
            break

        company = store.get_company(match.company_id)
        job = store.get_job(match.job_id) if match.job_id else None
        contact = store.get_contact_for_company(match.company_id)

        try:
            message = draft_message(
                llm=llm,
                company_name=company.name if company else "this company",
                job_title=job.title if job else None,
                funding_signal=company.raw_signal_text if company else None,
                contact_name=contact.name if contact else None,
                contact_title=contact.title if contact else None,
                score_reasoning=match.reasoning,
                resume_summary=resume_summary,
            )
            draft_type = DraftType.APPLICATION_BLURB if job else DraftType.COLD_OUTREACH
            store.insert_outreach_draft(OutreachDraft(
                match_id=match.id,
                contact_id=contact.id if contact else None,
                message_text=message,
                draft_type=draft_type,
            ))
            counts["drafted"] += 1
        except LLMError as exc:
            logger.error(f"[outreach] match {match.id}: {exc}")
            counts["errors"] += 1

    return counts
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_outreach.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/stages/outreach.py tests/test_outreach.py
git commit -m "feat: outreach stage — draft_message(), run_outreach(), cold vs blurb type"
```

---

## Task 13: Report stage

**Files:**
- Create: `job_agent/stages/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_report.py
import csv
from pathlib import Path
from job_agent.stages.report import run_report
from job_agent.store import Store
from job_agent.models import Company, RoleVariant, Match, Contact, OutreachDraft, DraftType

def _full_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       funding_stage="Seed", funding_date="2026-06",
                                       raw_signal_text="Raised $5M"))
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="strong Python match"))
    ctid = store.insert_contact(Contact(company_id=cid, name="Alice Smith", title="CTO",
                                        email="alice@acme.com", profile_url="https://li.com/alice"))
    store.insert_outreach_draft(OutreachDraft(
        match_id=mid, contact_id=ctid, draft_type=DraftType.COLD_OUTREACH,
        message_text="Hi Alice, I saw Acme raised $5M..."
    ))
    return store

def test_creates_report_files(tmp_path):
    store = _full_store(tmp_path)
    report_dir = tmp_path / "reports"
    paths = run_report(store, output_dir=str(report_dir))
    assert Path(paths["markdown"]).exists()
    assert Path(paths["csv"]).exists()

def test_markdown_contains_company_and_score(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    md = Path(paths["markdown"]).read_text()
    assert "Acme AI" in md
    assert "8/10" in md
    assert "Alice Smith" in md
    assert "Hi Alice" in md

def test_csv_has_correct_columns(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    with open(paths["csv"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Acme AI"
    assert rows[0]["score"] == "8"
    assert rows[0]["contact_name"] == "Alice Smith"

def test_empty_store_produces_valid_report(tmp_path):
    store = Store(db_path=str(tmp_path / "empty.db"))
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    assert Path(paths["markdown"]).exists()
    md = Path(paths["markdown"]).read_text()
    assert "Total matches: 0" in md
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_report.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.stages.report'`

- [ ] **Step 3: Implement stages/report.py**

```python
# job_agent/stages/report.py
import csv
from datetime import datetime, timezone
from pathlib import Path
from job_agent.store import Store


def run_report(store: Store, output_dir: str = "reports") -> dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir) / ts
    report_dir.mkdir(parents=True, exist_ok=True)

    rows = store.get_all_for_report()
    md_path = report_dir / "report.md"
    csv_path = report_dir / "matches.csv"

    _write_markdown(rows, md_path)
    _write_csv(rows, csv_path)

    return {"markdown": str(md_path), "csv": str(csv_path)}


def _write_markdown(rows: list[dict], path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Job Agent Report",
        f"Generated: {now}",
        f"Total matches: {len(rows)}",
        "",
        "---",
        "",
    ]

    for row in rows:
        score = row.get("score", "?")
        company = row.get("company_name", "Unknown")
        lines.append(f"## {company} (Score: {score}/10)")
        lines.append(f"**Role:** {row.get('role_variant_name', '?')}")
        if row.get("job_title"):
            lines.append(f"**Job:** [{row['job_title']}]({row.get('job_url', '#')})")
        if row.get("funding_stage"):
            lines.append(f"**Funding:** {row['funding_stage']} · {row.get('funding_date', '')}")
        lines += ["", f"**Match reasoning:** {row.get('reasoning', '')}", ""]
        if row.get("contact_name"):
            lines.append(f"**Contact:** {row['contact_name']} ({row.get('contact_title', '')})")
            if row.get("contact_email"):
                lines.append(f"**Email:** {row['contact_email']}")
            if row.get("contact_profile_url"):
                lines.append(f"**Profile:** {row['contact_profile_url']}")
            lines.append("")
        if row.get("message_text"):
            quoted = row["message_text"].replace("\n", "\n> ")
            lines += ["**Drafted message:**", "", f"> {quoted}", ""]
        lines += ["---", ""]

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(rows: list[dict], path: Path) -> None:
    fields = [
        "company_name", "role_variant_name", "score", "job_title", "job_url",
        "funding_stage", "funding_date", "contact_name", "contact_title",
        "contact_email", "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run — verify it passes**

```bash
uv run pytest tests/test_report.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_agent/stages/report.py tests/test_report.py
git commit -m "feat: report stage — markdown + CSV renderer with company/contact/message"
```

---

## Task 14: CLI

**Files:**
- Create: `job_agent/cli.py`
- Modify: `pyproject.toml` (already has `job-agent` script entry)

- [ ] **Step 1: Write smoke test (end-to-end, all-fixture)**

```python
# tests/test_smoke.py
"""
End-to-end smoke test: full 'run' command with fixture connectors and mocked LLM.
No live API calls, no network.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from job_agent.cli import app
from job_agent.llm.client import LLMClient

RUNNER = CliRunner()

FIXTURE_QUERY_RESPONSE = "python startup funding 2026"
FIXTURE_EXTRACT_RESPONSE = '{"relevant": true, "company": {"name": "Acme AI", "funding_stage": "Seed", "funding_amount": "$5M", "funding_date": "2026-06"}, "job": null}'
FIXTURE_SCORE_RESPONSE = '{"score": 8, "reasoning": "Strong Python fit"}'
FIXTURE_PEOPLE_QUERY = "Acme AI founder CEO"
FIXTURE_PEOPLE_VERIFY = '{"found": true, "name": "Alice Smith", "title": "CTO", "profile_url": null}'
FIXTURE_MESSAGE = "Hi Alice, I saw Acme raised $5M..."


@pytest.fixture
def config_file(tmp_path, sample_resume_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""
role_variants:
  - name: backend-eng
    resume: {sample_resume_path}
    keywords: [python, go]
    seniority: mid-senior
sourcing:
  max_queries_per_role_per_run: 1
  funding_lookback_days: 30
matching:
  score_threshold_for_outreach: 7
llm:
  provider: openrouter
  model: anthropic/claude-haiku-4-5
people_search:
  paid_api: null
""")
    return str(cfg)


def test_run_produces_report(tmp_path, config_file, bigset_csv_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("BIGSET_EXPORT_PATH", bigset_csv_path)
    monkeypatch.chdir(tmp_path)

    call_responses = [
        FIXTURE_QUERY_RESPONSE,      # sourcing query gen (call)
        FIXTURE_EXTRACT_RESPONSE,    # sourcing extract (call_json via call_json)
        FIXTURE_EXTRACT_RESPONSE,    # bigset extract
        FIXTURE_SCORE_RESPONSE,      # match company
        FIXTURE_SCORE_RESPONSE,      # match bigset company
        FIXTURE_PEOPLE_QUERY,        # people query gen
        FIXTURE_PEOPLE_VERIFY,       # people verify
        FIXTURE_MESSAGE,             # outreach draft
    ]
    idx = {"n": 0}

    import json
    def fake_call(system, user, **kwargs):
        r = call_responses[idx["n"] % len(call_responses)]
        idx["n"] += 1
        return r

    def fake_call_json(system, user):
        r = call_responses[idx["n"] % len(call_responses)]
        idx["n"] += 1
        return json.loads(r)

    with patch("job_agent.llm.client.OpenAI"):
        with patch("job_agent.stages.people_finding.WebSearchConnector") as mock_ws:
            from job_agent.models import RawResult
            mock_ws.return_value.search.return_value = [
                RawResult(url="https://li.com/alice", title="Alice Smith CTO Acme", snippet="...")
            ]
            monkeypatch.setenv("SERPER_API_KEY", "fake-key")

            with patch.object(LLMClient, "call", side_effect=fake_call), \
                 patch.object(LLMClient, "call_json", side_effect=fake_call_json), \
                 patch.object(LLMClient, "is_over_budget", return_value=False):

                result = RUNNER.invoke(app, ["run", "--config", config_file])

    assert result.exit_code == 0, result.output
    reports = list((tmp_path / "reports").rglob("report.md"))
    assert len(reports) >= 1
    md = reports[0].read_text()
    assert "Job Agent Report" in md
```

- [ ] **Step 2: Run — verify it fails**

```bash
uv run pytest tests/test_smoke.py -v
```

Expected: `ModuleNotFoundError: No module named 'job_agent.cli'`

- [ ] **Step 3: Implement cli.py**

```python
# job_agent/cli.py
import logging
import os
from pathlib import Path
from typing import Optional
import typer

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
from job_agent.stages.sourcing import run_sourcing

app = typer.Typer(help="Job-Finding Agent: source startups → match → outreach")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _build(config_path: str) -> tuple:
    cfg = load_config(config_path)

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        typer.echo("Error: OPENROUTER_API_KEY not set", err=True)
        raise typer.Exit(1)

    store = Store()
    llm = LLMClient(api_key=api_key, model=cfg.llm.model)

    connectors = []
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key:
        connectors.append(WebSearchConnector(api_key=serper_key, connector_type="funding_news"))
        connectors.append(WebSearchConnector(api_key=serper_key, connector_type="job_board"))
    else:
        typer.echo("Warning: SERPER_API_KEY not set — web search disabled", err=True)

    bigset_path = os.environ.get("BIGSET_EXPORT_PATH", "")
    if bigset_path and Path(bigset_path).exists():
        connectors.append(BigSetConnector(csv_path=bigset_path))

    if not connectors:
        typer.echo("Warning: no connectors active", err=True)

    return cfg, store, llm, connectors


@app.command()
def run(
    config: str = typer.Option("config.yaml", help="Path to config.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (no live API calls)"),
) -> None:
    """Run all pipeline stages: source → match → people-find → outreach → report."""
    cfg, store, llm, connectors = _build(config)

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

        typer.echo(f"[source] {rv_cfg.name} …")
        c = run_sourcing(
            role_variant=rv_cfg, role_variant_id=rv_id,
            connectors=connectors, llm=llm, store=store, config=cfg.sourcing,
        )
        typer.echo(f"  → {c['companies']} companies, {c['jobs']} jobs, {c['errors']} errors")

        typer.echo(f"[match]  {rv_cfg.name} …")
        c = run_matching(
            role_variant=rv_cfg, role_variant_id=rv_id,
            resume_text=resume_text, llm=llm, store=store, config=cfg.matching,
        )
        typer.echo(f"  → {c['scored']} scored, {c['errors']} errors")

    typer.echo("[people-find] …")
    apollo_key: Optional[str] = os.environ.get("APOLLO_API_KEY")
    c = run_people_finding(
        llm=llm, store=store, config=cfg.people_search,
        threshold=cfg.matching.score_threshold_for_outreach,
        apollo_api_key=apollo_key,
    )
    typer.echo(f"  → {c['found']} found, {c['not_found']} not found, {c['errors']} errors")

    typer.echo("[outreach] …")
    first_resume = resume_texts[cfg.role_variants[0].name] if resume_texts else ""
    c = run_outreach(
        llm=llm, store=store,
        threshold=cfg.matching.score_threshold_for_outreach,
        resume_summary=make_resume_summary(first_resume),
    )
    typer.echo(f"  → {c['drafted']} drafted, {c['errors']} errors")

    typer.echo("[report] …")
    paths = run_report(store)
    typer.echo(f"  → {paths['markdown']}")
    typer.echo(f"  → {paths['csv']}")
```

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS (smoke test + all unit tests from prior tasks).

- [ ] **Step 5: Verify the CLI entry point is wired up**

```bash
uv run job-agent --help
```

Expected: Shows `run` command and `--config` / `--dry-run` options.

- [ ] **Step 6: Update .gitignore for runtime artifacts**

Add these lines to `.gitignore`:

```
job_agent.db
reports/
resumes/
```

- [ ] **Step 7: Commit**

```bash
git add job_agent/cli.py tests/test_smoke.py .gitignore
git commit -m "feat: CLI — typer app, run command, pipeline orchestration, smoke test"
```

---

## Full test run

- [ ] **Run all tests and confirm green**

```bash
uv run pytest -v --tb=short
```

Expected: all tests from Tasks 2–14 PASS, 0 failures.

- [ ] **Final commit if any loose files**

```bash
git status
git add -A
git commit -m "chore: final cleanup — ensure all files committed"
```

---

## Usage quick-reference

```bash
# Set env vars
export OPENROUTER_API_KEY=sk-or-...
export SERPER_API_KEY=...                  # for web search
export BIGSET_EXPORT_PATH=exports/bigset.csv   # optional: BigSet CSV
export APOLLO_API_KEY=...                  # optional: email enrichment

# Place your resume(s) and configure config.yaml

# Run the full pipeline
uv run job-agent run

# Results written to reports/<timestamp>/report.md  +  matches.csv
```
