# tests/test_matching.py
import pytest
from unittest.mock import MagicMock
from job_agent.stages.matching import run_matching, score_match
from job_agent.store import Store
from job_agent.llm.client import LLMClient, LLMError
from job_agent.config import RoleVariantConfig, MatchingConfig
from job_agent.models import Company, Job, RoleVariant

RV_CFG = RoleVariantConfig(name="be", resume="r.txt", keywords=["python"], seniority="mid")
RESUME = "5 years Python backend engineer"


def _store_with_company(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv = RoleVariant(name="be", resume_path="r.txt", keywords=["python"], seniority="mid")
    rv_id = store.upsert_role_variant(rv)
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       funding_stage="Seed", raw_signal_text="Raised $5M"))
    return store, rv_id, cid


def _mock_llm(score=8, reasoning="good fit"):
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call_json.return_value = {"score": score, "reasoning": reasoning}
    return llm


def test_run_matching_scores_company(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = _mock_llm(score=8)
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["scored"] == 1
    assert counts["errors"] == 0
    # matches land in 'new' status; get_matches_for_review returns them
    pending = store.get_matches_for_review(7)
    assert len(pending) == 1 and pending[0]["score"] == 8


def test_run_matching_skips_already_scored(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = _mock_llm(score=8)
    run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    counts2 = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts2["scored"] == 0  # already scored, skipped


def test_run_matching_scores_job(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    store.upsert_job(Job(title="Backend Eng", url="https://a.com/jobs/1", company_id=cid))
    llm = _mock_llm(score=9)
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["scored"] == 2  # company + job


def test_score_match_invalid_score_raises():
    llm = MagicMock(spec=LLMClient)
    llm.call_json.return_value = {"score": 15, "reasoning": "too high"}
    with pytest.raises(LLMError, match="Invalid score"):
        score_match(llm, RESUME, RV_CFG, "context")


def test_run_matching_handles_llm_error(tmp_path):
    store, rv_id, cid = _store_with_company(tmp_path)
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call_json.side_effect = LLMError("API down")
    counts = run_matching(RV_CFG, rv_id, RESUME, llm, store, MatchingConfig())
    assert counts["errors"] == 1
    assert counts["scored"] == 0
