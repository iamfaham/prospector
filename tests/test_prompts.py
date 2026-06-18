from job_agent.llm.prompts import (
    sourcing_query_prompt,
    sourcing_extract_prompt,
    score_match_prompt,
    people_search_query_prompt,
    people_verify_prompt,
    draft_message_prompt,
    resume_tailor_latex_prompt,
)
from job_agent.config import RoleVariantConfig
from job_agent.models import RawResult

RV = RoleVariantConfig(name="be", resume="r.txt", keywords=["python", "go"], seniority="mid-senior")
RESULT = RawResult(url="https://tc.com/a", title="Acme raises $5M", snippet="Acme AI raised $5M Seed")

def test_sourcing_query_prompt_returns_tuple():
    system, user = sourcing_query_prompt(RV, "funding_news", [], 30)
    assert isinstance(system, str) and len(system) > 10
    assert "python" in user or "go" in user

def test_sourcing_query_prompt_job_board():
    system, user = sourcing_query_prompt(RV, "job_board", ["Acme"], 30)
    assert isinstance(system, str) and isinstance(user, str)

def test_sourcing_extract_prompt_returns_tuple():
    system, user = sourcing_extract_prompt(RESULT, RV, "funding_news", 30)
    assert "json" in system.lower() or "JSON" in system
    assert RESULT.title in user

def test_score_match_prompt_contains_resume():
    system, user = score_match_prompt("My resume text", RV, "Company: Acme\nFunding: Seed")
    assert "My resume text" in user
    assert "score" in user.lower() or "0-10" in user

def test_people_search_query_prompt():
    system, user = people_search_query_prompt("Acme AI", 0, [])
    assert "Acme AI" in user
    assert isinstance(system, str)

def test_people_verify_prompt():
    results = [RESULT]
    system, user = people_verify_prompt(results, "Acme AI")
    assert "Acme AI" in user
    assert "json" in system.lower() or "JSON" in system

def test_draft_message_prompt_with_contact():
    system, user = draft_message_prompt(
        company_name="Acme AI",
        job_title="Backend Engineer",
        funding_signal="Raised $5M Seed",
        contact_name="Alice Smith",
        contact_title="CTO",
        score_reasoning="Strong Python background",
        resume_summary="5 years Python, Go, distributed systems",
    )
    assert "Alice" in user or "Alice" in system
    assert "Acme AI" in user

def test_resume_tailor_latex_prompt_with_jd():
    system, user = resume_tailor_latex_prompt(
        latex_src=r"\documentclass{article}\begin{document}John Doe\end{document}",
        role_variant_keywords=["python", "go"],
        role_variant_seniority="mid-senior",
        company_name="AcmeCorp",
        job_title="Senior Backend Engineer",
        job_description="Must know distributed systems and Python.",
        funding_signal=None,
    )
    assert "AcmeCorp" in user
    assert "Senior Backend Engineer" in user
    assert "distributed systems" in user
    # System must instruct LaTeX-only output
    assert "LaTeX" in system
    assert "fabricate" in system.lower() or "invent" in system.lower() or "never" in system.lower()


def test_resume_tailor_latex_prompt_funding_fallback():
    _, user = resume_tailor_latex_prompt(
        latex_src=r"\documentclass{article}\begin{document}Resume\end{document}",
        role_variant_keywords=["go"],
        role_variant_seniority="senior",
        company_name="FundedCo",
        job_title=None,
        job_description=None,
        funding_signal="Raised $20M Series B for API infrastructure.",
    )
    assert "Series B" in user
    assert "FundedCo" in user


def test_draft_message_prompt_without_contact():
    system, user = draft_message_prompt(
        company_name="Acme AI",
        job_title=None,
        funding_signal="Raised $5M Seed",
        contact_name=None,
        contact_title=None,
        score_reasoning="Strong match",
        resume_summary="5 years Python",
    )
    assert "Acme AI" in user
    assert isinstance(system, str)
