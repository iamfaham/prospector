# tests/test_review.py
"""Tests for the interactive review stage."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_agent.config import MatchingConfig, RoleVariantConfig
from job_agent.llm.client import LLMClient
from job_agent.models import Company, Match, MatchStatus, RoleVariant
from job_agent.stages.review import run_review
from job_agent.store import Store

_RV_CFG = RoleVariantConfig(name="be", resume="r.txt", keywords=["python"], seniority="mid")

_TAILOR_OK = {"company": "Acme AI", "files": [], "ok": True}
_TAILOR_ERR = {"company": "Acme AI", "files": [], "ok": False, "error": "LLM failed"}


def _setup(tmp_path) -> tuple[Store, int, int, dict, dict, dict]:
    store = Store(db_path=str(tmp_path / "test.db"))
    rv = RoleVariant(name="be", resume_path="r.txt", keywords=["python"], seniority="mid")
    rv_id = store.upsert_role_variant(rv)
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com",
                                       funding_stage="Seed", funding_amount="$5M"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="good fit"))
    rv_map = {rv_id: _RV_CFG}
    latex_sources = {rv_id: None}
    resume_texts = {"be": "5 years Python"}
    return store, rv_id, cid, rv_map, latex_sources, resume_texts


def _mock_llm():
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    return llm


def test_accept_submits_tailoring(tmp_path):
    store, rv_id, cid, rv_map, latex_sources, resume_texts = _setup(tmp_path)
    llm = _mock_llm()

    with patch("job_agent.stages.review._tailor_and_compile", return_value=_TAILOR_OK) as mock_t, \
         patch("builtins.input", return_value="a"):
        counts = run_review(store, rv_map, latex_sources, resume_texts,
                            MatchingConfig(), llm, "Faham", str(tmp_path / "reports"))

    assert counts["accepted"] == 1
    assert counts["rejected"] == 0
    mock_t.assert_called_once()
    # status updated in DB
    accepted = store.get_matches_above_threshold(7)
    assert len(accepted) == 1 and accepted[0].status == MatchStatus.ACCEPTED


def test_reject_updates_status(tmp_path):
    store, rv_id, cid, rv_map, latex_sources, resume_texts = _setup(tmp_path)
    llm = _mock_llm()

    with patch("job_agent.stages.review._tailor_and_compile", return_value=_TAILOR_OK) as mock_t, \
         patch("builtins.input", return_value="r"):
        counts = run_review(store, rv_map, latex_sources, resume_texts,
                            MatchingConfig(), llm, "Faham", str(tmp_path / "reports"))

    assert counts["rejected"] == 1
    mock_t.assert_not_called()
    # rejected match does not appear in accepted query
    assert store.get_matches_above_threshold(7) == []


def test_skip_leaves_status_new(tmp_path):
    store, rv_id, cid, rv_map, latex_sources, resume_texts = _setup(tmp_path)
    llm = _mock_llm()

    with patch("job_agent.stages.review._tailor_and_compile", return_value=_TAILOR_OK), \
         patch("builtins.input", return_value="s"):
        counts = run_review(store, rv_map, latex_sources, resume_texts,
                            MatchingConfig(), llm, "Faham", str(tmp_path / "reports"))

    assert counts["skipped"] == 1
    # still new — appears in next review
    pending = store.get_matches_for_review(7)
    assert len(pending) == 1


def test_quit_stops_early(tmp_path):
    store, rv_id, cid, rv_map, latex_sources, resume_texts = _setup(tmp_path)
    # add a second company
    cid2 = store.upsert_company(Company(name="Beta Inc", source_url="https://b.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid2, score=9, reasoning="great"))
    llm = _mock_llm()

    responses = iter(["q"])
    with patch("job_agent.stages.review._tailor_and_compile", return_value=_TAILOR_OK), \
         patch("builtins.input", side_effect=responses):
        counts = run_review(store, rv_map, latex_sources, resume_texts,
                            MatchingConfig(), llm, "Faham", str(tmp_path / "reports"))

    assert counts["accepted"] + counts["rejected"] + counts["skipped"] == 0


def test_no_pending_returns_early(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    llm = _mock_llm()
    counts = run_review(store, {}, {}, {}, MatchingConfig(), llm, "Faham",
                        str(tmp_path / "reports"))
    assert counts == {"accepted": 0, "rejected": 0, "skipped": 0}


def test_live_report_written(tmp_path):
    store, rv_id, cid, rv_map, latex_sources, resume_texts = _setup(tmp_path)
    llm = _mock_llm()
    reports_dir = tmp_path / "reports"

    with patch("job_agent.stages.review._tailor_and_compile", return_value=_TAILOR_OK), \
         patch("builtins.input", return_value="a"):
        run_review(store, rv_map, latex_sources, resume_texts,
                   MatchingConfig(), llm, "Faham", str(reports_dir))

    live = reports_dir / "live_report.md"
    assert live.exists()
    content = live.read_text()
    assert "Acme AI" in content
    assert "accepted" in content
