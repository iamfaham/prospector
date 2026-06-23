# tests/test_smoke.py
"""
End-to-end smoke test: source → review → report with mocked LLM and connectors.
No live API calls, no network.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from prospector.cli import app
from prospector.llm.client import LLMClient

RUNNER = CliRunner()

_QUERY = "python startup funding 2026"
_EXTRACT = json.dumps({
    "relevant": True,
    "company": {"name": "Acme AI", "funding_stage": "Seed",
                 "funding_amount": "$5M", "funding_date": "2026-06"},
    "job": None,
})
_EXTRACT2 = json.dumps({"relevant": False})   # skip DataFlow Inc from BigSet CSV
_SCORE = json.dumps({"score": 8, "reasoning": "Strong Python fit"})
_PEOPLE_QUERY = "Acme AI founder CEO LinkedIn"
_PEOPLE_VERIFY = json.dumps({"found": True, "name": "Alice Smith",
                              "title": "CTO", "profile_url": None})
_MESSAGE = "Hi Alice, I saw Acme raised $5M — I'd love to connect."

_RESPONSES = [_QUERY, _EXTRACT, _EXTRACT2, _SCORE, _PEOPLE_QUERY, _PEOPLE_VERIFY, _MESSAGE]


@pytest.fixture
def cfg_file(tmp_path, sample_resume_path):
    p = tmp_path / "config.yaml"
    p.write_text(f"""
role_variants:
  - name: backend-eng
    resume: {sample_resume_path}
    keywords: [python, go]
    seniority: mid-senior
sourcing:
  max_queries_per_role_per_run: 1
  funding_lookback_days: 30
matching:
  score_threshold_for_outreach: 7
llm:
  provider: openrouter
  model: anthropic/claude-haiku-4-5
people_search:
  paid_api: null
""")
    return str(p)


def _make_llm_mocks():
    idx = {"n": 0}

    def fake_call(self, system, user, **kwargs):
        r = _RESPONSES[idx["n"] % len(_RESPONSES)]
        idx["n"] += 1
        return r

    def fake_call_json(self, system, user):
        r = _RESPONSES[idx["n"] % len(_RESPONSES)]
        idx["n"] += 1
        return json.loads(r)

    def fake_is_over_budget(self):
        return False

    return fake_call, fake_call_json, fake_is_over_budget


def test_source_produces_live_report(tmp_path, cfg_file, bigset_csv_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("BIGSET_EXPORT_PATH", bigset_csv_path)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    fake_call, fake_call_json, fake_is_over_budget = _make_llm_mocks()

    from prospector.models import RawResult
    fake_ws = [RawResult(url="https://li.com/alice", title="Alice Smith CTO Acme", snippet="...")]

    fake_tailor_result = {"company": "Acme AI", "files": [], "ok": True}

    with patch("prospector.llm.client.OpenAI"), \
         patch.object(LLMClient, "call", fake_call), \
         patch.object(LLMClient, "call_json", fake_call_json), \
         patch.object(LLMClient, "is_over_budget", fake_is_over_budget), \
         patch("prospector.stages.people_finding.WebSearchConnector") as mock_ws, \
         patch("prospector.stages.review._tailor_and_compile", return_value=fake_tailor_result):

        mock_ws.return_value.search.return_value = fake_ws
        # 'a' accepts the match; \n flushes the prompt loop
        result = RUNNER.invoke(app, ["source", "--config", cfg_file], input="a\n")

    assert result.exit_code == 0, f"source failed:\n{result.output}\n{result.stderr}"
    live = tmp_path / "reports" / "live_report.md"
    assert live.exists(), "live_report.md not written"
    assert "Acme AI" in live.read_text()


def test_report_produces_markdown(tmp_path, cfg_file, bigset_csv_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("BIGSET_EXPORT_PATH", bigset_csv_path)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    fake_call, fake_call_json, fake_is_over_budget = _make_llm_mocks()

    from prospector.models import RawResult
    fake_ws = [RawResult(url="https://li.com/alice", title="Alice Smith CTO Acme", snippet="...")]

    fake_tailor = {"company": "Acme AI", "files": [], "ok": True}

    with patch("prospector.llm.client.OpenAI"), \
         patch.object(LLMClient, "call", fake_call), \
         patch.object(LLMClient, "call_json", fake_call_json), \
         patch.object(LLMClient, "is_over_budget", fake_is_over_budget), \
         patch("prospector.stages.people_finding.WebSearchConnector") as mock_ws, \
         patch("prospector.stages.review._tailor_and_compile", return_value=fake_tailor):

        mock_ws.return_value.search.return_value = fake_ws

        # source + accept
        RUNNER.invoke(app, ["source", "--config", cfg_file], input="a\n")

        # reset LLM call counter for report stage
        fake_call, fake_call_json, fake_is_over_budget = _make_llm_mocks()
        with patch.object(LLMClient, "call", fake_call), \
             patch.object(LLMClient, "call_json", fake_call_json), \
             patch.object(LLMClient, "is_over_budget", fake_is_over_budget), \
             patch("prospector.stages.people_finding.WebSearchConnector") as mock_ws2:
            mock_ws2.return_value.search.return_value = fake_ws
            result2 = RUNNER.invoke(app, ["report", "--config", cfg_file])

    assert result2.exit_code == 0, f"report failed:\n{result2.output}"
    reports = list((tmp_path / "reports").rglob("report.md"))
    assert len(reports) >= 1
    md = reports[0].read_text()
    assert "Job Agent Report" in md
    assert "Total matches:" in md
