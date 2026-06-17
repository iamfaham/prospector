# tests/test_smoke.py
"""
End-to-end smoke test: full 'run' command with fixture connectors and mocked LLM.
No live API calls, no network.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from job_agent.cli import app
from job_agent.llm.client import LLMClient

RUNNER = CliRunner()

# Fixed LLM responses in call order
_QUERY = "python startup funding 2026"
_EXTRACT = json.dumps({
    "relevant": True,
    "company": {"name": "Acme AI", "funding_stage": "Seed",
                 "funding_amount": "$5M", "funding_date": "2026-06"},
    "job": None,
})
_SCORE = json.dumps({"score": 8, "reasoning": "Strong Python fit"})
_PEOPLE_QUERY = "Acme AI founder CEO LinkedIn"
_PEOPLE_VERIFY = json.dumps({"found": True, "name": "Alice Smith",
                              "title": "CTO", "profile_url": None})
_MESSAGE = "Hi Alice, I saw Acme raised $5M — I'd love to connect."

_RESPONSES = [_QUERY, _EXTRACT, _SCORE, _PEOPLE_QUERY, _PEOPLE_VERIFY, _MESSAGE]


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


def test_run_produces_report(tmp_path, cfg_file, bigset_csv_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("BIGSET_EXPORT_PATH", bigset_csv_path)
    monkeypatch.setenv("SERPER_API_KEY", "fake-key")
    monkeypatch.chdir(tmp_path)

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

    from job_agent.models import RawResult
    fake_ws_results = [RawResult(url="https://li.com/alice",
                                  title="Alice Smith CTO Acme", snippet="...")]

    with patch("job_agent.llm.client.OpenAI"), \
         patch.object(LLMClient, "call", fake_call), \
         patch.object(LLMClient, "call_json", fake_call_json), \
         patch.object(LLMClient, "is_over_budget", fake_is_over_budget), \
         patch("job_agent.stages.people_finding.WebSearchConnector") as mock_ws:

        mock_ws.return_value.search.return_value = fake_ws_results

        result = RUNNER.invoke(app, ["--config", cfg_file])

    assert result.exit_code == 0, f"CLI failed:\n{result.output}"
    reports = list((tmp_path / "reports").rglob("report.md"))
    assert len(reports) >= 1
    md = reports[0].read_text()
    assert "Job Agent Report" in md
    assert "Total matches:" in md
