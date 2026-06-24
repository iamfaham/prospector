# prospector/stages/sourcing.py
import logging
from datetime import datetime, timedelta, timezone
from prospector.config import RoleVariantConfig, SourcingConfig
from prospector.connectors.base import SourceConnector
from prospector.llm.client import LLMClient, LLMError
from prospector.llm.prompts import sourcing_query_prompt, sourcing_extract_prompt
from prospector.models import Company, Job
from prospector.store import Store

logger = logging.getLogger(__name__)


def run_sourcing(
    role_variant: RoleVariantConfig,
    role_variant_id: int,
    connectors: list[SourceConnector],
    llm: LLMClient,
    store: Store,
    config: SourcingConfig,
    today: str = "",
    since_date: str = "",
) -> dict[str, int]:
    """Agentic sourcing loop. Returns {"companies": N, "jobs": N, "errors": N}."""
    counts = {"companies": 0, "jobs": 0, "errors": 0}
    found_names: list[str] = []
    new_this_run = 0

    if since_date:
        cutoff_date = since_date
    else:
        cutoff_date = (
            datetime.now(timezone.utc) - timedelta(days=config.funding_lookback_days)
        ).strftime("%Y-%m-%d")

    for connector in connectors:
        if new_this_run >= config.max_new_per_run:
            break
        ctype = connector.connector_type

        for i in range(config.max_queries_per_role_per_run):
            if new_this_run >= config.max_new_per_run:
                logger.info(f"[sourcing] reached {config.max_new_per_run} new companies — stopping")
                break
            if llm.is_over_budget():
                logger.warning("[sourcing] LLM budget exhausted")
                break

            try:
                sys_p, usr_p = sourcing_query_prompt(
                    role_variant, ctype, found_names, config.funding_lookback_days, today, cutoff_date
                )
                query = llm.call(sys_p, usr_p).strip().strip("\"'")
                logger.info(f"[sourcing] {ctype} query {i+1}: {query}")

                results = connector.search(query)

                for result in results:
                    if new_this_run >= config.max_new_per_run or llm.is_over_budget():
                        break
                    try:
                        sys_e, usr_e = sourcing_extract_prompt(
                            result, role_variant, ctype, config.funding_lookback_days, today, cutoff_date
                        )
                        extracted = llm.call_json(sys_e, usr_e)

                        if not extracted.get("relevant"):
                            continue

                        co_data = extracted.get("company")
                        if co_data and co_data.get("name"):
                            name = co_data["name"]
                            is_fresh = not store.is_company_known(
                                name, within_days=config.company_freshness_days
                            )
                            company = Company(
                                name=name,
                                source_url=result.url,
                                funding_stage=co_data.get("funding_stage"),
                                funding_amount=co_data.get("funding_amount"),
                                funding_date=co_data.get("funding_date"),
                                raw_signal_text=result.snippet,
                            )
                            company_id = store.upsert_company(company)
                            if name not in found_names:
                                found_names.append(name)
                                counts["companies"] += 1
                                if is_fresh:
                                    new_this_run += 1

                            job_data = extracted.get("job")
                            if job_data and job_data.get("title") and job_data.get("url"):
                                job = Job(
                                    company_id=company_id,
                                    title=job_data["title"],
                                    url=job_data["url"],
                                    location=job_data.get("location"),
                                    posted_at=job_data.get("posted_at"),
                                    raw_text=job_data.get("raw_text"),
                                )
                                store.upsert_job(job)
                                counts["jobs"] += 1

                    except LLMError as exc:
                        logger.error(f"[sourcing] LLM error for {result.url}: {exc}")
                        counts["errors"] += 1

            except Exception as exc:
                logger.error(f"[sourcing] connector error (query {i+1}): {exc}")
                counts["errors"] += 1

    return counts
