# job_agent/stages/matching.py
import logging
from typing import Optional
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
