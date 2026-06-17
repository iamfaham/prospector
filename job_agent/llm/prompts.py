from job_agent.config import RoleVariantConfig
from job_agent.models import RawResult


def sourcing_query_prompt(
    role_variant: RoleVariantConfig,
    connector_type: str,
    already_found: list[str],
    funding_lookback_days: int,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    already = ", ".join(already_found[-10:]) if already_found else "none yet"

    system = (
        "You generate precise Google search queries to find job opportunities for a "
        "specific candidate profile. Return ONLY the raw search query string — no "
        "explanation, no quotes around it."
    )

    if connector_type == "funding_news":
        user = (
            f"Generate a Google search query to find startups that raised funding in "
            f"the last {funding_lookback_days} days, likely to hire someone with: "
            f"{keywords} ({role_variant.seniority}).\n\n"
            f"Already found (avoid): {already}\n\n"
            f"Be specific. Use site: or date filters where useful. "
            f"Example style: 'site:techcrunch.com startup raises Series A 2026 {role_variant.keywords[0]}'"
        )
    else:  # job_board
        kw0 = role_variant.keywords[0] if role_variant.keywords else "software engineer"
        user = (
            f"Generate a search query to find {role_variant.seniority} {kw0} job "
            f"openings at startups. Skills: {keywords}.\n\n"
            f"Already found companies (try others): {already}\n\n"
            f"Example: 'site:wellfound.com \"{kw0}\" startup remote 2026'"
        )
    return system, user


def sourcing_extract_prompt(
    result: RawResult,
    role_variant: RoleVariantConfig,
    connector_type: str,
    funding_lookback_days: int,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    system = (
        "You analyze search results to extract structured startup and job data. "
        "Always return valid JSON. Be strict about recency."
    )
    user = (
        f"Analyze this search result and extract information.\n\n"
        f"Title: {result.title}\nURL: {result.url}\nSnippet: {result.snippet}\n\n"
        f"Target skills: {keywords} ({role_variant.seniority})\n"
        f"Source type: {'funding news' if connector_type == 'funding_news' else 'job board'}\n"
        f"Max age: {funding_lookback_days} days\n\n"
        f"Return JSON:\n"
        f'{{"relevant": true/false, '
        f'"company": {{"name": "...", "funding_stage": "...|null", "funding_amount": "...|null", "funding_date": "YYYY-MM|null"}} | null, '
        f'"job": {{"title": "...", "url": "{result.url}", "location": "...|null", "posted_at": "YYYY-MM-DD|null", "raw_text": "...|null"}} | null}}\n\n'
        f"Set relevant=false if: not a startup, funding older than {funding_lookback_days} days, "
        f"or skills don't match."
    )
    return system, user


def score_match_prompt(
    resume_text: str,
    role_variant: RoleVariantConfig,
    context: str,
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    system = "You score job-candidate fit 0-10. Always return valid JSON."
    user = (
        f"Score this opportunity for the candidate (0=no fit, 10=perfect).\n\n"
        f"=== RESUME ===\n{resume_text[:3000]}\n\n"
        f"=== TARGET PROFILE ===\nKeywords: {keywords}\nSeniority: {role_variant.seniority}\n\n"
        f"=== OPPORTUNITY ===\n{context}\n\n"
        f'Return JSON: {{"score": <0-10 integer>, "reasoning": "<2-3 sentences>"}}'
    )
    return system, user


def people_search_query_prompt(
    company_name: str,
    attempt: int,
    previous_queries: list[str],
) -> tuple[str, str]:
    previous = "\n".join(f"- {q}" for q in previous_queries) if previous_queries else "none"
    system = (
        "You generate Google search queries to find the right person to contact "
        "at a startup for job opportunities. Return ONLY the raw search query string."
    )
    user = (
        f"Generate a query to find the founder, CTO, VP Engineering, or hiring manager "
        f"at '{company_name}'.\n\nPrevious queries:\n{previous}\n\n"
        f"Attempt {attempt + 1}. {'Use a different angle than previous queries.' if attempt > 0 else ''}\n\n"
        f"Example styles:\n"
        f"- '{company_name} founder CEO LinkedIn'\n"
        f"- '{company_name} CTO site:linkedin.com'\n"
        f"- '{company_name} \"head of engineering\" contact email'"
    )
    return system, user


def people_verify_prompt(
    results: list[RawResult],
    company_name: str,
) -> tuple[str, str]:
    snippets = "\n\n".join(
        f"[{i+1}] {r.title}\n{r.url}\n{r.snippet}"
        for i, r in enumerate(results[:5])
    )
    system = "You extract contact information from search results. Always return valid JSON."
    user = (
        f"Find the best person to reach out to at '{company_name}' about job "
        f"opportunities. Prefer founder > CTO > VP Eng > Eng Manager.\n\n"
        f"{snippets}\n\n"
        f'Return JSON: {{"found": true/false, "name": "...|null", "title": "...|null", "profile_url": "...|null"}}\n'
        f"Set found=false if no result clearly identifies a real person at this company."
    )
    return system, user


def resume_tailor_prompt(
    resume_text: str,
    role_variant_keywords: list[str],
    role_variant_seniority: str,
    company_name: str,
    job_title: str | None,
    job_description: str | None,
    funding_signal: str | None,
) -> tuple[str, str]:
    context = ""
    if job_title and job_description:
        context = f"Job title: {job_title}\n\nJob description:\n{job_description[:2000]}"
    elif job_title:
        context = f"Job title: {job_title}"
    elif funding_signal:
        context = f"Company signal (no JD available): {funding_signal[:500]}"
    else:
        context = "No JD available — tailor for a general role matching the keywords."

    keywords = ", ".join(role_variant_keywords)
    system = (
        "You are an expert resume editor. Given a candidate's resume and a specific job "
        "opportunity, you produce a tailored resume that maximises fit. "
        "Return ONLY valid markdown with exactly two sections: "
        "'## Key Changes' (bullet list of what you changed and why) and "
        "'## Tailored Resume' (the full tailored resume text, ready to copy-paste). "
        "Never invent experience the candidate does not have."
    )
    user = (
        f"Tailor this resume for a role at {company_name}.\n\n"
        f"Target profile: {role_variant_seniority} with skills in {keywords}.\n\n"
        f"=== OPPORTUNITY ===\n{context}\n\n"
        f"=== RESUME ===\n{resume_text[:4000]}\n\n"
        "Return the two-section markdown now."
    )
    return system, user


def draft_message_prompt(
    company_name: str,
    job_title: str | None,
    funding_signal: str | None,
    contact_name: str | None,
    contact_title: str | None,
    score_reasoning: str,
    resume_summary: str,
) -> tuple[str, str]:
    greeting = f"Hi {contact_name.split()[0]}," if contact_name else "Hi,"
    recipient = (
        f"to {contact_name} ({contact_title}) at" if contact_name and contact_title
        else "to the team at"
    )
    if job_title:
        angle = f"I'm reaching out about the {job_title} role"
        style = "application blurb"
    elif funding_signal:
        angle = "Congratulations on your recent funding! I wanted to reach out"
        style = "cold outreach referencing funding"
    else:
        angle = "I wanted to reach out"
        style = "general cold outreach"

    system = (
        f"You write concise, personalized {style} messages for job outreach. "
        "First person, professional but warm, max 150 words. No 'I hope this message "
        "finds you well' or other filler. Never invent facts beyond what you're given."
    )
    user = (
        f"Write a cold outreach message {recipient} {company_name}.\n\n"
        f"{greeting}\n\n"
        f"Angle: {angle}.\n"
        f"Why good fit: {score_reasoning}\n"
        f"Candidate summary: {resume_summary}\n"
        f"Context: {funding_signal or 'N/A'}\n\n"
        "Write the full message text only (no subject line). Start with the greeting above."
    )
    return system, user
