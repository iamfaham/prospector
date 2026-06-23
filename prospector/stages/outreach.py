# prospector/stages/outreach.py
import logging
from typing import Optional
from prospector.llm.client import LLMClient, LLMError
from prospector.llm.prompts import draft_message_prompt
from prospector.models import DraftType, OutreachDraft
from prospector.store import Store

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
