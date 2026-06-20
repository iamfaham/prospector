# tests/test_connectors.py
import pytest
from job_agent.connectors.base import SourceConnector
from job_agent.connectors.web_search import WebSearchConnector
from job_agent.connectors.bigset import BigSetConnector
from job_agent.models import RawResult

def test_web_search_connector_is_source_connector():
    c = WebSearchConnector(api_key="key", connector_type="funding_news")
    assert isinstance(c, SourceConnector)
    assert c.connector_type == "funding_news"

def test_bigset_connector_is_source_connector(bigset_csv_path):
    c = BigSetConnector(csv_path=bigset_csv_path)
    assert isinstance(c, SourceConnector)
    assert c.connector_type == "bigset"

def test_bigset_returns_raw_results(bigset_csv_path):
    c = BigSetConnector(csv_path=bigset_csv_path)
    results = c.search("any query")
    assert len(results) == 2
    assert all(isinstance(r, RawResult) for r in results)
    assert results[0].title == "Acme AI"
    assert results[1].title == "DataFlow Inc"

def test_bigset_missing_file_returns_empty():
    c = BigSetConnector(csv_path="/nonexistent/path.csv")
    assert c.search("q") == []

def test_web_search_connector_returns_results(monkeypatch):
    import httpx

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"url": "https://example.com", "title": "Acme raises $5M", "content": "Acme AI seed round"},
            ]}

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: FakeResp())
    c = WebSearchConnector(api_key="key", connector_type="funding_news")
    results = c.search("AI startup funding 2026")
    assert len(results) == 1
    assert results[0].title == "Acme raises $5M"
    assert results[0].snippet == "Acme AI seed round"


def test_web_search_connector_handles_http_error(monkeypatch):
    import httpx
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(httpx, "post", fake_post)
    c = WebSearchConnector(api_key="key", connector_type="job_board")
    results = c.search("python startup jobs")
    assert results == []  # errors return empty, not raise
