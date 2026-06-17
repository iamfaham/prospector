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
            # SQLite UNIQUE treats NULL as distinct, so handle job_id=None dedup manually
            if match.job_id is None:
                existing = conn.execute(
                    """SELECT id FROM matches
                       WHERE role_variant_id = ? AND company_id = ? AND job_id IS NULL""",
                    (match.role_variant_id, match.company_id),
                ).fetchone()
                if existing:
                    return None
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
