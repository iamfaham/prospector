# tests/test_report.py
import csv
from pathlib import Path
from job_agent.stages.report import run_report
from job_agent.store import Store
from job_agent.models import Company, RoleVariant, Match, Contact, OutreachDraft, DraftType


def _full_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    cid = store.upsert_company(Company(
        name="Acme AI", source_url="https://a.com",
        funding_stage="Seed", funding_date="2026-06",
        raw_signal_text="Raised $5M",
    ))
    mid = store.insert_match(
        Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="strong Python match")
    )
    ctid = store.insert_contact(Contact(
        company_id=cid, name="Alice Smith", title="CTO",
        email="alice@acme.com", profile_url="https://li.com/alice",
    ))
    store.insert_outreach_draft(OutreachDraft(
        match_id=mid, contact_id=ctid, draft_type=DraftType.COLD_OUTREACH,
        message_text="Hi Alice, I saw Acme raised $5M...",
    ))
    return store


def test_creates_report_files(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    assert Path(paths["markdown"]).exists()
    assert Path(paths["csv"]).exists()


def test_markdown_contains_company_and_score(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    md = Path(paths["markdown"]).read_text()
    assert "Acme AI" in md
    assert "8/10" in md
    assert "Alice Smith" in md
    assert "Hi Alice" in md


def test_csv_has_correct_columns(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    with open(paths["csv"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Acme AI"
    assert rows[0]["score"] == "8"
    assert rows[0]["contact_name"] == "Alice Smith"


def test_empty_store_produces_valid_report(tmp_path):
    store = Store(db_path=str(tmp_path / "empty.db"))
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    assert Path(paths["markdown"]).exists()
    md = Path(paths["markdown"]).read_text()
    assert "Total matches: 0" in md
