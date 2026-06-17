# job_agent/stages/resume_tailoring.py
import logging
from job_agent.config import RoleVariantConfig, MatchingConfig
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import resume_tailor_prompt
from job_agent.models import ResumeDraft
from job_agent.store import Store

logger = logging.getLogger(__name__)


def tailor_resume(
    llm: LLMClient,
    resume_text: str,
    role_variant: RoleVariantConfig,
    company_name: str,
    job_title: str | None,
    job_description: str | None,
    funding_signal: str | None,
) -> str:
    """Call LLM to produce a tailored resume markdown string."""
    system, user = resume_tailor_prompt(
        resume_text=resume_text,
        role_variant_keywords=role_variant.keywords,
        role_variant_seniority=role_variant.seniority,
        company_name=company_name,
        job_title=job_title,
        job_description=job_description,
        funding_signal=funding_signal,
    )
    return llm.call(system, user)


def run_resume_tailoring(
    llm: LLMClient,
    store: Store,
    role_variant: RoleVariantConfig,
    role_variant_id: int,
    resume_text: str,
    config: MatchingConfig,
) -> dict[str, int]:
    """Generate tailored resume variants for all matches above threshold that don't have one yet."""
    counts = {"tailored": 0, "errors": 0}
    threshold = config.score_threshold_for_outreach

    for match in store.get_matches_needing_resume_draft(threshold):
        # Only process matches belonging to this role variant
        if match.role_variant_id != role_variant_id:
            continue
        if llm.is_over_budget():
            break

        company = store.get_company(match.company_id)
        job = store.get_job(match.job_id) if match.job_id else None

        company_name = company.name if company else "Unknown"
        job_title = job.title if job else None
        job_description = job.raw_text if job else None
        funding_signal = company.raw_signal_text if company else None

        try:
            tailored = tailor_resume(
                llm=llm,
                resume_text=resume_text,
                role_variant=role_variant,
                company_name=company_name,
                job_title=job_title,
                job_description=job_description,
                funding_signal=funding_signal,
            )
            store.insert_resume_draft(ResumeDraft(
                match_id=match.id,
                role_variant_id=role_variant_id,
                company_name=company_name,
                job_title=job_title,
                tailored_text=tailored,
            ))
            counts["tailored"] += 1
            logger.info(f"[resume_tailoring] tailored for {company_name}")
        except LLMError as exc:
            logger.error(f"[resume_tailoring] match {match.id} ({company_name}): {exc}")
            counts["errors"] += 1

    return counts
