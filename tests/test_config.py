import pytest
import textwrap
from job_agent.config import load_config, Config

MINIMAL_YAML = textwrap.dedent("""\
    role_variants:
      - name: backend-eng
        resume: resumes/backend.txt
        keywords: [python, go]
        seniority: mid-senior
""")

@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(MINIMAL_YAML)
    return str(p)

def test_load_minimal_config(config_file):
    cfg = load_config(config_file)
    assert len(cfg.role_variants) == 1
    assert cfg.role_variants[0].name == "backend-eng"
    assert cfg.role_variants[0].keywords == ["python", "go"]

def test_defaults_applied(config_file):
    cfg = load_config(config_file)
    assert cfg.sourcing.max_queries_per_role_per_run == 8
    assert cfg.sourcing.funding_lookback_days == 30
    assert cfg.matching.score_threshold_for_outreach == 7
    assert cfg.llm.provider == "openrouter"
    assert cfg.people_search.paid_api is None

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")

def test_invalid_config_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("role_variants: not_a_list")
    with pytest.raises(Exception):
        load_config(str(p))
