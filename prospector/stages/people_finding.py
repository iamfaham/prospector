# prospector/stages/people_finding.py
import logging
import os
from typing import Optional
from urllib.parse import urlparse

import httpx

from prospector.config import PeopleSearchConfig
from prospector.llm.client import LLMClient, LLMError
from prospector.llm.prompts import people_search_query_prompt, people_verify_prompt
from prospector.models import Contact, Confidence
from prospector.store import Store
from prospector.connectors.web_search import WebSearchConnector

logger = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3

_SENIOR_TITLES = ["ceo", "cto", "founder", "co-founder", "vp", "head of", "chief"]


def run_people_finding(
    llm: LLMClient,
    store: Store,
    config: PeopleSearchConfig,
    threshold: int,
    apollo_api_key: Optional[str] = None,
    skrapp_api_key: Optional[str] = None,
) -> dict[str, int]:
    counts = {"found": 0, "not_found": 0, "errors": 0}

    for match in store.get_matches_above_threshold(threshold):
        if store.get_contact_for_company(match.company_id):
            continue

        company = store.get_company(match.company_id)
        if not company:
            continue

        try:
            contact = _find_person(
                llm=llm,
                company_name=company.name,
                source_url=company.source_url or "",
                use_skrapp=bool(skrapp_api_key),
                use_apollo=bool(apollo_api_key),
                skrapp_api_key=skrapp_api_key or "",
                apollo_api_key=apollo_api_key or "",
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
    source_url: str,
    use_skrapp: bool,
    use_apollo: bool,
    skrapp_api_key: str,
    apollo_api_key: str,
) -> Optional[Contact]:
    # 1. Skrapp domain search — most direct, gives verified email
    if use_skrapp:
        domain = _extract_domain(source_url)
        if domain:
            contact = _find_via_skrapp(domain, skrapp_api_key)
            if contact:
                logger.info("[people_finding] skrapp hit: %s at %s", contact.name, domain)
                return contact

    # 2. Apollo people search — good profile data, email may be null
    if use_apollo:
        contact = _find_via_apollo(company_name, apollo_api_key)
        if contact:
            logger.info("[people_finding] apollo hit: %s at %s", contact.name, company_name)
            return contact

    # 3. Web search + LLM fallback
    return _find_via_web_search(llm, company_name)


def _find_via_skrapp(domain: str, api_key: str) -> Optional[Contact]:
    try:
        resp = httpx.get(
            "https://api.skrapp.io/api/v2/domains/search",
            params={"domain": domain},
            headers={"X-Access-Key": api_key},
            timeout=10.0,
        )
        resp.raise_for_status()
        emails = resp.json().get("emails", [])
        if not emails:
            return None
        # Prefer senior titles; fall back to first result
        best = next(
            (p for p in emails if any(t in (p.get("title") or "").lower() for t in _SENIOR_TITLES)),
            emails[0],
        )
        return Contact(
            company_id=0,
            name=best.get("name") or "Unknown",
            title=best.get("title") or "Unknown",
            email=best.get("email"),
            confidence=Confidence.HIGH,
            found_via="skrapp",
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (402, 429):
            logger.warning("[people_finding] skrapp credits exhausted — falling back")
        else:
            logger.warning("[people_finding] skrapp error for %s: %s", domain, exc)
        return None
    except Exception as exc:
        logger.warning("[people_finding] skrapp error for %s: %s", domain, exc)
        return None


def _find_via_apollo(company_name: str, api_key: str) -> Optional[Contact]:
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
        if not people:
            return None
        p = people[0]
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or "Unknown"
        email = p.get("email")
        return Contact(
            company_id=0,
            name=name,
            title=p.get("title") or "Unknown",
            profile_url=p.get("linkedin_url"),
            email=email,
            confidence=Confidence.HIGH if email else Confidence.MEDIUM,
            found_via="apollo",
        )
    except Exception as exc:
        logger.warning("[people_finding] apollo error for %s: %s", company_name, exc)
        return None


def _find_via_web_search(llm: LLMClient, company_name: str) -> Optional[Contact]:
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_key:
        logger.warning("[people_finding] TAVILY_API_KEY not set, skipping web search")
        return None

    searcher = WebSearchConnector(api_key=tavily_key, connector_type="funding_news")
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

            return Contact(
                company_id=0,
                name=person["name"],
                title=person.get("title") or "Unknown",
                profile_url=person.get("profile_url"),
                confidence=Confidence.MEDIUM,
                found_via="web_search",
            )
        except LLMError as exc:
            logger.error(f"[people_finding] attempt {attempt+1} LLM error: {exc}")

    return None


def _extract_domain(url: str) -> str:
    """Extract bare domain from a URL. 'https://www.acme.com/about' -> 'acme.com'"""
    try:
        netloc = urlparse(url).netloc
        # Strip www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""
