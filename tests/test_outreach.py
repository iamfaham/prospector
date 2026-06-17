# tests/test_outreach.py
import pytest
from unittest.mock import MagicMock
from job_agent.stages.outreach import run_outreach, draft_message
from job_agent.store import Store
from job_agent.llm.client import LLMClient, LLMError
from job_agent.models import Company, RoleVariant, Match, Contact, Job, DraftType


def _populated_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       raw_signal_text="Raised $5M Seed"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="strong match"))
    return store, cid


def test_drafts_cold_outreach(tmp_path):
    store, cid = _populated_store(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.return_value = "Hi, I saw Acme raised $5M..."
    counts = run_outreach(llm, store, threshold=7, resume_summary="5 years Python")
    assert counts["drafted"] == 1
    rows = store.get_all_for_report()
    assert any(r.get("message_text") for r in rows)


def test_drafts_application_blurb_when_job_present(tmp_path):
    store, cid = _populated_store(tmp_path)
    jid = store.upsert_job(Job(title="Backend Eng", url="https://a.com/j/1", company_id=cid))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be2", resume_path="r.txt", keywords=[], seniority="mid")
    )
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, job_id=jid, score=9, reasoning="perfect"))
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.return_value = "I'm writing about the Backend Eng role..."
    counts = run_outreach(llm, store, threshold=7, resume_summary="5 years Python")
    assert counts["drafted"] >= 1


def test_handles_llm_error_gracefully(tmp_path):
    store, cid = _populated_store(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.side_effect = LLMError("API down")
    counts = run_outreach(llm, store, threshold=7, resume_summary="resume")
    assert counts["errors"] == 1
    assert counts["drafted"] == 0


def test_draft_message_returns_string():
    llm = MagicMock(spec=LLMClient)
    llm.call.return_value = "Hi Alice, I saw Acme raised..."
    result = draft_message(llm, "Acme", None, "Raised $5M", "Alice", "CTO", "strong Python", "5yr Python")
    assert isinstance(result, str) and "Alice" in result
