# tests/test_people_finding.py
import pytest
from unittest.mock import MagicMock, patch
from prospector.stages.people_finding import run_people_finding
from prospector.store import Store
from prospector.llm.client import LLMClient
from prospector.config import PeopleSearchConfig
from prospector.models import Company, RoleVariant, Match, MatchStatus, Contact, Confidence
from prospector.connectors.web_search import WebSearchConnector

CFG = PeopleSearchConfig(paid_api=None)


def _populated_store(tmp_path, score=8):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    cid = store.upsert_company(Company(name="Acme AI", source_url="https://a.com"))
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=score, reasoning="good"))
    if score >= 7:
        store.update_match_status(mid, MatchStatus.ACCEPTED)
    return store, cid


def _mock_llm(found: bool, name="Alice Smith", title="CTO"):
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    llm.call.return_value = "Acme AI founder CEO LinkedIn"
    llm.call_json.return_value = {
        "found": found,
        "name": name if found else None,
        "title": title if found else None,
        "profile_url": None,
    }
    return llm


def test_finds_contact_and_writes_to_store(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    llm = _mock_llm(found=True)
    fake_connector = MagicMock(spec=WebSearchConnector)
    from prospector.models import RawResult
    fake_connector.search.return_value = [
        RawResult(url="https://li.com/alice", title="Alice Smith CTO Acme", snippet="...")
    ]
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    with patch("prospector.stages.people_finding.WebSearchConnector", return_value=fake_connector):
        counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 1
    contact = store.get_contact_for_company(cid)
    assert contact is not None
    assert contact.name == "Alice Smith"


def test_skips_below_threshold(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=5)
    llm = _mock_llm(found=True)
    counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 0
    assert store.get_contact_for_company(cid) is None


def test_not_found_records_zero(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    llm = _mock_llm(found=False)
    fake_connector = MagicMock(spec=WebSearchConnector)
    from prospector.models import RawResult
    fake_connector.search.return_value = [
        RawResult(url="https://x.com", title="unrelated", snippet="...")
    ]
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    with patch("prospector.stages.people_finding.WebSearchConnector", return_value=fake_connector):
        counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["not_found"] == 1


def test_skips_company_already_has_contact(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    store.insert_contact(Contact(company_id=cid, name="Bob", title="CEO"))
    llm = _mock_llm(found=True)
    counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 0  # already had a contact, skipped
