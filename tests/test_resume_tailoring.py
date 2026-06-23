# tests/test_resume_tailoring.py
"""Tests for resume tailoring stage and prompt."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_agent.config import MatchingConfig, RoleVariantConfig
from job_agent.llm.prompts import resume_tailor_prompt
from job_agent.models import Company, Job, Match, MatchStatus, ResumeDraft
from job_agent.stages.resume_tailoring import run_resume_tailoring, tailor_resume
from job_agent.store import Store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    return Store(db_path=str(tmp_path / "test.db"))


@pytest.fixture()
def role_variant_cfg():
    return RoleVariantConfig(
        name="backend-eng",
        resume="resumes/test.txt",
        keywords=["python", "go", "backend"],
        seniority="mid-senior",
    )


@pytest.fixture()
def matching_cfg():
    return MatchingConfig(score_threshold_for_outreach=7)


@pytest.fixture()
def seeded_store(store, role_variant_cfg):
    """Store with one company, one job, one high-scoring match."""
    from job_agent.models import RoleVariant
    rv = RoleVariant(
        name=role_variant_cfg.name,
        resume_path=role_variant_cfg.resume,
        keywords=role_variant_cfg.keywords,
        seniority=role_variant_cfg.seniority,
    )
    rv_id = store.upsert_role_variant(rv)

    company = Company(name="AcmeCorp", source_url="https://acme.example.com")
    company_id = store.upsert_company(company)

    job = Job(title="Senior Backend Engineer", url="https://acme.example.com/jobs/1",
              company_id=company_id, raw_text="We need Python/Go expertise.")
    job_id = store.upsert_job(job)

    match = Match(
        role_variant_id=rv_id, company_id=company_id, job_id=job_id,
        score=8, reasoning="Strong match on Python and Go experience.",
    )
    mid = store.insert_match(match)
    store.update_match_status(mid, MatchStatus.ACCEPTED)

    return store, rv_id


# ── Prompt tests ───────────────────────────────────────────────────────────────

def test_resume_tailor_prompt_with_jd():
    system, user = resume_tailor_prompt(
        resume_text="John Doe — Python developer with 5 years experience.",
        role_variant_keywords=["python", "go"],
        role_variant_seniority="mid-senior",
        company_name="AcmeCorp",
        job_title="Senior Backend Engineer",
        job_description="We need Python/Go expertise. Must know distributed systems.",
        funding_signal=None,
    )
    assert "AcmeCorp" in user
    assert "Senior Backend Engineer" in user
    assert "distributed systems" in user
    assert "## Key Changes" in system
    assert "## Tailored Resume" in system


def test_resume_tailor_prompt_without_jd_uses_funding_signal():
    _, user = resume_tailor_prompt(
        resume_text="Jane Smith — Go engineer.",
        role_variant_keywords=["go"],
        role_variant_seniority="senior",
        company_name="FundedStartup",
        job_title=None,
        job_description=None,
        funding_signal="Raised Series A $10M to build developer tools.",
    )
    assert "Series A" in user
    assert "FundedStartup" in user


def test_resume_tailor_prompt_no_context_fallback():
    _, user = resume_tailor_prompt(
        resume_text="Resume text here.",
        role_variant_keywords=["python"],
        role_variant_seniority="junior",
        company_name="SteathCo",
        job_title=None,
        job_description=None,
        funding_signal=None,
    )
    assert "No JD available" in user


# ── tailor_resume unit test ────────────────────────────────────────────────────

def test_tailor_resume_calls_llm(role_variant_cfg):
    llm = MagicMock()
    llm.call.return_value = "## Key Changes\n- Highlighted Python\n\n## Tailored Resume\nJohn Doe..."

    result = tailor_resume(
        llm=llm,
        resume_text="John Doe Python engineer",
        role_variant=role_variant_cfg,
        company_name="AcmeCorp",
        job_title="Backend Engineer",
        job_description="Need Python",
        funding_signal=None,
    )

    assert llm.call.called
    assert "## Key Changes" in result


# ── run_resume_tailoring integration test ────────────────────────────────────

def test_run_resume_tailoring_writes_to_store(seeded_store, role_variant_cfg, matching_cfg):
    store, rv_id = seeded_store
    llm = MagicMock()
    llm.is_over_budget.return_value = False
    llm.call.return_value = (
        "## Key Changes\n- Emphasised Python and Go\n\n## Tailored Resume\nJohn Doe..."
    )

    counts = run_resume_tailoring(
        llm=llm,
        store=store,
        role_variant=role_variant_cfg,
        role_variant_id=rv_id,
        resume_text="John Doe Python/Go engineer",
        config=matching_cfg,
    )

    assert counts["tailored"] == 1
    assert counts["errors"] == 0
    # Should not re-tailor on second run (idempotent)
    counts2 = run_resume_tailoring(
        llm=llm,
        store=store,
        role_variant=role_variant_cfg,
        role_variant_id=rv_id,
        resume_text="John Doe Python/Go engineer",
        config=matching_cfg,
    )
    assert counts2["tailored"] == 0


def test_run_resume_tailoring_skips_below_threshold(store, role_variant_cfg, matching_cfg):
    from job_agent.models import RoleVariant
    rv = RoleVariant(name=role_variant_cfg.name, resume_path=role_variant_cfg.resume,
                     keywords=role_variant_cfg.keywords, seniority=role_variant_cfg.seniority)
    rv_id = store.upsert_role_variant(rv)

    company = Company(name="LowScoreCo", source_url="https://low.example.com")
    company_id = store.upsert_company(company)
    match = Match(role_variant_id=rv_id, company_id=company_id, job_id=None,
                  score=4, reasoning="Poor fit.")
    store.insert_match(match)

    llm = MagicMock()
    llm.is_over_budget.return_value = False

    counts = run_resume_tailoring(
        llm=llm, store=store, role_variant=role_variant_cfg,
        role_variant_id=rv_id, resume_text="Resume text",
        config=matching_cfg,
    )
    assert counts["tailored"] == 0
    assert not llm.call.called


def test_run_resume_tailoring_stops_when_over_budget(seeded_store, role_variant_cfg, matching_cfg):
    store, rv_id = seeded_store
    llm = MagicMock()
    llm.is_over_budget.return_value = True

    counts = run_resume_tailoring(
        llm=llm, store=store, role_variant=role_variant_cfg,
        role_variant_id=rv_id, resume_text="Resume",
        config=matching_cfg,
    )
    assert counts["tailored"] == 0
    assert not llm.call.called
