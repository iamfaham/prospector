from job_agent.config import RoleVariantConfig
from job_agent.models import RawResult


def sourcing_query_prompt(
    role_variant: RoleVariantConfig,
    connector_type: str,
    already_found: list[str],
    funding_lookback_days: int,
    today: str = "",
    cutoff_date: str = "",
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    already = ", ".join(already_found[-10:]) if already_found else "none yet"
    date_note = f" Today's date is {today}." if today else ""

    system = (
        "You generate precise Google search queries to find job opportunities for a "
        f"specific candidate profile.{date_note} Return ONLY the raw search query "
        "string — no explanation, no quotes around it."
    )

    year = today[:4] if today else "2026"
    since = f"since {cutoff_date}" if cutoff_date else f"in the last {funding_lookback_days} days"
    if connector_type == "funding_news":
        user = (
            f"Generate a Google search query to find startups that raised funding {since}, "
            f"likely to hire someone with: {keywords} ({role_variant.seniority}).\n\n"
            f"Already found (avoid): {already}\n\n"
            f"Be specific. Use site: or date filters to target recent results only. "
            f"Example style: 'site:techcrunch.com startup raises Series A {year} {role_variant.keywords[0]}'"
        )
    else:  # job_board
        kw0 = role_variant.keywords[0] if role_variant.keywords else "software engineer"
        user = (
            f"Generate a search query to find {role_variant.seniority} {kw0} job "
            f"openings at startups posted {since}. Skills: {keywords}.\n\n"
            f"Already found companies (try others): {already}\n\n"
            f"Example: 'site:wellfound.com \"{kw0}\" startup remote {year}'"
        )
    return system, user


def sourcing_extract_prompt(
    result: RawResult,
    role_variant: RoleVariantConfig,
    connector_type: str,
    funding_lookback_days: int,
    today: str = "",
    cutoff_date: str = "",
) -> tuple[str, str]:
    keywords = ", ".join(role_variant.keywords)
    if cutoff_date and today:
        date_rule = (
            f"HARD RULE: today is {today}. Any funding round or job posting dated "
            f"before {cutoff_date} is too old — set relevant=false immediately."
        )
    else:
        date_rule = (
            f"HARD RULE: only accept funding or postings from the last {funding_lookback_days} days. "
            f"Anything older — set relevant=false immediately."
        )
    system = (
        "You analyze search results to extract structured startup and job data. "
        f"Always return valid JSON. {date_rule}"
    )
    cutoff_display = f"on or after {cutoff_date}" if cutoff_date else f"within last {funding_lookback_days} days"
    user = (
        f"Analyze this search result and extract information.\n\n"
        f"Title: {result.title}\nURL: {result.url}\nSnippet: {result.snippet}\n\n"
        f"Target skills: {keywords} ({role_variant.seniority})\n"
        f"Source type: {'funding news' if connector_type == 'funding_news' else 'job board'}\n"
        f"Accepted date range: {cutoff_display} (reject anything older — set relevant=false).\n\n"
        f"Return JSON:\n"
        f'{{"relevant": true/false, '
        f'"company": {{"name": "...", "funding_stage": "...|null", "funding_amount": "...|null", "funding_date": "YYYY-MM|null"}} | null, '
        f'"job": {{"title": "...", "url": "{result.url}", "location": "...|null", "posted_at": "YYYY-MM-DD|null", "raw_text": "...|null"}} | null}}\n\n'
        f"Set relevant=false if: not a startup, dated before {cutoff_date or f'last {funding_lookback_days} days'}, or skills don't match."
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


def resume_tailor_latex_prompt(
    latex_src: str,
    role_variant_keywords: list[str],
    role_variant_seniority: str,
    company_name: str,
    job_title: str | None,
    job_description: str | None,
    funding_signal: str | None,
) -> tuple[str, str]:
    """Prompt that returns tailored LaTeX source — no markdown, no fences.

    Hard constraint: the output MUST compile to exactly ONE page.
    The input is already a one-pager, so only reword/reorder — never add content.
    """
    if job_title and job_description:
        context = f"Job title: {job_title}\n\nJob description:\n{job_description[:2500]}"
    elif job_title:
        context = f"Job title: {job_title}"
    elif funding_signal:
        context = f"Company signal (no JD): {funding_signal[:600]}"
    else:
        context = "No JD — tailor for a general senior engineering role."

    keywords = ", ".join(role_variant_keywords)
    system = (
        "You are an expert resume writer and LaTeX specialist. "
        "You tailor a candidate's one-page LaTeX resume for a specific opportunity.\n\n"
        "STRICT RULES — violating any rule makes the output unusable:\n"
        "1. Return ONLY the complete, compilable LaTeX source. No explanation, no ```latex fences.\n"
        "2. The output MUST fit on exactly ONE page when compiled — the input is already a "
        "one-pager, so do NOT add any new content, sections, or lines. Only reword or "
        "reorder existing content.\n"
        "3. Keep the document class, preamble, page geometry, font sizes, and margins identical.\n"
        "4. Do NOT change the candidate's name, contact details, company names, job titles, "
        "dates, or degree information.\n"
        "5. Do NOT reorder sections, experiences, or roles — every job must stay in exactly "
        "the same position as in the original. Only reword or reorder bullet points WITHIN "
        "a single role.\n"
        "6. You may tighten bullet point wording to save space — shorter is fine.\n"
        "7. Never fabricate experience, skills, or credentials the candidate does not have.\n"
        "8. Do NOT keyword-stuff — natural fit only."
    )
    user = (
        f"Tailor this one-page resume for a role at {company_name}.\n\n"
        f"Target: {role_variant_seniority} with expertise in {keywords}.\n\n"
        f"=== OPPORTUNITY ===\n{context}\n\n"
        f"=== LATEX SOURCE (one page — do not expand) ===\n{latex_src}\n\n"
        "Return the full tailored LaTeX source now. Must compile to exactly one page."
    )
    return system, user


def fix_latex_compile_error_prompt(
    latex_src: str,
    error_log: str,
) -> tuple[str, str]:
    """Prompt to fix a LaTeX source that failed to compile.

    Returns a corrected LaTeX source that should compile cleanly.
    """
    system = (
        "You are a LaTeX expert. A LaTeX resume failed to compile. "
        "Fix the compilation error and return the corrected LaTeX source.\n\n"
        "Rules:\n"
        "1. Return ONLY the complete corrected LaTeX — no explanation, no ```latex fences.\n"
        "2. Fix only what is causing the error; do not rewrite unrelated sections.\n"
        "3. Preserve all content, structure, and formatting exactly as given.\n"
        "4. The output must still fit on one page."
    )
    user = (
        f"The following LaTeX failed to compile.\n\n"
        f"=== PDFLATEX ERROR LOG ===\n{error_log}\n\n"
        f"=== LATEX SOURCE ===\n{latex_src}\n\n"
        "Return the fixed LaTeX source."
    )
    return system, user


def fix_latex_overflow_prompt(
    latex_src: str,
    page_count: int,
) -> tuple[str, str]:
    """Prompt to condense a LaTeX resume that compiled to more than one page.

    Returns a shorter LaTeX source that fits on one page.
    """
    system = (
        "You are an expert resume editor and LaTeX specialist. "
        f"A LaTeX resume compiled to {page_count} pages but must fit on ONE page.\n\n"
        "Rules:\n"
        "1. Return ONLY the complete condensed LaTeX — no explanation, no ```latex fences.\n"
        "2. Do NOT change the document class, preamble, page geometry, or font sizes.\n"
        "3. Do NOT remove entire sections or jobs — instead shorten bullet points.\n"
        "4. Trim the longest bullet points first: cut filler words, combine related points, "
        "or drop the least impactful bullet in each role (maximum one per role).\n"
        "5. Do NOT change the candidate's name, contact details, company names, job titles, "
        "dates, or degrees.\n"
        "6. Every remaining bullet must still be truthful and make sense."
    )
    user = (
        f"This resume compiled to {page_count} pages. Condense it to fit on ONE page.\n\n"
        f"=== LATEX SOURCE ===\n{latex_src}\n\n"
        "Return the condensed LaTeX source. Must compile to exactly one page."
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
        "STRICT RULES: never invent experience the candidate does not have. "
        "Never reorder sections, jobs, or roles — every experience must remain in exactly "
        "the same order as the original. Only reword or reorder bullet points within a single role."
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
