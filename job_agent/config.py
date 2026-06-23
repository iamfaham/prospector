from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel


class RoleVariantConfig(BaseModel):
    name: str
    resume: str                           # path to PDF/txt used for text extraction & scoring
    keywords: list[str]
    seniority: str
    resume_latex: Optional[str] = None    # path to .tex source; enables PDF/DOCX tailoring output


class SourcingConfig(BaseModel):
    max_queries_per_role_per_run: int = 8
    funding_lookback_days: int = 30


class MatchingConfig(BaseModel):
    score_threshold_for_outreach: int = 7


class LLMConfig(BaseModel):
    provider: str = "openrouter"
    model: str = "anthropic/claude-sonnet-4-5"
    max_calls: int = 1000


class PeopleSearchConfig(BaseModel):
    paid_api: Optional[str] = None  # "apollo" | None


class Config(BaseModel):
    candidate_name: str = "candidate"     # used in output filenames
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
