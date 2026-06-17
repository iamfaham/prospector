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
