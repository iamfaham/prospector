# job_agent/stages/resume_tailoring.py
import logging
from pathlib import Path

from job_agent.config import MatchingConfig, RoleVariantConfig
from job_agent.llm.client import LLMClient, LLMError
from job_agent.llm.prompts import resume_tailor_latex_prompt, resume_tailor_prompt
from job_agent.models import ResumeDraft
from job_agent.store import Store

logger = logging.getLogger(__name__)


def _read_latex(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def tailor_resume(
    llm: LLMClient,
    resume_text: str,
    role_variant: RoleVariantConfig,
    company_name: str,
    job_title: str | None,
    job_description: str | None,
    funding_signal: str | None,
    latex_mode: bool = False,
) -> str:
    """Call LLM to produce a tailored resume.

    When *latex_mode* is True the resume_text is LaTeX source and the LLM
    returns compilable LaTeX.  Otherwise it returns a two-section markdown
    document (## Key Changes / ## Tailored Resume).
    """
    if latex_mode:
        system, user = resume_tailor_latex_prompt(
            latex_src=resume_text,
            role_variant_keywords=role_variant.keywords,
            role_variant_seniority=role_variant.seniority,
            company_name=company_name,
            job_title=job_title,
            job_description=job_description,
            funding_signal=funding_signal,
        )
    else:
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
    """Generate tailored resume variants for all matches above threshold.

    If ``role_variant.resume_latex`` points to a .tex file, the LLM returns
    tailored LaTeX which is later compiled to PDF and DOCX by run_report.
    Otherwise the LLM returns markdown (## Key Changes / ## Tailored Resume).

    Idempotent: matches that already have a resume_draft are skipped.
    """
    counts = {"tailored": 0, "errors": 0}
    threshold = config.score_threshold_for_outreach

    # Decide mode once per role variant
    latex_src: str | None = None
    if role_variant.resume_latex:
        try:
            latex_src = _read_latex(role_variant.resume_latex)
        except OSError as exc:
            logger.warning("[resume_tailoring] cannot read %s: %s", role_variant.resume_latex, exc)

    for match in store.get_matches_needing_resume_draft(threshold):
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
            source = latex_src if latex_src is not None else resume_text
            tailored = tailor_resume(
                llm=llm,
                resume_text=source,
                role_variant=role_variant,
                company_name=company_name,
                job_title=job_title,
                job_description=job_description,
                funding_signal=funding_signal,
                latex_mode=latex_src is not None,
            )
            store.insert_resume_draft(ResumeDraft(
                match_id=match.id,
                role_variant_id=role_variant_id,
                company_name=company_name,
                job_title=job_title,
                tailored_text=tailored,
            ))
            counts["tailored"] += 1
            logger.info("[resume_tailoring] tailored for %s", company_name)
        except LLMError as exc:
            logger.error("[resume_tailoring] match %s (%s): %s", match.id, company_name, exc)
            counts["errors"] += 1

    return counts
