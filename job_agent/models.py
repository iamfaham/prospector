from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MatchStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


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


@dataclass
class ResumeDraft:
    match_id: int
    role_variant_id: int
    company_name: str
    job_title: Optional[str]
    tailored_text: str   # full markdown: ## Key Changes + ## Tailored Resume
    id: Optional[int] = None
    generated_at: str = field(default_factory=_now)
