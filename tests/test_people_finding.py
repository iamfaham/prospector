# tests/test_people_finding.py
import pytest
from unittest.mock import MagicMock, patch
from prospector.stages.people_finding import run_people_finding, _find_via_skrapp, _find_via_apollo
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
    monkeypatch.setenv("TAVILY_API_KEY", "fake")
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
    monkeypatch.setenv("TAVILY_API_KEY", "fake")
    with patch("prospector.stages.people_finding.WebSearchConnector", return_value=fake_connector):
        counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["not_found"] == 1


def test_skips_company_already_has_contact(tmp_path, monkeypatch):
    store, cid = _populated_store(tmp_path, score=8)
    store.insert_contact(Contact(company_id=cid, name="Bob", title="CEO"))
    llm = _mock_llm(found=True)
    counts = run_people_finding(llm, store, CFG, threshold=7)
    assert counts["found"] == 0  # already had a contact, skipped


def test_find_via_skrapp_returns_contact(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "emails": [
            {"name": "Alice Smith", "email": "alice@acme.com", "title": "CEO"},
            {"name": "Bob Jones", "email": "bob@acme.com", "title": "Engineer"},
        ]
    }
    with patch("prospector.stages.people_finding.httpx.get", return_value=mock_resp):
        contact = _find_via_skrapp("acme.com", "test-key")

    assert contact is not None
    assert contact.name == "Alice Smith"
    assert contact.email == "alice@acme.com"
    assert contact.title == "CEO"
    assert contact.confidence == Confidence.HIGH
    assert contact.found_via == "skrapp"


def test_find_via_skrapp_returns_none_on_empty(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"emails": []}
    with patch("prospector.stages.people_finding.httpx.get", return_value=mock_resp):
        contact = _find_via_skrapp("acme.com", "test-key")
    assert contact is None


def test_find_via_apollo_returns_contact_without_email(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "people": [{
            "first_name": "Carol",
            "last_name": "White",
            "title": "CTO",
            "email": None,
            "linkedin_url": "https://linkedin.com/in/carolwhite",
        }]
    }
    with patch("prospector.stages.people_finding.httpx.post", return_value=mock_resp):
        contact = _find_via_apollo("Acme Corp", "test-key")

    assert contact is not None
    assert contact.name == "Carol White"
    assert contact.title == "CTO"
    assert contact.email is None
    assert contact.profile_url == "https://linkedin.com/in/carolwhite"
    assert contact.confidence == Confidence.MEDIUM
    assert contact.found_via == "apollo"


def test_find_via_apollo_returns_contact_with_email(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "people": [{
            "first_name": "Carol",
            "last_name": "White",
            "title": "CTO",
            "email": "carol@acme.com",
            "linkedin_url": "https://linkedin.com/in/carolwhite",
        }]
    }
    with patch("prospector.stages.people_finding.httpx.post", return_value=mock_resp):
        contact = _find_via_apollo("Acme Corp", "test-key")

    assert contact.email == "carol@acme.com"
    assert contact.confidence == Confidence.HIGH


def test_people_finding_skrapp_takes_priority(tmp_path, monkeypatch):
    """Skrapp is tried first; if it succeeds, Apollo and web search are skipped."""
    from prospector.stages.people_finding import run_people_finding
    from prospector.store import Store
    from prospector.models import Company, Match, MatchStatus, RoleVariant
    from prospector.config import PeopleSearchConfig

    store = Store(db_path=str(tmp_path / "test.db"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://acme.com"))
    rv_id = store.upsert_role_variant(RoleVariant(name="ai-eng", resume_path="r.pdf", keywords=[], seniority="mid"))
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="good"))
    store.update_match_status(mid, MatchStatus.ACCEPTED)

    llm = MagicMock()
    llm.is_over_budget.return_value = False

    skrapp_contact = {"emails": [{"name": "Alice", "email": "alice@acme.com", "title": "CEO"}]}

    mock_get = MagicMock()
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = skrapp_contact

    with patch("prospector.stages.people_finding.httpx.get", mock_get):
        counts = run_people_finding(
            llm=llm, store=store, config=PeopleSearchConfig(paid_api="skrapp"),
            threshold=7, skrapp_api_key="sk-key",
        )

    assert counts["found"] == 1
    contact = store.get_contact_for_company(cid)
    assert contact.found_via == "skrapp"
    assert contact.email == "alice@acme.com"
    llm.call.assert_not_called()  # LLM not used when Skrapp succeeds
