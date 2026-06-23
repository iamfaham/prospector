# job_agent/stages/matching.py
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from job_agent.config import RoleVariantConfig, MatchingConfig
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import score_match_prompt
from job_agent.models import Match
from job_agent.store import Store

logger = logging.getLogger(__name__)

_MAX_WORKERS = 5


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
    lock = threading.Lock()

    companies = store.get_unscored_companies(role_variant_id)
    jobs = store.get_unscored_jobs(role_variant_id)

    def _score_company(company):
        ctx = (
            f"Company: {company.name}\n"
            f"Funding: {company.funding_stage or 'unknown'} {company.funding_amount or ''}\n"
            f"Signal: {company.raw_signal_text or '(none)'}"
        )
        result = score_match(llm, resume_text, role_variant, ctx)
        return Match(
            role_variant_id=role_variant_id,
            company_id=company.id,
            job_id=None,
            score=result["score"],
            reasoning=result["reasoning"],
        )

    def _score_job(job):
        ctx = (
            f"Job: {job.title}\n"
            f"URL: {job.url}\n"
            f"Description: {job.raw_text or '(none)'}"
        )
        result = score_match(llm, resume_text, role_variant, ctx)
        return Match(
            role_variant_id=role_variant_id,
            company_id=job.company_id,
            job_id=job.id,
            score=result["score"],
            reasoning=result["reasoning"],
        )

    items: list[tuple] = (
        [("company", c, lambda c=c: _score_company(c)) for c in companies]
        + [("job", j, lambda j=j: _score_job(j)) for j in jobs]
    )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(fn): (kind, item)
            for kind, item, fn in items
            if not llm.is_over_budget()
        }

        for future in as_completed(futures):
            kind, item = futures[future]
            label = item.name if kind == "company" else item.url
            try:
                match = future.result()
                store.insert_match(match)
                with lock:
                    counts["scored"] += 1
                snippet = (match.reasoning or "")[:70]
                logger.info("[matching] %s: %d/10 — %s", label, match.score, snippet)
            except LLMError as exc:
                logger.error("[matching] FAILED %s: %s", label, exc)
                with lock:
                    counts["errors"] += 1

    return counts
