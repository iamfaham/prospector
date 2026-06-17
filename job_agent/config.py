from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel


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
